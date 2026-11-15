"""Model-impact experiments: reproducibility, the planted leakage fixture, and honest edge cases."""

from pathlib import Path

import numpy as np
import pytest

from app.config import Limits
from app.services import experiments
from app.services.loader import DatasetError, load_csv
from tests.conftest import TEST_LIMITS, load, rows_csv, upload
from tests.test_api import SECRET, assert_safe_error

SAMPLES = Path(__file__).resolve().parent.parent / "sample_data"
LIMITS = Limits(max_label_review_rows=5000)


def planted(n: int = 240, leak: bool = True, dup_every: int = 0, seed: int = 7) -> str:
    """Synthetic classification data: weak numeric signal, an optional feature that is the label in
    disguise, and optional exact duplicate rows."""
    rng = np.random.default_rng(seed)
    y = rng.integers(0, 2, n)
    x = y + rng.normal(0, 1.6, n)
    z = rng.normal(0, 1, n)
    rows = []
    for i in range(n):
        cells = [f"{x[i]:.4f}", f"{z[i]:.4f}", "pos" if y[i] else "neg"]
        if leak:
            cells.insert(2, "closed" if y[i] else "open")
        rows.append(",".join(cells))
        if dup_every and i % dup_every == 0:
            rows.append(rows[-1])
    header = "x,z,status,label" if leak else "x,z,label"
    return rows_csv(header, rows)


def run(text: str, target: str = "label", limits: Limits = LIMITS):
    return experiments.run_experiments(load(text), target, limits)


def experiment(result, code: str):
    return next(e for e in result.experiments if e.code == code)


# --- Done-when: reproducibility and the planted leakage fixture ---------------------------------


def test_results_are_bit_for_bit_reproducible():
    text = planted(dup_every=5)
    assert run(text).model_dump_json() == run(text).model_dump_json()


def test_planted_leakage_inflates_the_score_on_every_seed():
    result = run(planted())
    leak = experiment(result, "leakage")
    assert result.leaky_features == ["status"]
    assert leak.status == "computed"
    without, with_leak = leak.conditions
    assert with_leak.mean == pytest.approx(1.0)
    assert leak.differences[0].mean >= 0.2
    assert leak.differences[0].min > 0
    assert "not proof" in leak.summary


def test_every_seed_is_reported_with_mean_and_spread():
    result = run(planted())
    assert result.seeds == list(experiments.SEEDS) and result.test_fraction == experiments.TEST_FRACTION
    for e in result.experiments:
        for c in e.conditions:
            assert len(c.scores) == len(experiments.SEEDS)
            assert c.mean == pytest.approx(np.mean(c.scores), abs=1e-6)
            assert c.min == min(c.scores) and c.max == max(c.scores)
            assert c.std == pytest.approx(np.std(c.scores, ddof=1), abs=1e-6)


def test_conditions_share_the_clean_baseline_and_test_sets():
    result = run(planted(dup_every=5))
    clean = experiment(result, "leakage").conditions[0].scores
    assert experiment(result, "duplicates").conditions[0].scores == clean
    assert experiment(result, "label_noise").conditions[0].scores == clean
    for e in result.experiments:
        for d in e.differences:
            assert d.mean == pytest.approx(np.mean(d.differences), abs=1e-6)


# --- Duplicates and label noise -----------------------------------------------------------------


def test_duplicate_experiment_reports_contamination():
    dup = experiment(run(planted(dup_every=4)), "duplicates")
    assert dup.status == "computed"
    assert dup.details["n_duplicate_rows"] > 0 and dup.details["mean_test_rows_with_copy_in_train"] > 0
    kept, removed = dup.conditions
    assert dup.differences[0].differences == pytest.approx(
        [a - b for a, b in zip(kept.scores, removed.scores)], abs=1e-6)


def test_duplicate_experiment_is_not_applicable_without_duplicates():
    dup = experiment(run(planted()), "duplicates")
    assert dup.status == "not_applicable" and "no exact duplicate" in dup.reason


def test_label_noise_has_one_condition_per_rate():
    noise = experiment(run(planted()), "label_noise")
    assert [c.label for c in noise.conditions] == ["0% of training labels flipped"] + [
        f"{r:.0%} of training labels flipped" for r in experiments.NOISE_RATES]
    assert len(noise.differences) == len(experiments.NOISE_RATES)


