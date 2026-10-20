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
from sklearn.compose import ColumnTransformer
from sklearn.exceptions import ConvergenceWarning
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, balanced_accuracy_score
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from app.config import Limits
from app.models.schemas import (
    ExcludedFeature,
    InferredType,
    LabelCandidate,
    LabelReviewResult,
    TargetTask,
)
from app.services import profiler, target
from app.services.loader import DatasetError, LoadedDataset

CV_FOLDS = 5
RANDOM_SEED = 0
MAX_CATEGORIES = 50
MAX_CLASSES = 20
MAX_FEATURES = 200
CANDIDATES_LIMIT = 50
MODEL_DESCRIPTION = (
    "LogisticRegression(max_iter=1000) on median-imputed, standardized numeric features and "
    "one-hot encoded categorical features"
)
_MISSING_CATEGORY = "__missing__"

LIMITATIONS = [
    "Model disagreement is not proof of a wrong label. Ambiguous examples, a weak model or "
    "missing features also produce disagreements.",
    "A linear model cannot capture every relationship; a low out-of-fold accuracy means the "
    "candidate list is less informative.",
    "Exact duplicate rows can fall into different folds, which makes the model agree with "
    "their labels more than it otherwise would.",
    "Labels are never changed automatically.",
]


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
    numeric: list[str] = []
    categorical: list[str] = []
    excluded: list[ExcludedFeature] = []
    for p in profiles:
        if p.name == target_column:
            continue
        reason = None
        if p.all_missing or p.is_constant:
            reason = "no variation"
        elif p.identifier_like:
            reason = "identifier-like"
        elif p.name in leaky:
            reason = "possible target leakage"
        elif p.inferred_type is InferredType.numeric:
            numeric.append(p.name)
        elif p.inferred_type in (InferredType.categorical, InferredType.boolean):
            if p.n_unique <= MAX_CATEGORIES:
                categorical.append(p.name)
            else:
                reason = f"more than {MAX_CATEGORIES} categories"
        else:
            reason = f"{p.inferred_type.value} columns are not used"
        if reason:
            excluded.append(ExcludedFeature(column=p.name, reason=reason))
    if not numeric and not categorical:
        return _unsupported(target_column, "No usable feature columns remain after exclusions.")
    if len(numeric) + len(categorical) > MAX_FEATURES:
        return _unsupported(target_column, f"Label review supports at most {MAX_FEATURES} features.")

    rows = labels.index
    X = pd.DataFrame(index=rows)
    for c in numeric:
        X[c] = pd.to_numeric(frame.loc[rows, c], errors="coerce").astype("float64").replace(
            [np.inf, -np.inf], np.nan
        )
    for c in categorical:
        col = frame.loc[rows, c]
        X[c] = col.astype(str).where(col.notna(), _MISSING_CATEGORY).astype(object)
    y = labels.to_numpy()

    transformers = []
    if numeric:
        transformers.append(
            (
                "num",
                Pipeline(
                    [("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                     ("scale", StandardScaler())]
                ),
                numeric,
            )
        )
    if categorical:
        transformers.append(("cat", OneHotEncoder(handle_unknown="ignore"), categorical))
    model = Pipeline(
        [
            ("prep", ColumnTransformer(transformers)),
            ("clf", LogisticRegression(max_iter=1000)),
        ]
    )
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
    candidates = [
        LabelCandidate(
            row_index=int(positions[i]),
            given_label=profiler.clip(str(y[i])),
            predicted_label=profiler.clip(str(predicted[i])),
            given_label_probability=round(float(given_p[i]), 4),
            predicted_label_probability=round(float(pred_p[i]), 4),
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
        limitations=limitations,
    )
