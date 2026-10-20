"""Label review, train/test overlap and approved corrections."""

import io

import numpy as np
import pandas as pd
import pytest

from app.config import Limits
from app.models.schemas import CorrectionOperation, CorrectionPlan, CorrectionStep
from app.services import corrections, label_review, leakage
from app.services.loader import DatasetError
from tests.conftest import TEST_LIMITS, load

# --- Label review ----------------------------------------------------------------------------


def noisy_classification(n: int = 300) -> tuple[pd.DataFrame, list[int]]:
    """Separable data with four labels flipped far from the decision boundary."""
    rng = np.random.default_rng(0)
    x1, x2 = rng.normal(size=n), rng.normal(size=n)
    score = x1 + 0.5 * x2
    y = np.where(score > 0, "pos", "neg")
    flips = [int(i) for i in np.flatnonzero(np.abs(score) > 1.0)[:4]]
    y[flips] = np.where(y[flips] == "pos", "neg", "pos")
    df = pd.DataFrame({"id": range(n), "x1": x1, "x2": x2, "g": rng.choice(["a", "b"], n), "y": y})
    return df, flips


def test_label_review_ranks_flipped_labels_first():
    df, flips = noisy_classification()
    result = label_review.review_labels(load(df.to_csv(index=False)), "y", TEST_LIMITS)
    assert result.status == "completed"
    assert {c.row_index for c in result.candidates[:4]} == set(flips)
    assert result.oof_accuracy > result.majority_baseline_accuracy
    assert {"column": "id", "reason": "identifier-like"} in [e.model_dump() for e in result.excluded_features]
    assert result.cv_folds == 5 and result.random_seed == 0


def test_label_review_is_deterministic():
    data = load(noisy_classification()[0].to_csv(index=False))
    a = label_review.review_labels(data, "y", TEST_LIMITS).model_dump_json()
    b = label_review.review_labels(data, "y", TEST_LIMITS).model_dump_json()
    assert a == b


def test_label_review_excludes_leaky_features():
    df, _ = noisy_classification()
    df["leak"] = np.where(df["y"] == "pos", "P", "N")
    result = label_review.review_labels(load(df.to_csv(index=False)), "y", TEST_LIMITS)
    assert any(e.column == "leak" and "leakage" in e.reason for e in result.excluded_features)
    assert "leak" not in result.features_used


@pytest.mark.parametrize(
    "df, reason",
    [
        (pd.DataFrame({"x": np.linspace(0, 1, 50), "y": np.linspace(0, 1, 50)}), "classification"),
        (pd.DataFrame({"x": range(50), "y": ["a"] * 47 + ["b"] * 3}), "two classes"),
        (pd.DataFrame({"t": [f"note {i}" for i in range(60)], "y": ["a", "b"] * 30}), "No usable feature"),
    ],
)
def test_label_review_reports_unsupported_cases(df, reason):
    result = label_review.review_labels(load(df.to_csv(index=False)), "y", TEST_LIMITS)
    assert result.status == "unsupported" and reason in result.reason


def test_label_review_respects_row_limit():
    data = load(noisy_classification()[0].to_csv(index=False))
    result = label_review.review_labels(data, "y", Limits(max_label_review_rows=100))
    assert result.status == "unsupported" and "limited" in result.reason


# --- Train/test overlap ----------------------------------------------------------------------


def test_train_test_overlap_counts_exact_and_label_conflicts():
    train = load("a,b,y\n1,x,p\n2,y,q\n3,z,p\n")
    test = load("a,b,y\n1,x,p\n2,y,p\n9,w,q\n")
    result = leakage.train_test_overlap(train, test, "y")
    assert result.n_test_rows_in_train == 1
    assert result.example_test_row_indices == [0]
    assert result.n_test_feature_matches == 2
    assert result.n_feature_matches_with_different_label == 1
    assert {f.code for f in result.findings} == {"train_test_row_overlap", "train_test_label_conflict"}


def test_train_test_overlap_aligns_int_and_float_and_reports_schema_differences():
    train = load("a,b,extra\n1,x,0\n2,y,0\n")
    test = load("a,b\n1.0,x\n5,y\n")
    result = leakage.train_test_overlap(train, test, None)
    assert result.n_test_rows_in_train == 1
    assert result.train_only_columns == ["extra"]
    assert result.n_test_feature_matches is None
    assert "train_test_schema_mismatch" in {f.code for f in result.findings}


