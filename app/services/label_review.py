"""Opt-in label review using out-of-fold predictions.

A simple, deterministic model (one-hot + scaled logistic regression) is trained with 5-fold
stratified cross-validation. Every row is scored by a model that never saw it, and rows where the
model confidently prefers another label are listed for manual review. Preprocessing lives inside
the pipeline, so imputation and scaling are fitted on training folds only.

Model disagreement is not proof of a wrong label: the model may simply be too weak, or the
example may be genuinely ambiguous.
"""

import warnings

import numpy as np
import pandas as pd
from sklearn.exceptions import ConvergenceWarning
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict

from app.config import Limits
from app.models.schemas import CleanlabSummary, LabelCandidate, LabelReviewResult, TargetTask
from app.services import profiler, target
from app.services.loader import DatasetError, LoadedDataset
from app.services.modeling import (
    MAX_FEATURES,
    MODEL_DESCRIPTION,
    build_model,
    feature_matrix,
    select_features,
)

CV_FOLDS = 5
RANDOM_SEED = 0
MAX_CLASSES = 20
CANDIDATES_LIMIT = 50
CLEANLAB_METHOD = "find_label_issues(filter_by='prune_by_noise_rate'), ranked by self-confidence"
CLEANLAB_INSTALL_HINT = (
    "Cleanlab is an optional extra. Install it with "
    "python -m pip install -r requirements-optional.txt to add confident-learning label checks."
)

LIMITATIONS = [
    "Model disagreement is not proof of a wrong label. Ambiguous examples, a weak model or "
    "missing features also produce disagreements.",
    "A linear model cannot capture every relationship; a low out-of-fold accuracy means the "
    "candidate list is less informative.",
    "Exact duplicate rows can fall into different folds, which makes the model agree with "
    "their labels more than it otherwise would.",
    "Labels are never changed automatically.",
]


def _cleanlab(given_idx: np.ndarray, proba: np.ndarray, positions: np.ndarray) -> tuple[CleanlabSummary, set[int]]:
    """Confident learning on the out-of-fold probabilities, when the optional extra is installed.
    Returns the summary and the flagged positions within the reviewed rows."""
    try:
        import cleanlab
        from cleanlab.filter import find_label_issues
    except ImportError:
        return CleanlabSummary(status="unavailable", reason=CLEANLAB_INSTALL_HINT), set()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            mask = find_label_issues(
                labels=given_idx, pred_probs=proba, filter_by="prune_by_noise_rate", n_jobs=1
            )
    except Exception as exc:  # a library failure must never break label review
        return CleanlabSummary(
            status="failed", reason=f"Cleanlab could not run on this data ({type(exc).__name__})."
        ), set()
    flagged = np.flatnonzero(mask)
    self_conf = proba[np.arange(len(given_idx)), given_idx]
    ranked = sorted(flagged.tolist(), key=lambda i: (self_conf[i], i))
    return CleanlabSummary(
        status="computed",
        version=str(cleanlab.__version__),
        method=CLEANLAB_METHOD,
        n_issues=len(ranked),
        issue_row_indices=[int(positions[i]) for i in ranked[:CANDIDATES_LIMIT]],
    ), set(ranked)


def _unsupported(column: str, reason: str) -> LabelReviewResult:
    return LabelReviewResult(
        status="unsupported", reason=reason, target_column=column, limitations=LIMITATIONS
    )


