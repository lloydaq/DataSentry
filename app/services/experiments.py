"""Model-impact experiments: measure what a data problem costs a model on this dataset.

Each experiment trains the shared baseline model (``modeling``) under two or more conditions and
scores every condition on the same held-out test set within a seed, for several fixed seeds. The
result reports every per-seed score, the mean and the spread; there is no single cherry-picked run
and no significance test. Everything is seeded, so the same file gives the same numbers.

  * leakage:     with versus without the features the leakage screen flagged
  * duplicates:  with versus without training rows that have an exact copy in the test set
  * label_noise: training labels flipped at fixed rates, scored on clean test labels

These are measurements on one dataset with one simple model, not general claims.
"""

import math
import warnings

import numpy as np
import pandas as pd
from sklearn.dummy import DummyClassifier
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import balanced_accuracy_score
from sklearn.model_selection import train_test_split

from app.config import Limits
from app.models.schemas import (
    ExperimentCondition,
    ExperimentDifference,
    ExperimentResult,
    ModelImpactResult,
    TargetTask,
)
from app.services import profiler, target
from app.services.loader import DatasetError, LoadedDataset, describe
from app.services.modeling import (
    MAX_FEATURES,
    MODEL_DESCRIPTION,
    build_model,
    feature_matrix,
    select_features,
    usable_kind,
)

SEEDS = (0, 1, 2, 3, 4)
TEST_FRACTION = 0.25
NOISE_RATES = (0.05, 0.10, 0.20)
MIN_CLASS_EXAMPLES = 10  # smaller classes are excluded so every split can stratify
MAX_CLASSES = 20

LIMITATIONS = [
    "These are experiments on this dataset with one simple model (logistic regression). Other "
    "models and other data can behave differently; the numbers are measurements, not general "
    "claims.",
    f"Within a seed every condition is scored on the same {TEST_FRACTION:.0%} held-out test set; "
    f"{len(SEEDS)} fixed seeds give the spread. No significance test is applied.",
    "Balanced accuracy is the mean recall over classes, so always predicting the most frequent "
    "class scores 1 / (number of classes).",
    "Removing copies of test rows from training also makes the training set slightly smaller.",
    "Label noise flips training labels to another class uniformly at random; real label errors "
    "are rarely uniform.",
]


def _round(x: float) -> float:
    return round(float(x), 6)


def _condition(label: str, scores: list[float]) -> ExperimentCondition:
    arr = np.array(scores, dtype="float64")
    return ExperimentCondition(
        label=label,
        scores=[_round(s) for s in scores],
        mean=_round(arr.mean()),
        std=_round(arr.std(ddof=1)) if len(arr) > 1 else None,
        min=_round(arr.min()),
        max=_round(arr.max()),
    )


def _difference(label: str, a: list[float], b: list[float]) -> ExperimentDifference:
    diffs = np.array(a, dtype="float64") - np.array(b, dtype="float64")
    return ExperimentDifference(
        label=label,
        differences=[_round(d) for d in diffs],
        mean=_round(diffs.mean()),
        min=_round(diffs.min()),
        max=_round(diffs.max()),
    )


def _unsupported(dataset: LoadedDataset, target_column: str, reason: str) -> ModelImpactResult:
    return ModelImpactResult(
        status="unsupported", reason=reason, dataset=describe(dataset), target_column=target_column,
        limitations=LIMITATIONS,
    )


