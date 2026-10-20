"""Analysis of a user-selected target column. The target is never guessed from column names."""

import numpy as np
import pandas as pd

from app.models.schemas import (
    ClassCount,
    ClassDistribution,
    ColumnProfile,
    InferredType,
    LabelConflictSummary,
    TargetAnalysis,
    TargetTask,
)
from app.services import leakage
from app.services.profiler import clip, fraction, numeric_stats

INTEGER_CLASS_MAX_UNIQUE = 20  # integer-valued numeric targets with at most this many values
CLASS_LIST_LIMIT = 50
RARE_CLASS_THRESHOLD = 5  # classes below this cannot appear in every fold of 5-fold stratified CV
CONFLICT_EXAMPLES_LIMIT = 10


def infer_task(profile: ColumnProfile) -> tuple[TargetTask, str]:
    kind = profile.inferred_type
    if kind is InferredType.empty:
        return TargetTask.unsupported, "The target column has no non-missing values."
    if kind is InferredType.datetime:
        return TargetTask.unsupported, "Datetime targets are not supported."
    if kind is InferredType.boolean:
        return TargetTask.classification, "The target holds boolean values."
    if kind in (InferredType.categorical, InferredType.text):
        return TargetTask.classification, "The target holds non-numeric values."
    stats = profile.numeric
    if stats is not None and stats.all_integer and profile.n_unique <= INTEGER_CLASS_MAX_UNIQUE:
        return (
            TargetTask.classification,
            f"The target is integer-valued with {profile.n_unique} distinct values "
            f"(at most {INTEGER_CLASS_MAX_UNIQUE}). If the values are quantities rather than "
            "class codes, treat the task as regression instead.",
        )
    return (
        TargetTask.regression,
        "The target is numeric with non-integer values or more than "
        f"{INTEGER_CLASS_MAX_UNIQUE} distinct values.",
    )


def label_strings(series: pd.Series) -> pd.Series:
    """Non-missing target values as display labels; integer-valued floats lose their '.0'."""
    values = series.dropna()
    if pd.api.types.is_numeric_dtype(values) and not pd.api.types.is_bool_dtype(values):
        as_float = values.astype("float64")
        if np.isfinite(as_float).all() and (np.mod(as_float, 1) == 0).all():
            return as_float.astype("int64").astype(str)
    return values.astype(str)


def class_distribution(labels: pd.Series) -> ClassDistribution:
    counts = sorted(labels.value_counts().items(), key=lambda item: (-item[1], item[0]))
    n = len(labels)
    rare = [label for label, count in counts if count < RARE_CLASS_THRESHOLD]
    majority, minority = int(counts[0][1]), int(counts[-1][1])
    return ClassDistribution(
        n_classes=len(counts),
        classes=[
            ClassCount(label=clip(label), count=int(c), fraction=fraction(int(c), n))
            for label, c in counts[:CLASS_LIST_LIMIT]
        ],
        truncated=len(counts) > CLASS_LIST_LIMIT,
        majority_count=majority,
        minority_count=minority,
        imbalance_ratio=round(majority / minority, 6) if len(counts) >= 2 else None,
        rare_class_threshold=RARE_CLASS_THRESHOLD,
        n_rare_classes=len(rare),
        rare_classes=[clip(label) for label in rare[:CLASS_LIST_LIMIT]],
    )


def label_conflicts(frame: pd.DataFrame, target: str, labels: pd.Series) -> LabelConflictSummary | None:
    """Rows whose feature values are identical but whose labels differ."""
    features = frame.drop(columns=[target])
    if features.shape[1] == 0:
        return None
    keys = pd.Series(
        pd.util.hash_pandas_object(features, index=False).to_numpy(), index=frame.index
    )
    labeled_keys = keys.loc[labels.index]
    per_key = labels.groupby(labeled_keys.to_numpy()).nunique()
    conflicting = per_key[per_key > 1].index
    mask = keys.isin(conflicting) & frame[target].notna()
    positions = np.flatnonzero(mask.to_numpy())
    return LabelConflictSummary(
        n_conflicting_groups=int(len(conflicting)),
        n_rows_involved=int(len(positions)),
        example_row_indices=[int(i) for i in positions[:CONFLICT_EXAMPLES_LIMIT]],
    )


def analyze_target(
    frame: pd.DataFrame, target: str, profiles: list[ColumnProfile]
) -> TargetAnalysis:
    profile = next(p for p in profiles if p.name == target)
    task, reason = infer_task(profile)
    series = frame[target]
    analysis = TargetAnalysis(
        column=target,
        task=task,
        task_reason=reason,
        n_labeled=profile.n_non_null,
        n_missing_labels=profile.n_missing,
    )
    if task is TargetTask.unsupported:
        return analysis
    if task is TargetTask.regression:
        analysis.regression = numeric_stats(series)
        values = pd.to_numeric(series, errors="coerce").astype("float64")
        analysis.leakage_signals = leakage.target_leakage_signals(
            frame, profiles, target, task, values.dropna()
        )
        return analysis

    labels = label_strings(series)
    analysis.classes = class_distribution(labels)
    analysis.label_conflicts = label_conflicts(frame, target, labels)
    analysis.leakage_signals = leakage.target_leakage_signals(
        frame, profiles, target, task, labels
    )
    return analysis
