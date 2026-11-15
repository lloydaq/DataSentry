"""Data contracts: export, untrusted-contract validation, checking and the API."""

import json
from pathlib import Path

import pytest

from app.services import contract
from app.services.loader import DatasetError, load_csv, parse_options
from tests.conftest import TEST_LIMITS, load, rows_csv, upload
from tests.test_api import SECRET, assert_safe_error

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"

BASE = rows_csv(
    "id,amount,plan,active,joined,note",
    [f"{i},{i * 2.5},{'ab'[i % 2]},{'true' if i % 3 else 'false'},2024-01-{i % 28 + 1:02d},free text {i}" for i in range(30)],
)


def exported(text: str = BASE, target=None) -> dict:
    return json.loads(contract.export_contract(load(text), target).model_dump_json())


def check(text: str, spec: dict):
    parsed = contract.parse_contract(json.dumps(spec).encode(), TEST_LIMITS)
    return contract.check_contract(load(text), parsed)


def column(spec: dict, name: str) -> dict:
    return next(c for c in spec["columns"] if c["name"] == name)


# --- Export -------------------------------------------------------------------------------------


def test_export_infers_types_ranges_categories_and_uniqueness():
    spec = exported(target="plan")
    assert spec["contract_version"] == "1" and spec["target_column"] == "plan"
    assert spec["source"]["n_rows"] == 30 and len(spec["source"]["sha256"]) == 64
    assert spec["parsing"] == {"delimiter": "comma", "encoding": "utf-8", "missing_values": []}
    assert column(spec, "id") | {} == {**column(spec, "id"), "type": "numeric", "unique": True, "min": 0.0, "max": 29.0}
    assert column(spec, "amount")["min"] == 0.0 and column(spec, "amount")["max"] == 72.5
    assert column(spec, "plan")["allowed_values"] == ["a", "b"]
    assert column(spec, "active")["type"] == "boolean"
    assert column(spec, "joined")["type"] == "datetime"
    # 30 distinct notes is within the categorical rule (at most 50), so every value is listed;
    # an exported contract is a draft to edit.
    assert column(spec, "note")["type"] == "categorical" and len(column(spec, "note")["allowed_values"]) == 30
    assert all(c["nullable"] is False and c["required"] is True for c in spec["columns"])


def test_export_marks_columns_with_missing_values_nullable_and_empty_columns_as_text():
    spec = exported(rows_csv("a,b", [f"{i if i % 2 else ''}," for i in range(30)]))
    assert column(spec, "a")["nullable"] is True
    assert column(spec, "b") | {} == {**column(spec, "b"), "type": "text", "nullable": True}


def test_export_skips_allowed_values_for_many_categories():
    n = contract.EXPORT_MAX_ALLOWED_VALUES + 1
    rows = [f"c{i % n}" for i in range(n * 3)]
    spec = exported(rows_csv("cat", rows))
    assert column(spec, "cat")["type"] == "categorical" and column(spec, "cat")["allowed_values"] is None


def test_export_records_parsing_options():
    data = load_csv(b"a;b\n1;x\n2;?\n", TEST_LIMITS, "d.csv", parse_options("semicolon", "latin-1", "?"))
    spec = contract.export_contract(data, None)
    assert spec.parsing.delimiter == "semicolon" and spec.parsing.missing_values == ["?"]
    assert contract.contract_options(spec) == data.options


def test_export_rejects_unknown_target():
    with pytest.raises(DatasetError) as info:
        contract.export_contract(load(BASE), "nope")
    assert info.value.code == "unknown_target_column"


# --- Round trip and determinism -----------------------------------------------------------------


def test_round_trip_has_no_violations():
    result = check(BASE, exported())
    assert result.passed and result.violations == [] and result.findings == []
    assert result.n_columns_checked == 6 and result.n_rules_checked > 6


def test_round_trip_on_the_sample_dataset():
    raw = (SAMPLES / "customer_churn.csv").read_bytes()
    data = load_csv(raw, TEST_LIMITS, "c.csv")
    spec = contract.export_contract(data, "churned")
    assert contract.check_contract(data, spec).passed


def test_export_is_deterministic():
    assert exported() == exported()


# --- Violations ---------------------------------------------------------------------------------


def test_missing_required_column_and_optional_column():
    spec = exported()
    column(spec, "note")["required"] = False
    text = rows_csv("id,amount,plan,active", [f"{i},1,a,true" for i in range(3)])
    result = check(text, spec)
    rules = {(v.rule, v.column) for v in result.violations}
    assert ("missing_column", "joined") in rules and ("missing_column", "note") not in rules
    finding = next(f for f in result.findings if f.code == "contract_missing_column")
    assert finding.kind == "likely_issue" and finding.severity == "high"