def run_experiments(dataset: LoadedDataset, target_column: str, limits: Limits) -> ModelImpactResult:
    frame = dataset.frame
    if target_column not in frame.columns:
        raise DatasetError(
            "unknown_target_column", "The selected target column does not exist in the dataset."
        )
    if len(frame) > limits.max_label_review_rows:
        return _unsupported(
            dataset, target_column,
            f"Experiments are limited to {limits.max_label_review_rows} rows to keep them fast; "
            f"this dataset has {len(frame)}.",
        )
    profiles = profiler.profile_columns(frame)
    task, _ = target.infer_task(next(p for p in profiles if p.name == target_column))
    if task is not TargetTask.classification:
        return _unsupported(dataset, target_column,
                            "Model-impact experiments currently support classification targets.")

    labels = target.label_strings(frame[target_column])
    counts = labels.value_counts()
    small = counts[counts < MIN_CLASS_EXAMPLES].index
    labels = labels[~labels.isin(small)]
    if labels.nunique() < 2:
        return _unsupported(dataset, target_column,
                            f"At least two classes with {MIN_CLASS_EXAMPLES} or more labeled rows are required.")
    if labels.nunique() > MAX_CLASSES:
        return _unsupported(dataset, target_column, f"At most {MAX_CLASSES} classes are supported.")

    leaky = {s.column for s in target.analyze_target(frame, target_column, profiles).leakage_signals}
    numeric, categorical, _ = select_features(profiles, target_column, leaky)
    leak_num = [p.name for p in profiles if p.name in leaky and usable_kind(p) == "numeric"]
    leak_cat = [p.name for p in profiles if p.name in leaky and usable_kind(p) == "categorical"]
    if not (numeric or categorical or leak_num or leak_cat):
        return _unsupported(dataset, target_column, "No usable feature columns remain.")
    if len(numeric) + len(categorical) + len(leak_num) + len(leak_cat) > MAX_FEATURES:
        return _unsupported(dataset, target_column, f"At most {MAX_FEATURES} features are supported.")

    rows = labels.index
    X = feature_matrix(frame, rows, numeric + leak_num, categorical + leak_cat)
    y = labels.to_numpy()
    classes = np.array(sorted(set(y)))
    positions = np.arange(len(y))
    row_ids = pd.util.hash_pandas_object(frame.loc[rows], index=False).to_numpy()
    splits = [
        train_test_split(positions, test_size=TEST_FRACTION, random_state=seed, stratify=y)
        for seed in SEEDS
    ]

    def score(num: list[str], cat: list[str], train: np.ndarray, test: np.ndarray, y_train) -> float:
        if num or cat:
            model = build_model(num, cat)
            model.fit(X.iloc[train][num + cat], y_train)
            predicted = model.predict(X.iloc[test][num + cat])
        else:  # no usable features at all: the most-frequent-class baseline
            model = DummyClassifier(strategy="most_frequent").fit(np.zeros((len(train), 1)), y_train)
            predicted = model.predict(np.zeros((len(test), 1)))
        return float(balanced_accuracy_score(y[test], predicted))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        clean = [score(numeric, categorical, tr, te, y[tr]) for tr, te in splits]
        experiments = [
            _leakage(numeric, categorical, leak_num, leak_cat, splits, clean, score, y),
            _duplicates(numeric, categorical, splits, clean, score, y, row_ids),
            _label_noise(numeric, categorical, splits, clean, score, y, classes),
        ]
    limitations = list(LIMITATIONS)
    if any(issubclass(w.category, ConvergenceWarning) for w in caught):
        limitations.append("The logistic regression did not fully converge in some fits.")
    if len(small):
        limitations.append(f"{len(small)} class(es) with fewer than {MIN_CLASS_EXAMPLES} labeled rows were excluded.")
    return ModelImpactResult(
        status="completed",
        dataset=describe(dataset),
        target_column=target_column,
        model=MODEL_DESCRIPTION,
        seeds=list(SEEDS),
        test_fraction=TEST_FRACTION,
        n_rows_used=len(y),
        n_rows_excluded=len(frame) - len(y),
        features_used=numeric + categorical,
        leaky_features=leak_num + leak_cat,
        experiments=experiments,
        limitations=limitations,
    )


def _leakage(numeric, categorical, leak_num, leak_cat, splits, clean, score, y) -> ExperimentResult:
    title = "Suspected leaky features"
    question = "How much do the features flagged by the leakage screen raise the test score?"
    if not (leak_num or leak_cat):
        return ExperimentResult(code="leakage", title=title, question=question, status="not_applicable",
                                reason="The leakage screen flagged no usable feature for this target.")
    with_leak = [score(numeric + leak_num, categorical + leak_cat, tr, te, y[tr]) for tr, te in splits]
    diff = _difference("with − without", with_leak, clean)
    names = ", ".join(f"'{c}'" for c in leak_num + leak_cat)
    return ExperimentResult(
        code="leakage", title=title, question=question, status="computed",
        conditions=[_condition("Without the flagged feature(s)", clean),
                    _condition("With the flagged feature(s)", with_leak)],
        differences=[diff],
        summary=f"With {names}, balanced accuracy averaged {np.mean(with_leak):.3f} against "
        f"{np.mean(clean):.3f} without (difference {diff.mean:+.3f}; per seed {diff.min:+.3f} to "
        f"{diff.max:+.3f}). A large gain is consistent with leakage if the feature would not be "
        "available at prediction time; it is a measurement on this dataset, not proof.",
        details={"features": names},
    )


