"""Quality gate CLI: exit codes, gate thresholds, outputs matching the API, contracts, safety."""

import json
from pathlib import Path

import pytest

from app import cli
from app.services import contract as contracts
from app.services import profiler
from app.services.analysis import run_analysis
from tests.conftest import load, rows_csv, upload
from tests.test_api import SECRET

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"

# Varied numbers and balanced categories: no likely or potential issues, at most observations.
CLEAN = rows_csv("x,group", [f"{(i * 37) % 101},{'abc'[i % 3]}" for i in range(60)])
# A constant column is a likely issue of low severity.
FAILING = rows_csv("x,const", [f"{(i * 37) % 101},same" for i in range(60)])
# Missing values below the likely-issue level are a potential issue only (a warning).
WARNING = rows_csv("x,y", [f"{(i * 37) % 101},{'' if i % 10 == 0 else i}" for i in range(60)])


def write(tmp_path: Path, text: str | bytes, name: str = "data.csv") -> Path:
    path = tmp_path / name
    # Exact bytes: text mode would turn LF into CRLF on Windows and change the file hash.
    path.write_bytes(text if isinstance(text, bytes) else text.encode("utf-8"))
    return path


def run(capsys, *args) -> tuple[int, str, str]:
    code = cli.main([str(a) for a in args])
    out = capsys.readouterr()
    return code, out.out, out.err


def kinds(text: str) -> set[str]:
    return {f.kind.value for f in run_analysis(load(text)).findings}


# --- Fixtures behave as described ---------------------------------------------------------------


def test_fixture_datasets_have_the_intended_kinds():
    assert kinds(CLEAN) <= {"observation"}
    assert "likely_issue" in kinds(FAILING)
    assert "potential_issue" in kinds(WARNING) and "likely_issue" not in kinds(WARNING)


# --- Exit codes ---------------------------------------------------------------------------------


def test_clean_dataset_passes(tmp_path, capsys):
    code, out, err = run(capsys, "check", write(tmp_path, CLEAN))
    assert code == cli.EXIT_PASSED and "PASSED" in out and err == ""


def test_failing_dataset_fails_the_default_gate(tmp_path, capsys):
    code, out, _ = run(capsys, "check", write(tmp_path, FAILING))
    assert code == cli.EXIT_FAILED and "FAILED" in out and "constant_column" in out


def test_warning_dataset_passes_by_default_and_fails_on_potential_issues(tmp_path, capsys):
    path = write(tmp_path, WARNING)
    assert run(capsys, "check", path)[0] == cli.EXIT_PASSED
    code, out, _ = run(capsys, "check", path, "--fail-on", "potential_issue")
    assert code == cli.EXIT_FAILED and "potential_issue" in out


def test_fail_on_never_reports_without_failing(tmp_path, capsys):
    code, out, _ = run(capsys, "check", write(tmp_path, FAILING), "--fail-on", "never")
    assert code == cli.EXIT_PASSED and "never fails" in out


def test_min_severity_ignores_lower_severities(tmp_path, capsys):
    path = write(tmp_path, FAILING)  # its likely issue is low severity
    assert run(capsys, "check", path, "--min-severity", "low")[0] == cli.EXIT_FAILED
    assert run(capsys, "check", path, "--min-severity", "medium")[0] == cli.EXIT_PASSED


def test_incomplete_analysis_exits_3_unless_the_gate_already_failed(tmp_path, capsys, monkeypatch):
    def broken(frame):
        raise RuntimeError("stage failure with a value that must not leak: " + SECRET)

    monkeypatch.setattr(profiler, "duplicate_rows", broken)
    code, out, err = run(capsys, "check", write(tmp_path, CLEAN))
    assert code == cli.EXIT_INCOMPLETE and "INCOMPLETE" in out and "duplicates" in out
    assert SECRET not in out + err
    assert run(capsys, "check", write(tmp_path, FAILING, "f.csv"))[0] == cli.EXIT_FAILED


def test_observations_never_gate():
    from app.models.schemas import Category, Finding, FindingKind, Severity

    obs = Finding(code="x", kind=FindingKind.observation, severity=Severity.high, category=Category.target,
                  title="t", explanation="e", why_it_matters="w", recommendation="r", columns=[], evidence={})
    assert cli.gating([obs], "inconclusive", "info") == []


# --- Input errors -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make_args", "message"),
    [
        (lambda p: ["check", p.parent / "missing.csv"], "does not exist"),
        (lambda p: ["check", p, "--target", SECRET], "target column"),
        (lambda p: ["check", p, "--report", p.parent / "out.txt"], ".json or .html"),
    ],
)
def test_input_errors_exit_2_with_a_safe_message(tmp_path, capsys, make_args, message):
    code, out, err = run(capsys, *make_args(write(tmp_path, CLEAN)))
    assert code == cli.EXIT_USAGE and message in err and out == ""
    assert "Traceback" not in err and SECRET not in err


def test_invalid_csv_exits_2(tmp_path, capsys):
    code, _, err = run(capsys, "check", write(tmp_path, b"a,b\n1,2,3\n"))
    assert code == cli.EXIT_USAGE and "fields" in err