def test_unexpected_columns_only_when_extra_columns_are_disallowed():
    spec = exported()
    text = BASE.replace("note\n", "note,extra\n", 1).replace("\n", ",x\n").replace("note,extra,x\n", "note,extra\n", 1)
    assert check(text, spec).passed
    spec["allow_extra_columns"] = False
    assert [(v.rule, v.column) for v in check(text, spec).violations] == [("unexpected_column", "extra")]


def test_type_violations_report_counts_and_row_numbers_without_values():
    spec = exported()
    rows = BASE.splitlines()
    rows[3] = rows[3].replace(",5.0,", f",{SECRET},")  # data row 3 (id 2)
    rows[5] = rows[5].replace("2024-01-05", "yesterday")  # data row 5
    result = check("\n".join(rows) + "\n", spec)
    by_rule = {(v.rule, v.column): v for v in result.violations}
    amount = by_rule[("type", "amount")]
    assert amount.n_rows == 1 and amount.example_rows == [3]
    assert by_rule[("type", "joined")].example_rows == [5]
    assert SECRET not in result.model_dump_json()


def test_infinity_is_not_a_valid_number():
    spec = {"contract_version": "1", "parsing": {"delimiter": "comma", "encoding": "utf-8", "missing_values": []},
            "columns": [{"name": "x", "type": "numeric"}]}
    assert [v.rule for v in check("x\n1\ninf\n", spec).violations] == ["type"]


def test_boolean_type_accepts_true_false_in_any_case():
    spec = {"contract_version": "1", "parsing": {"delimiter": "comma", "encoding": "utf-8", "missing_values": []},
            "columns": [{"name": "b", "type": "boolean"}]}
    assert check("b\nTRUE\nfalse\n", spec).passed
    assert check("b\nyes\nfalse\n", spec).violations[0].example_rows == [1]


def test_nullability_uniqueness_ranges_and_allowed_values():
    spec = exported()
    column(spec, "amount")["min"], column(spec, "amount")["max"] = 3.0, 70.0
    rows = BASE.splitlines()
    rows[1] = rows[1].replace("0,0.0,a", "0,,c", 1)  # missing amount, plan outside the list
    rows[2] = rows[2].replace("1,", "0,", 1)  # duplicate id 0
    result = check("\n".join(rows) + "\n", spec)
    got = {(v.rule, v.column): v for v in result.violations}
    assert got[("not_nullable", "amount")].example_rows == [1]
    assert got[("unique", "id")].n_rows == 2 and got[("unique", "id")].example_rows == [1, 2]
    assert got[("allowed_values", "plan")].example_rows == [1]
    assert got[("max", "amount")].example_rows == [30]  # only 72.5 is above 70
    assert got[("min", "amount")].example_rows == [2]  # 2.5 is below 3; row 1 is missing, not low
    assert not result.passed


def test_missing_values_do_not_count_as_range_type_or_allowed_violations():
    spec = {"contract_version": "1", "parsing": {"delimiter": "comma", "encoding": "utf-8", "missing_values": []},
            "columns": [{"name": "x", "type": "numeric", "min": 0, "max": 1},
                        {"name": "c", "type": "categorical", "allowed_values": ["a"]}]}
    assert check("x,c\n,\n0.5,a\n", spec).passed


def test_contract_parsing_options_are_used_for_missing_tokens():
    spec = exported(rows_csv("x", [str(i) for i in range(30)]))
    spec["parsing"]["missing_values"] = ["-999"]
    column(spec, "x")["nullable"] = False
    data = load_csv(b"x\n1\n-999\n", TEST_LIMITS, "d.csv", contract.contract_options(
        contract.parse_contract(json.dumps(spec).encode(), TEST_LIMITS)))
    result = contract.check_contract(data, contract.parse_contract(json.dumps(spec).encode(), TEST_LIMITS))
    assert [(v.rule, v.example_rows) for v in result.violations] == [("not_nullable", [2])]


def test_example_rows_are_capped():
    spec = {"contract_version": "1", "parsing": {"delimiter": "comma", "encoding": "utf-8", "missing_values": []},
            "columns": [{"name": "x", "type": "numeric", "max": 0}]}
    v = check(rows_csv("x", [str(i + 1) for i in range(50)]), spec).violations[0]
    assert v.n_rows == 50 and len(v.example_rows) == contract.VIOLATION_EXAMPLES_LIMIT