def _duplicates(numeric, categorical, splits, clean, score, y, row_ids) -> ExperimentResult:
    title = "Copies of test rows in training"
    question = "How much do exact copies of test rows in the training set raise the test score?"
    n_dup_rows = int(pd.Series(row_ids).duplicated().sum())
    if not n_dup_rows:
        return ExperimentResult(code="duplicates", title=title, question=question, status="not_applicable",
                                reason="There are no exact duplicate rows among the rows used.")
    kept_sets, contaminated = [], []
    for tr, te in splits:
        contaminated.append(int(np.isin(row_ids[te], row_ids[tr]).sum()))
        kept_sets.append(tr[~np.isin(row_ids[tr], row_ids[te])])
    if any(len(set(y[keep])) < 2 for keep in kept_sets):
        return ExperimentResult(
            code="duplicates", title=title, question=question, status="not_applicable",
            reason="Removing the copies of test rows would leave a training set with fewer than "
            "two classes, so the comparison cannot be measured.",
            details={"n_duplicate_rows": n_dup_rows},
        )
    removed = [score(numeric, categorical, keep, te, y[keep]) for keep, (_, te) in zip(kept_sets, splits)]
    diff = _difference("kept − removed", clean, removed)
    avg = float(np.mean(contaminated))
    return ExperimentResult(
        code="duplicates", title=title, question=question, status="computed",
        conditions=[_condition("Copies of test rows kept in training", clean),
                    _condition("Copies of test rows removed from training", removed)],
        differences=[diff],
        summary=f"On average {avg:.1f} test rows had an exact copy in training. Keeping those "
        f"copies gave {np.mean(clean):.3f} balanced accuracy against {np.mean(removed):.3f} without "
        f"them (difference {diff.mean:+.3f}; per seed {diff.min:+.3f} to {diff.max:+.3f}). A "
        "positive difference means duplicates make the test score look better than it would on "
        "new rows.",
        details={"n_duplicate_rows": n_dup_rows, "mean_test_rows_with_copy_in_train": _round(avg)},
    )


def flip_labels(labels: np.ndarray, rate: float, seed: int, classes: np.ndarray) -> np.ndarray:
    """A copy of ``labels`` with round(rate * n) of them, chosen and replaced with a seeded
    generator, changed to a different class drawn uniformly from the others."""
    rng = np.random.default_rng([seed, int(round(rate * 1000))])
    noisy = labels.copy()
    flip = rng.choice(len(labels), size=int(math.floor(rate * len(labels) + 0.5)), replace=False)
    for i in flip:
        others = classes[classes != noisy[i]]
        noisy[i] = others[rng.integers(len(others))]
    return noisy


def _label_noise(numeric, categorical, splits, clean, score, y, classes) -> ExperimentResult:
    title = "Label noise"
    question = "How quickly does the test score fall as training labels are corrupted?"
    conditions = [_condition("0% of training labels flipped", clean)]
    differences = []
    for rate in NOISE_RATES:
        scores = []
        for seed, (tr, te) in zip(SEEDS, splits):
            scores.append(score(numeric, categorical, tr, te, flip_labels(y[tr], rate, seed, classes)))
        conditions.append(_condition(f"{rate:.0%} of training labels flipped", scores))
        differences.append(_difference(f"{rate:.0%} − 0%", scores, clean))
    worst = differences[-1]
    return ExperimentResult(
        code="label_noise", title=title, question=question, status="computed",
        conditions=conditions, differences=differences,
        summary=f"Flipping {NOISE_RATES[-1]:.0%} of training labels changed balanced accuracy by "
        f"{worst.mean:+.3f} on average (per seed {worst.min:+.3f} to {worst.max:+.3f}); test labels "
        "were never changed. This shows how sensitive this model is to label errors on this data.",
        details={"rates": ", ".join(f"{r:.0%}" for r in NOISE_RATES)},
    )