def test_size_limit_comes_from_the_same_environment_variables(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DATASENTRY_MAX_UPLOAD_BYTES", "100")
    code, _, err = run(capsys, "check", write(tmp_path, CLEAN))
    assert code == cli.EXIT_USAGE and "maximum size of 100 bytes" in err


def test_bad_arguments_exit_2(tmp_path, capsys):
    with pytest.raises(SystemExit) as info:
        cli.main(["check", str(write(tmp_path, CLEAN)), "--fail-on", "everything"])
    assert info.value.code == 2


# --- Outputs match the API ----------------------------------------------------------------------


def test_result_file_matches_the_analyze_endpoint(tmp_path, capsys, client):
    text = (SAMPLES / "customer_churn.csv").read_text(encoding="utf-8")
    out_path = tmp_path / "result.json"
    run(capsys, "check", write(tmp_path, text, "customer_churn.csv"), "--target", "churned",
        "--result", out_path, "--fail-on", "never")
    api = upload(client, "/api/analyze", text, filename="customer_churn.csv", target_column="churned").json()
    assert json.loads(out_path.read_text(encoding="utf-8")) == api


def test_json_report_matches_the_report_endpoint_except_the_timestamp(tmp_path, capsys, client):
    text = rows_csv("id,score,label", [f"{i},{i * 1.5},{'yn'[i % 2]}" for i in range(40)])
    out_path = tmp_path / "report.json"
    run(capsys, "check", write(tmp_path, text), "--target", "label", "--report", out_path, "--fail-on", "never")
    mine = json.loads(out_path.read_text(encoding="utf-8"))
    api = upload(client, "/api/report", text, target_column="label", format="json").json()
    for doc in (mine, api):
        doc["metadata"].pop("generated_at")
    assert mine == api


def test_html_report_is_written_escaped_and_script_free(tmp_path, capsys):
    text = rows_csv('id,"<script>alert(1)</script>"', [f"{i},{i}" for i in range(30)])
    out_path = tmp_path / "report.html"
    run(capsys, "check", write(tmp_path, text), "--report", out_path, "--fail-on", "never")
    html = out_path.read_text(encoding="utf-8")
    assert html.lstrip().lower().startswith("<!doctype html>")
    assert "<script>" not in html and "&lt;script&gt;" in html


def test_json_summary_lists_the_gating_findings(tmp_path, capsys):
    code, out, _ = run(capsys, "check", write(tmp_path, FAILING), "--format", "json")
    summary = json.loads(out)
    assert code == cli.EXIT_FAILED
    assert summary["gate"] == {"fail_on": "likely_issue", "min_severity": "info", "passed": False, "exit_code": 1}
    assert [f["code"] for f in summary["gating_findings"]] == ["constant_column"]
    assert summary["analysis_status"] == "complete" and summary["contract"] is None


def test_output_is_deterministic(tmp_path, capsys):
    path = write(tmp_path, FAILING)
    first = run(capsys, "check", path, "--format", "json")[1]
    assert run(capsys, "check", path, "--format", "json")[1] == first


# --- Parsing options ----------------------------------------------------------------------------


def test_parsing_options_are_applied(tmp_path, capsys):
    path = write(tmp_path, CLEAN.replace(",", ";"))
    summary = json.loads(run(capsys, "check", path, "--delimiter", "semicolon", "--format", "json")[1])
    assert summary["n_columns"] == 2


# --- Contracts ----------------------------------------------------------------------------------


def contract_file(tmp_path: Path, text: str, edit=None) -> Path:
    spec = json.loads(contracts.export_contract(load(text), None).model_dump_json())
    if edit:
        edit(spec)
    return write(tmp_path, json.dumps(spec), "contract.json")


def test_passing_contract(tmp_path, capsys):
    code, out, _ = run(capsys, "check", write(tmp_path, CLEAN), "--contract", contract_file(tmp_path, CLEAN))
    assert code == cli.EXIT_PASSED and "Contract: passed" in out


def test_contract_violations_fail_the_gate(tmp_path, capsys):
    def tighten(spec):
        next(c for c in spec["columns"] if c["name"] == "x")["max"] = 10

    code, out, _ = run(capsys, "check", write(tmp_path, CLEAN), "--contract", contract_file(tmp_path, CLEAN, tighten),
                       "--format", "json")
    summary = json.loads(out)
    assert code == cli.EXIT_FAILED and summary["contract"]["passed"] is False
    assert "contract_max" in {f["code"] for f in summary["gating_findings"]}


def test_contract_and_parsing_flags_conflict(tmp_path, capsys):
    code, _, err = run(capsys, "check", write(tmp_path, CLEAN), "--contract", contract_file(tmp_path, CLEAN),
                       "--delimiter", "semicolon")
    assert code == cli.EXIT_USAGE and "contract's parsing options" in err


def test_invalid_contract_exits_2_without_echoing_it(tmp_path, capsys):
    bad = write(tmp_path, SECRET, "contract.json")
    code, _, err = run(capsys, "check", write(tmp_path, CLEAN), "--contract", bad)
    assert code == cli.EXIT_USAGE and "contract is not valid" in err and SECRET not in err


# --- Terminal safety ----------------------------------------------------------------------------


def test_control_characters_in_dataset_strings_are_not_printed(tmp_path, capsys):
    text = 'id,"evil\x1b[31mname"\n' + "".join(f"{i},same\n" for i in range(30))
    code, out, _ = run(capsys, "check", write(tmp_path, text))
    assert code == cli.EXIT_FAILED
    assert "\x1b" not in out and "evil�[31mname" in out


def test_safe_keeps_ordinary_unicode():
    assert cli._safe("température 名前") == "température 名前"
    assert cli._safe("a\tb\x9bc") == "a�b�c"
