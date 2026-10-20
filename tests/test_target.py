import numpy as np
import pandas as pd
import pytest

from app.models.schemas import TargetTask
from app.services import profiler, target
from tests.conftest import load


def analyze(df: pd.DataFrame, column: str):
    return target.analyze_target(df, column, profiler.profile_columns(df))


def csv_frame(text: str) -> pd.DataFrame:
    return load(text).frame


@pytest.mark.parametrize(
    "values, task",
    [
        (["yes", "no", "yes"], TargetTask.classification),
        (["True", "False", "True"], TargetTask.classification),
        (["0", "1", "2", "1"], TargetTask.classification),
        (["0.5", "1.25", "2.0"], TargetTask.regression),
        ([str(i) for i in range(40)], TargetTask.regression),
        (["2024-01-01", "2024-01-02"], TargetTask.unsupported),
        (["", ""], TargetTask.unsupported),
    ],
)
def test_task_inference(values, task):
    df = pd.DataFrame({"f": range(len(values))}).assign(t=values)
    df = csv_frame(df.to_csv(index=False))
    assert analyze(df, "t").task is task


def test_class_distribution():
    df = csv_frame("f,y\n" + "".join(f"{i},a\n" for i in range(8)) + "8,b\n9,b\n10,c\n11,\n")
    t = analyze(df, "y")
    c = t.classes
    assert (t.n_labeled, t.n_missing_labels) == (11, 1)
    assert [(k.label, k.count) for k in c.classes] == [("a", 8), ("b", 2), ("c", 1)]
    assert (c.majority_count, c.minority_count, c.imbalance_ratio) == (8, 1, 8.0)
    assert c.n_rare_classes == 2 and c.rare_classes == ["b", "c"]


def test_integer_labels_with_missing_values_drop_float_suffix():
    df = csv_frame("f,y\n1,0\n2,1\n3,\n4,1\n")
    assert [k.label for k in analyze(df, "y").classes.classes] == ["1", "0"]


def test_single_class_target_has_no_ratio():
    df = csv_frame("f,y\n1,a\n2,a\n")
    c = analyze(df, "y").classes
    assert c.n_classes == 1 and c.imbalance_ratio is None


def test_high_cardinality_target_is_bounded():
    df = pd.DataFrame({"f": range(300), "y": [f"label{i}" for i in range(300)]})
    c = analyze(df, "y").classes
    assert c.n_classes == 300 and c.truncated and len(c.classes) == target.CLASS_LIST_LIMIT


def test_label_conflicts():
    df = csv_frame("a,b,y\n1,x,p\n1,x,q\n1,x,p\n2,y,p\n2,y,p\n3,z,\n3,z,q\n")
    lc = analyze(df, "y").label_conflicts
    assert lc.n_conflicting_groups == 1
    assert lc.n_rows_involved == 3
    assert lc.example_row_indices == [0, 1, 2]


def test_regression_target_has_numeric_summary_and_no_classes():
    df = pd.DataFrame({"f": range(30), "y": np.linspace(0, 1, 30)})
    t = analyze(df, "y")
    assert t.classes is None and t.regression.n_finite == 30


def test_leakage_signal_for_feature_encoding_the_target():
    rng = np.random.default_rng(0)
    y = rng.choice(["churn", "stay"], 100)
    df = pd.DataFrame({"noise": rng.normal(size=100), "code": np.where(y == "churn", "C", "N"), "y": y})
    signals = analyze(df, "y").leakage_signals
    assert [(s.column, s.method, s.statistic) for s in signals] == [("code", "category_mapping", 1.0)]


def test_leakage_mapping_tolerates_label_noise_but_not_weak_features():
    rng = np.random.default_rng(1)
    y = rng.choice(["a", "b"], 200)
    leaky = np.where(y == "a", "L1", "L2")
    leaky[:5] = np.where(leaky[:5] == "L1", "L2", "L1")  # 5 noisy rows
    weak = np.where(rng.random(200) < 0.7, leaky, rng.choice(["L1", "L2"], 200))
    df = pd.DataFrame({"leaky": leaky, "weak": weak, "y": y})
    assert [s.column for s in analyze(df, "y").leakage_signals] == ["leaky"]


def test_identifier_column_does_not_trigger_mapping_signal():
    df = pd.DataFrame({"id": [f"u{i}" for i in range(60)], "y": ["a", "b"] * 30})
    assert analyze(df, "y").leakage_signals == []


def test_numeric_feature_auc_signal_for_binary_target():
    rng = np.random.default_rng(2)
    x = rng.normal(size=80)
    df = pd.DataFrame({"x": x, "other": rng.normal(size=80), "y": np.where(x > 0, "pos", "neg")})
    signals = analyze(df, "y").leakage_signals
    assert [(s.column, s.method) for s in signals] == [("x", "single_feature_auc")]
    assert signals[0].statistic == 1.0


def test_regression_correlation_signal():
    rng = np.random.default_rng(3)
    y = rng.normal(size=60)
    df = pd.DataFrame({"copy": y * 3 + 0.001 * rng.normal(size=60), "other": rng.normal(size=60), "y": y})
    signals = analyze(df, "y").leakage_signals
    assert [(s.column, s.method) for s in signals] == [("copy", "pearson_correlation")]


def test_no_leakage_screen_on_small_datasets():
    df = pd.DataFrame({"code": ["a", "b"] * 5, "y": ["p", "q"] * 5})
    assert analyze(df, "y").leakage_signals == []