def test_flip_labels_flips_the_exact_share_to_another_class():
    labels = np.array(["a"] * 60 + ["b"] * 30 + ["c"] * 10, dtype=object)
    classes = np.array(["a", "b", "c"], dtype=object)
    noisy = experiments.flip_labels(labels, 0.2, 3, classes)
    assert int((noisy != labels).sum()) == 20
    assert set(noisy) <= set(classes)
    assert (experiments.flip_labels(labels, 0.2, 3, classes) == noisy).all()  # seeded
    assert not (experiments.flip_labels(labels, 0.2, 4, classes) == noisy).all()
    assert (labels == np.array(["a"] * 60 + ["b"] * 30 + ["c"] * 10, dtype=object)).all()  # untouched


# --- Edge cases ---------------------------------------------------------------------------------


def test_no_leakage_signal_means_not_applicable():
    leak = experiment(run(planted(leak=False)), "leakage")
    assert leak.status == "not_applicable" and leak.conditions == []


def test_only_a_leaky_feature_uses_the_most_frequent_class_baseline():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 120)
    text = rows_csv("status,label", [f"{'closed' if v else 'open'},{'pos' if v else 'neg'}" for v in y])
    leak = experiment(run(text), "leakage")
    without, with_leak = leak.conditions
    assert without.mean == pytest.approx(0.5) and with_leak.mean == pytest.approx(1.0)


@pytest.mark.parametrize(
    ("text", "target", "reason"),
    [
        (rows_csv("x,y", [f"{i},{i * 1.37}" for i in range(80)]), "y", "classification"),
        (rows_csv("x,y", [f"{i},a" for i in range(80)]), "y", "two classes"),
        (rows_csv("x,y", [f"{i},{'a' if i < 75 else 'b'}" for i in range(80)]), "y", "two classes"),
    ],
)
def test_unsupported_targets_say_why(text, target, reason):
    result = run(text, target)
    assert result.status == "unsupported" and reason in result.reason and result.experiments == []


def test_row_limit_is_respected():
    result = run(planted(), limits=Limits(max_label_review_rows=50))
    assert result.status == "unsupported" and "limited to 50 rows" in result.reason


def test_small_classes_are_excluded_and_reported():
    text = planted() + "".join(f"{i}.0,0.0,open,rare\n" for i in range(3))
    result = run(text)
    assert result.status == "completed" and result.n_rows_excluded == 3
    assert any("fewer than" in line for line in result.limitations)


def test_unknown_target_is_an_error():
    with pytest.raises(DatasetError) as info:
        run(planted(), "nope")
    assert info.value.code == "unknown_target_column"


def test_sample_churn_dataset_shows_its_planted_leak():
    data = load_csv((SAMPLES / "customer_churn.csv").read_bytes(), TEST_LIMITS, "c.csv")
    result = experiments.run_experiments(data, "churned", LIMITS)
    assert result.leaky_features == ["cancellation_code"]
    assert experiment(result, "leakage").differences[0].mean > 0.1
    assert experiment(result, "duplicates").status == "computed"


# --- API ----------------------------------------------------------------------------------------


def test_model_impact_endpoint(client):
    body = upload(client, "/api/model-impact", planted(), target_column="label").json()
    assert body["status"] == "completed" and body["metric"] == "balanced_accuracy"
    assert {e["code"] for e in body["experiments"]} == {"leakage", "duplicates", "label_noise"}


def test_model_impact_endpoint_with_parsing_options(client):
    body = upload(client, "/api/model-impact", planted().replace(",", ";"), target_column="label",
                  delimiter="semicolon").json()
    assert body["status"] == "completed" and body["dataset"]["parsing"]["delimiter"] == "semicolon"


def test_model_impact_endpoint_errors_are_safe(client):
    assert_safe_error(upload(client, "/api/model-impact", planted()), 422, "missing_target_column")
    assert_safe_error(upload(client, "/api/model-impact", planted(), target_column=SECRET), 422, "unknown_target_column")


def test_duplicates_that_would_empty_the_training_set_are_not_applicable():
    rng = np.random.default_rng(1)
    y = rng.integers(0, 2, 120)
    text = rows_csv("status,label", [f"{'closed' if v else 'open'},{'pos' if v else 'neg'}" for v in y])
    dup = experiment(run(text), "duplicates")
    assert dup.status == "not_applicable" and "fewer than two classes" in dup.reason