# --- Untrusted contract validation --------------------------------------------------------------


def bad(spec_or_raw) -> DatasetError:
    raw = spec_or_raw if isinstance(spec_or_raw, bytes) else json.dumps(spec_or_raw).encode()
    with pytest.raises(DatasetError) as info:
        contract.parse_contract(raw, TEST_LIMITS)
    assert info.value.code == "invalid_contract"
    return info.value


def minimal(**changes) -> dict:
    spec = {"contract_version": "1", "parsing": {"delimiter": "comma", "encoding": "utf-8", "missing_values": []},
            "columns": [{"name": "x", "type": "numeric"}]}
    spec.update(changes)
    return spec


@pytest.mark.parametrize(
    "spec",
    [
        b"not json",
        b"[]",
        minimal(contract_version="2"),
        minimal(unknown_key=True),
        minimal(columns=[{"name": "x", "type": "numeric", "regex": ".*"}]),
        minimal(columns=[{"name": "x", "type": "empty"}]),
        minimal(columns=[{"name": "x", "type": "numeric"}, {"name": "x", "type": "text"}]),
        minimal(columns=[{"name": " ", "type": "text"}]),
        minimal(columns=[{"name": "x", "type": "numeric", "min": 5, "max": 1}]),
        minimal(columns=[{"name": "x", "type": "text", "min": 1}]),
        minimal(columns=[{"name": "x", "type": "numeric", "allowed_values": ["1"]}]),
        minimal(columns=[{"name": "x", "type": "categorical", "allowed_values": ["v" * 201]}]),
        minimal(columns=[{"name": "x", "type": "categorical", "allowed_values": [str(i) for i in range(1001)]}]),
        minimal(target_column="y"),
        minimal(parsing={"delimiter": "regex", "encoding": "utf-8", "missing_values": []}),
        b'{"contract_version": "1", "parsing": {"delimiter": "comma", "encoding": "utf-8", "missing_values": []}, "columns": [{"name": "x", "type": "numeric", "max": NaN}]}',
    ],
)
def test_invalid_contracts_are_rejected(spec):
    bad(spec)


def test_too_many_columns_and_oversized_contracts_are_rejected():
    many = minimal(columns=[{"name": f"c{i}", "type": "text"} for i in range(TEST_LIMITS.max_columns + 1)])
    assert "columns" in bad(many).message
    huge = b" " * (contract.CONTRACT_MAX_BYTES + 1)
    assert "larger" in bad(huge).message


def test_invalid_contract_messages_do_not_echo_content():
    error = bad(minimal(columns=[{"name": SECRET, "type": "nope"}]))
    assert SECRET not in error.message


# --- API ----------------------------------------------------------------------------------------


def test_export_endpoint_and_check_round_trip(client):
    spec = upload(client, "/api/contract/export", BASE, target_column="plan").json()
    assert spec["target_column"] == "plan"
    response = client.post(
        "/api/contract/check",
        files={"file": ("d.csv", BASE.encode()), "contract": ("c.json", json.dumps(spec).encode())},
    )
    assert response.status_code == 200 and response.json()["passed"] is True


def test_check_endpoint_reads_the_file_with_the_contract_options(client):
    text = BASE.replace(",", ";")
    spec = upload(client, "/api/contract/export", text, delimiter="semicolon").json()
    body = client.post(
        "/api/contract/check",
        files={"file": ("d.csv", text.encode()), "contract": ("c.json", json.dumps(spec).encode())},
        data={"delimiter": "comma"},  # ignored: the contract's options win
    ).json()
    assert body["passed"] is True and body["dataset"]["parsing"]["delimiter"] == "semicolon"


def test_check_endpoint_reports_violations(client):
    spec = exported()
    column(spec, "amount")["max"] = 10
    body = client.post(
        "/api/contract/check",
        files={"file": ("d.csv", BASE.encode()), "contract": ("c.json", json.dumps(spec).encode())},
    ).json()
    assert body["passed"] is False
    assert {v["rule"] for v in body["violations"]} == {"max"}
    assert body["findings"][0]["code"] == "contract_max"


def test_check_endpoint_errors_are_safe(client):
    response = client.post(
        "/api/contract/check",
        files={"file": ("d.csv", BASE.encode()), "contract": ("c.json", SECRET.encode())},
    )
    assert_safe_error(response, 422, "invalid_contract")
    missing = client.post("/api/contract/check", files={"file": ("d.csv", BASE.encode())})
    assert_safe_error(missing, 422, "missing_file")