def test_train_test_overlap_errors():
    with pytest.raises(DatasetError) as info:
        leakage.train_test_overlap(load("a\n1\n"), load("b\n1\n"), None)
    assert info.value.code == "no_common_columns"
    with pytest.raises(DatasetError) as info:
        leakage.train_test_overlap(load("a,y\n1,2\n"), load("a\n1\n"), "y")
    assert info.value.code == "unknown_target_column"


# --- Corrections -----------------------------------------------------------------------------

RAW = "id,const,y,note\n1,k,a,007\n1,k,a,007\n2,k,,x\n3,k,b,  spaced  \n"


def plan(*steps, approved=True, target="y") -> CorrectionPlan:
    return CorrectionPlan(approved=approved, target_column=target, steps=list(steps))


def apply(p: CorrectionPlan, raw: str = RAW):
    return corrections.apply_corrections(raw.encode(), load(raw), p)


def test_corrections_require_approval():
    with pytest.raises(DatasetError) as info:
        apply(plan(CorrectionStep(operation=CorrectionOperation.drop_duplicate_rows), approved=False))
    assert info.value.code == "approval_required"


def test_corrections_apply_in_fixed_order_and_preserve_original_text():
    result = apply(
        plan(
            CorrectionStep(operation=CorrectionOperation.drop_columns, columns=["const"]),
            CorrectionStep(operation=CorrectionOperation.drop_duplicate_rows),
            CorrectionStep(operation=CorrectionOperation.drop_rows_missing_target),
        )
    )
    out = pd.read_csv(io.StringIO(result.csv), dtype=str, keep_default_na=False)
    assert list(out.columns) == ["id", "y", "note"]
    assert out["id"].tolist() == ["1", "3"]
    assert out["note"].tolist() == ["007", "  spaced  "]  # not re-parsed as numbers or trimmed
    steps = [(s.operation.value, s.rows_before, s.rows_after) for s in result.audit.steps]
    assert steps == [
        ("drop_rows_missing_target", 4, 3),
        ("drop_duplicate_rows", 3, 2),
        ("drop_columns", 2, 2),
    ]
    a = result.audit
    assert a.original_modified is False and a.approved_by_user
    assert (a.input.n_rows, a.output.n_rows, a.output.n_columns) == (4, 2, 3)
    assert result.filename == "data.corrected.csv"


@pytest.mark.parametrize(
    "steps, code",
    [
        ([CorrectionStep(operation=CorrectionOperation.drop_columns, columns=["nope"])], "invalid_plan"),
        ([CorrectionStep(operation=CorrectionOperation.drop_columns, columns=["y"])], "invalid_plan"),
        (
            [
                CorrectionStep(operation=CorrectionOperation.drop_duplicate_rows),
                CorrectionStep(operation=CorrectionOperation.drop_duplicate_rows),
            ],
            "invalid_plan",
        ),
    ],
)
def test_invalid_correction_plans(steps, code):
    with pytest.raises(DatasetError) as info:
        apply(plan(*steps, target="y"))
    assert info.value.code == code


def test_drop_rows_missing_target_needs_valid_target():
    with pytest.raises(DatasetError) as info:
        apply(plan(CorrectionStep(operation=CorrectionOperation.drop_rows_missing_target), target=None))
    assert info.value.code == "unknown_target_column"


def test_corrections_cannot_produce_an_empty_dataset():
    raw = "a,y\n1,\n2,\n"
    with pytest.raises(DatasetError) as info:
        apply(plan(CorrectionStep(operation=CorrectionOperation.drop_rows_missing_target)), raw)
    assert info.value.code == "invalid_plan"


def test_proposed_corrections_never_drop_the_target():
    from app.services.analysis import run_analysis

    result = run_analysis(load("x,y,k\n1,a,c\n2,a,c\n3,a,c\n"), "y")  # y and k are constant
    drop = next(c for c in result.corrections if c.id == "drop_columns")
    assert drop.columns == ["k"]
