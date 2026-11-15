"""Dataset diff: schema, rows, distributions, missing values and finding changes between versions."""

from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from app.services import diff
from app.services.loader import load_csv
from tests.conftest import TEST_LIMITS, load, rows_csv, upload
from tests.test_api import SECRET, assert_safe_error

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"


def compare(old: str, new: str, target=None):
    return diff.dataset_diff(load(old, "old.csv"), load(new, "new.csv"), target)


def table(n: int, offset: int = 0, cats: str = "ab", scale: float = 1.5) -> str:
    return rows_csv("id,cat,x", [f"{i + offset},{cats[i % len(cats)]},{i * scale}" for i in range(n)])


# --- Statistics ---------------------------------------------------------------------------------


def test_ks_statistic_matches_scipy():
    rng = np.random.default_rng(0)
    for a, b in [(rng.normal(size=200), rng.normal(0.4, size=150)), (rng.integers(0, 5, 80), rng.integers(1, 6, 90))]:
        assert diff.ks_statistic(a.astype(float), b.astype(float)) == pytest.approx(stats.ks_2samp(a, b).statistic)


def test_ks_statistic_is_zero_for_identical_and_one_for_disjoint_samples():
    a = np.arange(30, dtype=float)
    assert diff.ks_statistic(a, a.copy()) == 0.0
    assert diff.ks_statistic(a, a + 100) == 1.0


def test_psi_is_zero_for_equal_shares_and_finite_for_new_categories():
    import pandas as pd

    assert diff.psi(pd.Series(list("aabb")), pd.Series(list("ab"))) == pytest.approx(0.0)
    value = diff.psi(pd.Series(list("aaaa")), pd.Series(list("bbbb")))
    assert np.isfinite(value) and value > diff.PSI_MAJOR_THRESHOLD


# --- Identity and schema ------------------------------------------------------------------------


def test_identical_files_report_no_changes():
    text = table(40)
    result = compare(text, text)
    assert result.identical and result.findings == []
    assert result.headline == "The two files are identical."
    assert result.rows.n_new_rows_not_in_old == 0 and result.rows.n_old_rows_not_in_new == 0
    assert all(not c.shifted for c in result.columns)
    assert result.finding_changes.new == [] and result.finding_changes.resolved == []


def test_same_content_with_reordered_rows_is_not_identical_but_has_no_changes():
    rows = [f"{i},{'ab'[i % 2]},{i * 1.5}" for i in range(40)]
    result = compare(rows_csv("id,cat,x", rows), rows_csv("id,cat,x", rows[::-1]))
    assert not result.identical
    assert result.findings == [] and result.headline.startswith("No schema, type, missing-value or distribution changes")


def test_added_removed_and_renamed_columns():
    old = rows_csv("id,amount,legacy", [f"{i},{i * 2},{i % 3}" for i in range(30)])
    new = rows_csv("id,amount_usd,fresh", [f"{i},{i * 2},z{i}" for i in range(30)])
    s = compare(old, new).schema_changes
    assert s.removed == ["amount", "legacy"] and s.added == ["amount_usd", "fresh"]
    assert [(r.old_name, r.new_name, r.value_overlap) for r in s.possible_renames] == [("amount", "amount_usd", 1.0)]


def test_renames_need_matching_types_and_overlapping_values():
    old = rows_csv("id,a", [f"{i},{i}" for i in range(30)])
    new = rows_csv("id,b", [f"{i},{i + 1000}" for i in range(30)])
    assert compare(old, new).schema_changes.possible_renames == []


def test_type_change_is_reported_and_not_compared():
    old = rows_csv("id,v", [f"{i},{i}" for i in range(30)])
    new = rows_csv("id,v", [f"{i},{'ERR' if i % 2 else i}" for i in range(30)])
    result = compare(old, new)
    assert [(t.column, t.old_type, t.new_type) for t in result.schema_changes.type_changes] == [("v", "numeric", "categorical")]
    v = next(c for c in result.columns if c.column == "v")
    assert v.shift_statistic is None and "type changed" in v.note
    assert any(f.code == "diff_type_changes" and f.severity == "medium" for f in result.findings)