def review_labels(dataset: LoadedDataset, target_column: str, limits: Limits) -> LabelReviewResult:
    frame = dataset.frame
    if target_column not in frame.columns:
        raise DatasetError(
            "unknown_target_column", "The selected target column does not exist in the dataset."
        )
    if len(frame) > limits.max_label_review_rows:
        return _unsupported(
            target_column,
            f"Label review is limited to {limits.max_label_review_rows} rows to keep it fast; "
            f"this dataset has {len(frame)}.",
        )
    profiles = profiler.profile_columns(frame)
    target_profile = next(p for p in profiles if p.name == target_column)
    task, _ = target.infer_task(target_profile)
    if task is not TargetTask.classification:
        return _unsupported(target_column, "Label review requires a classification-like target.")

    labels = target.label_strings(frame[target_column])
    counts = labels.value_counts()
    too_small = counts[counts < CV_FOLDS].index
    labels = labels[~labels.isin(too_small)]
    if labels.nunique() < 2:
        return _unsupported(
            target_column,
            f"At least two classes with {CV_FOLDS} or more labeled examples are required.",
        )
    if labels.nunique() > MAX_CLASSES:
        return _unsupported(
            target_column, f"Label review supports at most {MAX_CLASSES} classes."
        )

    signals = target.analyze_target(frame, target_column, profiles).leakage_signals
    leaky = {s.column for s in signals}
    numeric, categorical, excluded = select_features(profiles, target_column, leaky)
    if not numeric and not categorical:
        return _unsupported(target_column, "No usable feature columns remain after exclusions.")
    if len(numeric) + len(categorical) > MAX_FEATURES:
        return _unsupported(target_column, f"Label review supports at most {MAX_FEATURES} features.")

    rows = labels.index
    X = feature_matrix(frame, rows, numeric, categorical)
    y = labels.to_numpy()
    model = build_model(numeric, categorical)
    cv = StratifiedKFold(n_splits=CV_FOLDS, shuffle=True, random_state=RANDOM_SEED)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", ConvergenceWarning)
        proba = cross_val_predict(model, X, y, cv=cv, method="predict_proba")
    converged = not any(issubclass(w.category, ConvergenceWarning) for w in caught)

    classes = np.array(sorted(set(y)))
    given_idx = np.searchsorted(classes, y)
    predicted_idx = proba.argmax(axis=1)
    predicted = classes[predicted_idx]
    given_p = proba[np.arange(len(y)), given_idx]
    pred_p = proba[np.arange(len(y)), predicted_idx]

    disagree = np.flatnonzero(predicted_idx != given_idx)
    order = sorted(disagree, key=lambda i: (given_p[i], i))
    positions = frame.index.get_indexer(rows)
    clean_summary, flagged = _cleanlab(given_idx, proba, positions)
    available = clean_summary.status == "computed"
    clean_summary.n_issues_among_candidates = len(flagged.intersection(order[:CANDIDATES_LIMIT]))
    candidates = [
        LabelCandidate(
            row_index=int(positions[i]),
            given_label=profiler.clip(str(y[i])),
            predicted_label=profiler.clip(str(predicted[i])),
            given_label_probability=round(float(given_p[i]), 4),
            predicted_label_probability=round(float(pred_p[i]), 4),
            cleanlab_flagged=(i in flagged) if available else None,
        )
        for i in order[:CANDIDATES_LIMIT]
    ]
    majority = pd.Series(y).value_counts().iloc[0] / len(y)
    limitations = list(LIMITATIONS)
    if not converged:
        limitations.append("The logistic regression did not fully converge in some folds.")
    if len(too_small):
        limitations.append(
            f"{len(too_small)} class(es) with fewer than {CV_FOLDS} examples were excluded."
        )
    return LabelReviewResult(
        status="completed",
        target_column=target_column,
        model=MODEL_DESCRIPTION,
        cv_folds=CV_FOLDS,
        random_seed=RANDOM_SEED,
        n_rows_used=len(y),
        n_rows_excluded=len(frame) - len(y),
        features_used=numeric + categorical,
        excluded_features=excluded,
        oof_accuracy=round(float(accuracy_score(y, predicted)), 6),
        oof_balanced_accuracy=round(float(balanced_accuracy_score(y, predicted)), 6),
        majority_baseline_accuracy=round(float(majority), 6),
        n_disagreements=int(len(disagree)),
        candidates=candidates,
        candidates_truncated=len(disagree) > CANDIDATES_LIMIT,
        cleanlab=clean_summary,
        limitations=limitations,
    )
