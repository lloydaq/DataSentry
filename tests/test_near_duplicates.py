"""Near-duplicate rows: normalized grouping, ignored identifiers, bounds and the finding."""

import pytest

from app.services import findings, profiler
from app.services.analysis import run_analysis
from tests.conftest import load, rows_csv, upload


def near(text: str):
    return run_analysis(load(text)).near_duplicates


def finding(text: str):
    return next((f for f in run_analysis(load(text)).findings if f.code == "near_duplicate_rows"), None)


# --- What counts as a near-duplicate ------------------------------------------------------------


def test_case_spacing_and_punctuation_variants_are_grouped():
    text = "name,city\nAlice Smith,Paris\nalice   smith,PARIS\nBob,Rome\nBob.,rome!\nCarl,Oslo\n"
    n = near(text)
    assert n.status == "computed"
    assert n.example_groups == [[0, 1], [2, 3]]
    assert (n.n_groups, n.n_rows_involved) == (2, 4)
    assert n.rows_involved_fraction == pytest.approx(0.8)


def test_numbers_match_to_six_significant_digits():
    assert near("v,k\n10.0,a\n10.0000001,a\n").n_groups == 1
    assert near("v,k\n10.0,a\n10.1,a\n").n_groups == 0
    assert near("v,k\n123456,a\n123456.4,a\n").n_groups == 1  # equal to 6 significant digits


def test_exact_duplicates_are_left_to_the_exact_check():
    assert near("a,b\nx,1\nx,1\nx,1\n").n_groups == 0


def test_typos_are_not_matched():
    assert near("name,city\nAlice,Paris\nAlicia,Paris\n").n_groups == 0


def test_unicode_compatibility_forms_match():
    assert near("w,k\nＡＢＣ,1\nabc,1\n").n_groups == 1


def test_missing_values_equal_each_other():
    n = near("a,b,c\nX,,1\nx,,1\n")
    assert n.n_groups == 1 and n.example_groups == [[0, 1]]


def test_identifier_like_columns_are_ignored_but_never_create_groups_alone():
    # 30 rows with a unique id: rows 0 and 1 differ only in formatting, all others are distinct.
    rows = ["0,Alice Smith,Paris", "1,alice smith,paris"] + [f"{i},person{i},city{i}" for i in range(2, 30)]
    n = near(rows_csv("id,name,city", rows))
    assert "id" in n.columns_ignored and n.example_groups == [[0, 1]]
    # Rows identical apart from the id are not near-duplicates: formatting must differ.
    same = [f"{i},Alice Smith,Paris" for i in range(30)]
    assert near(rows_csv("id,name,city", same)).n_groups == 0


def test_empty_columns_are_ignored():
    n = near("a,empty\nX,\nx,\n")
    assert "empty" in n.columns_ignored and n.n_groups == 1


def test_differing_columns_are_counted_and_ordered():
    text = "name,city,v\nAnn,Rome,1\nann,Rome,1\nBen,Oslo,2\nben,OSLO,2\n"
    n = near(text)
    assert [(d.column, d.n_groups) for d in n.differing_columns] == [("name", 2), ("city", 1)]


def test_examples_are_bounded(monkeypatch):
    monkeypatch.setattr(profiler, "NEAR_DUPLICATE_EXAMPLES_LIMIT", 3)
    monkeypatch.setattr(profiler, "NEAR_DUPLICATE_GROUP_EXAMPLE_ROWS", 2)
    rows = [f"Name{g}{'.' * k},{g}" for g in range(5) for k in range(4)]
    n = near(rows_csv("name,g", rows))
    assert n.n_groups == 5 and len(n.example_groups) == 3
    assert all(len(group) == 2 for group in n.example_groups)


# --- Bounds -------------------------------------------------------------------------------------


def test_large_tables_are_skipped_and_say_so(monkeypatch):
    monkeypatch.setattr(profiler, "NEAR_DUPLICATE_CELL_LIMIT", 5)
    result = run_analysis(load("a,b,c\nX,1,2\nx,1,2\n"))
    n = result.near_duplicates
    assert n.status == "skipped" and "compared cells" in n.reason
    assert all(f.code != "near_duplicate_rows" for f in result.findings)
    assert next(s for s in result.stages if s.name == "near_duplicates").status == "completed"


def test_nothing_left_to_compare_is_skipped():
    rows = [f"{i}," for i in range(30)]  # a unique id and an empty column
    n = near(rows_csv("id,empty", rows))
    assert n.status == "skipped" and "No columns" in n.reason


def test_failed_profiling_skips_the_stage(monkeypatch):
    def broken(frame):
        raise RuntimeError("boom")

    monkeypatch.setattr(profiler, "profile_columns", broken)
    result = run_analysis(load("a\nX\nx\n"))
    assert result.near_duplicates is None
    assert next(s for s in result.stages if s.name == "near_duplicates").status == "skipped"


# --- Finding ------------------------------------------------------------------------------------


def test_finding_is_a_potential_issue_with_examples():
    f = finding("name,city\nAlice Smith,Paris\nalice smith,PARIS\nBob,Rome\nCarl,Oslo\nDan,Lima\n")
    assert f.kind == "potential_issue" and f.category == "uniqueness"
    assert f.columns == ["city", "name"] or f.columns == ["name", "city"]
    assert f.evidence["first_group_row_positions"] == "0, 1"
    assert f.evidence["n_groups"] == 1 and f.evidence["n_rows_involved"] == 2
    assert "differ in" in f.explanation.lower()


def test_severity_follows_the_medium_threshold():
    small = rows_csv("name,k", ["Ann,1", "ann,1"] + [f"p{i},{i}" for i in range(2, 60)])  # 2 of 60 rows
    big = "name,k\nAnn,1\nann,1\nBo,2\n"  # 2 of 3 rows
    assert finding(small).severity == "low"
    assert finding(big).severity == "medium"
    assert findings.NEAR_DUPLICATE_MEDIUM_FRACTION == 0.05


def test_no_finding_without_groups():
    assert finding("a,b\nx,1\ny,2\n") is None


def test_detection_is_deterministic():
    text = "name,city\nb,Rome\nB,rome\na,Oslo\nA.,oslo\n"
    assert near(text) == near(text)
    assert near(text).example_groups == [[0, 1], [2, 3]]


def test_analyze_endpoint_returns_near_duplicates(client):
    body = upload(client, "/api/analyze", "name,city\nAlice,Paris\nalice,PARIS\n").json()
    assert body["near_duplicates"]["n_groups"] == 1
    assert any(f["code"] == "near_duplicate_rows" for f in body["findings"])