def test_removed_columns_finding_mentions_renames():
    result = compare(rows_csv("id,a", [f"{i},{i}" for i in range(30)]), rows_csv("id,b", [f"{i},{i}" for i in range(30)]))
    finding = next(f for f in result.findings if f.code == "diff_columns_removed")
    assert finding.evidence == {"n_removed": 1, "n_possible_renames": 1}
    assert "look renamed" in finding.explanation


# --- Rows ---------------------------------------------------------------------------------------


def test_row_changes_count_kept_added_and_dropped_rows():
    rows = table(40).splitlines()[1:]
    old = rows_csv("id,cat,x", rows[:30])
    new = rows_csv("id,cat,x", rows[10:])
    r = compare(old, new).rows
    assert (r.n_old, r.n_new, r.n_columns_compared) == (30, 30, 3)
    assert (r.n_new_rows_found_in_old, r.n_new_rows_not_in_old, r.n_old_rows_not_in_new) == (20, 10, 10)


def test_rows_are_matched_on_shared_columns_only():
    old = rows_csv("id,v", [f"{i},{i}" for i in range(20)])
    new = rows_csv("id,w", [f"{i},x" for i in range(20)])
    r = compare(old, new).rows
    assert r.n_columns_compared == 1 and r.n_new_rows_found_in_old == 20


def test_no_shared_columns():
    r = compare("a\n1\n", "b\n1\n").rows
    assert r.n_columns_compared == 0 and r.n_new_rows_not_in_old == 1 and r.n_old_rows_not_in_new == 1


# --- Distributions and missing values -----------------------------------------------------------


def test_numeric_shift_uses_ks_and_reports_means():
    result = compare(table(100), table(100, scale=3.0))
    x = next(c for c in result.columns if c.column == "x")
    assert x.shift_measure == "ks" and x.shifted and x.shift_statistic >= diff.KS_SHIFT_THRESHOLD
    assert x.old_mean == pytest.approx(74.25) and x.new_mean == pytest.approx(148.5)
    finding = next(f for f in result.findings if f.code == "diff_distribution_shift")
    assert "x" in finding.columns and finding.kind == "potential_issue"


def test_categorical_shift_uses_psi_and_lists_new_and_vanished_values():
    result = compare(table(60, cats="ab"), table(60, cats="bc"))
    cat = next(c for c in result.columns if c.column == "cat")
    assert cat.shift_measure == "psi" and cat.shifted
    assert cat.new_categories == ["c"] and cat.vanished_categories == ["a"]
    assert any(f.code == "diff_new_categories" and f.severity == "info" for f in result.findings)


def test_small_columns_are_not_compared():
    result = compare(table(diff.SHIFT_MIN_VALUES - 1), table(diff.SHIFT_MIN_VALUES - 1, scale=9))
    x = next(c for c in result.columns if c.column == "x")
    assert x.shift_statistic is None and not x.shifted and "Fewer than" in x.note


def test_text_columns_are_not_compared_for_shift():
    old = rows_csv("id,t", [f"{i},unique text {i}" for i in range(60)])
    new = rows_csv("id,t", [f"{i},other words {i}" for i in range(60)])
    t = next(c for c in compare(old, new).columns if c.column == "t")
    assert t.shift_measure is None and "text" in t.note


def test_shift_severity_follows_the_major_threshold():
    rows = lambda shift: rows_csv("x", [f"{i + shift}" for i in range(200)])
    small = next(f for f in compare(rows(0), rows(30)).findings if f.code == "diff_distribution_shift")
    big = next(f for f in compare(rows(0), rows(150)).findings if f.code == "diff_distribution_shift")
    assert small.severity == "low" and big.severity == "medium"


def test_target_shift_is_called_out():
    old = rows_csv("x,y", [f"{i},{'n' if i % 4 else 'y'}" for i in range(80)])
    new = rows_csv("x,y", [f"{i},{'y' if i % 4 else 'n'}" for i in range(80)])
    finding = next(f for f in compare(old, new, target="y").findings if f.code == "diff_distribution_shift")
    assert finding.evidence["target_shifted"] is True and "including the target" in finding.explanation


