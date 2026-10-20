import json

import numpy as np
import pandas as pd

from app.models.schemas import FindingKind, Severity
from app.services.analysis import run_analysis
from app.services.loader import LoadedDataset
from tests.conftest import load


def dataset(df: pd.DataFrame) -> LoadedDataset:
    return load(df.to_csv(index=False))


def codes(result) -> dict[str, list]:
    out: dict[str, list] = {}
    for f in result.findings:
        out.setdefault(f.code, []).append(f)
    return out


def test_clean_dataset_has_no_problems():
    rng = np.random.default_rng(0)
    df = pd.DataFrame({"x": rng.normal(size=50), "c": rng.choice(["a", "b", "c"], 50)})
    result = run_analysis(dataset(df))
    assert result.status == "complete"
    assert not [f for f in result.findings if f.kind in (FindingKind.likely_issue, FindingKind.potential_issue)]
    assert result.summary.status == "no_issues_detected"
    assert any("no target" in n.lower() for n in result.summary.not_evaluated)


def test_column_findings_and_severities():
    df = pd.DataFrame(
        {
            "empty": [np.nan] * 40,
            "const": ["k"] * 40,
            "half": [1.0, np.nan] * 20,
            "few": [np.nan] + list(range(39)),
            "mixed": [str(i) for i in range(38)] + ["?", "n/a?"],
            "inf": [float(i) for i in range(39)] + [np.inf],
        }
    )
    found = codes(run_analysis(dataset(df)))
    assert found["all_missing_column"][0].columns == ["empty"]
    assert found["all_missing_column"][0].severity is Severity.medium
    assert found["constant_column"][0].columns == ["const"]
    missing = {f.columns[0]: f for f in found["missing_values"]}
    assert missing["half"].severity is Severity.medium
    assert found["minor_missing_values"][0].columns == ["few"]
    assert found["mixed_numeric_text"][0].evidence["n_non_numeric"] == 2
    assert found["infinite_values"][0].columns == ["inf"]


def test_every_finding_explains_itself():
    df = pd.DataFrame({"a": [1, 1, 2, np.nan] * 10, "b": ["x", "x ", "X", "y"] * 10})
    for f in run_analysis(dataset(df)).findings:
        assert f.title and f.explanation and f.why_it_matters and f.recommendation
        assert isinstance(f.evidence, dict)


def test_imbalance_is_an_observation_not_a_problem():
    df = pd.DataFrame({"x": range(200), "y": ["a"] * 190 + ["b"] * 10})
    result = run_analysis(dataset(df), "y")
    imbalance = codes(result)["class_imbalance"][0]
    assert imbalance.kind is FindingKind.observation and imbalance.severity is Severity.info
    target_status = next(c for c in result.summary.categories if c.category.value == "target")
    assert target_status.status == "pass"


def test_outliers_are_observations():
    df = pd.DataFrame({"x": list(range(30)) + [10_000]})
    outlier = codes(run_analysis(dataset(df)))["outlier_candidates"][0]
    assert outlier.kind is FindingKind.observation


def test_target_findings_and_corrections():
    df = pd.DataFrame({"x": [1, 2, 3, 4, 5, 5], "y": ["a", "a", "a", "b", None, None]})
    df = pd.concat([df, df.iloc[[0]]], ignore_index=True)
    result = run_analysis(dataset(df), "y")
    found = codes(result)
    assert "missing_target_labels" in found and "rare_classes" in found
    assert "missing_values" not in found and "minor_missing_values" not in found  # not double-reported
    assert {c.id for c in result.corrections} == {"drop_rows_missing_target", "drop_duplicate_rows"}


def test_single_class_target_is_high_severity():
    df = pd.DataFrame({"x": range(10), "y": ["a"] * 10})
    result = run_analysis(dataset(df), "y")
    f = codes(result)["single_class_target"][0]
    assert f.severity is Severity.high and f.kind is FindingKind.likely_issue
    assert result.summary.status == "issues_detected"


def test_unknown_target_is_rejected():
    import pytest

    from app.services.loader import DatasetError

    with pytest.raises(DatasetError) as info:
        run_analysis(dataset(pd.DataFrame({"x": [1]})), "missing")
    assert info.value.code == "unknown_target_column"


def test_findings_are_sorted_by_severity():
    df = pd.DataFrame({"x": range(30), "empty": [np.nan] * 30, "y": ["a"] * 30})
    order = [f.severity for f in run_analysis(dataset(df), "y").findings]
    rank = list(Severity)
    assert order == sorted(order, key=rank.index)


def test_failed_stage_marks_result_partial(monkeypatch):
    from app.services import profiler

    def boom(*_args):
        raise ValueError("cell value SECRET-42 caused this")

    monkeypatch.setattr(profiler, "duplicate_rows", boom)
    result = run_analysis(dataset(pd.DataFrame({"x": [1, 2, 3]})))
    assert result.status == "partial"
    assert result.duplicates is None
    assert {s.name: s.status for s in result.stages}["duplicates"] == "failed"
    uniqueness = next(c for c in result.summary.categories if c.category.value == "uniqueness")
    assert uniqueness.status == "not_evaluated"
    assert "SECRET-42" not in result.model_dump_json()


def test_analysis_is_deterministic_and_strict_json():
    rng = np.random.default_rng(5)
    df = pd.DataFrame(
        {
            "x": np.append(rng.normal(size=99), np.inf),
            "c": rng.choice(["a", "b", "B "], 100),
            "y": rng.choice(["p", "q"], 100),
        }
    )
    a = run_analysis(dataset(df), "y").model_dump_json()
    b = run_analysis(dataset(df), "y").model_dump_json()
    assert a == b
    json.loads(a, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))  # no NaN/Infinity