def test_missing_rate_increase():
    old = rows_csv("id,v", [f"{i},{i}" for i in range(40)])
    new = rows_csv("id,v", [f"{i},{'' if i < 12 else i}" for i in range(40)])
    result = compare(old, new)
    finding = next(f for f in result.findings if f.code == "diff_missing_rate_increase")
    assert finding.severity == "medium" and finding.columns == ["v"]
    assert "1 column(s) with more missing values" in result.headline
    assert finding.evidence["max_increase"] == 0.3


def test_small_missing_increase_is_not_reported():
    old = rows_csv("id,v", [f"{i},{i}" for i in range(40)])
    new = rows_csv("id,v", [f"{i},{'' if i == 0 else i}" for i in range(40)])
    assert all(f.code != "diff_missing_rate_increase" for f in compare(old, new).findings)


# --- Finding changes ----------------------------------------------------------------------------


def test_findings_are_classified_as_new_resolved_and_persisting():
    old = rows_csv("id,const,empty", [f"{i},same," for i in range(30)])
    new = rows_csv("id,const,empty", [f"{i},same,{i}" for i in range(30)] + ["0,same,0"])
    fc = compare(old, new).finding_changes
    assert "all_missing_column" in {r.code for r in fc.resolved}
    assert "duplicate_rows" in {r.code for r in fc.new}
    assert "constant_column" in {r.code for r in fc.persisting}


def test_diff_is_deterministic():
    a, b = table(80), table(70, offset=5, cats="abc", scale=2.0)
    assert compare(a, b) == compare(a, b)


def test_unknown_target_in_either_file_is_rejected():
    from app.services.loader import DatasetError

    with pytest.raises(DatasetError) as info:
        compare("a,y\n1,2\n", "a\n1\n", target="y")
    assert info.value.code == "unknown_target_column"


def test_sample_churn_versus_holdout():
    old = load_csv((SAMPLES / "customer_churn.csv").read_bytes(), TEST_LIMITS, "old.csv")
    new = load_csv((SAMPLES / "customer_churn_holdout.csv").read_bytes(), TEST_LIMITS, "new.csv")
    result = diff.dataset_diff(old, new, "churned")
    assert result.schema_changes.added == [] and result.schema_changes.removed == []
    assert result.rows.n_new_rows_found_in_old == 20  # the 20 rows copied into the holdout
    assert result.finding_changes is not None


# --- API ----------------------------------------------------------------------------------------


def post_diff(client, old: str | bytes, new: str | bytes, **fields):
    enc = lambda t: t.encode() if isinstance(t, str) else t
    return client.post(
        "/api/dataset-diff",
        files={"old_file": ("v1.csv", enc(old)), "new_file": ("v2.csv", enc(new))},
        data=fields,
    )


def test_dataset_diff_endpoint(client):
    body = post_diff(client, table(40), table(40, scale=3.0)).json()
    assert body["old"]["filename"] == "v1.csv" and body["new"]["filename"] == "v2.csv"
    assert any(c["column"] == "x" and c["shifted"] for c in body["columns"])


def test_dataset_diff_endpoint_honours_parsing_options(client):
    body = post_diff(client, table(30).replace(",", ";"), table(30).replace(",", ";"), delimiter="semicolon").json()
    assert body["identical"] is True and body["new"]["parsing"]["delimiter"] == "semicolon"


def test_dataset_diff_endpoint_needs_both_files(client):
    response = client.post("/api/dataset-diff", files={"old_file": ("a.csv", b"a\n1\n")})
    assert_safe_error(response, 422, "missing_file")


def test_dataset_diff_endpoint_errors_are_safe(client):
    assert_safe_error(post_diff(client, "a\n1\n", "a\n1\n", target_column=SECRET), 422, "unknown_target_column")
    assert_safe_error(post_diff(client, b"", "a\n1\n"), 422, "empty_file")
