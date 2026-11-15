"""Split Doctor: evidence for choosing a train/test split for one dataset.

A random split assumes rows are independent and that the model will see data like the past. Two
common violations inflate validation scores: the same entity (customer, patient, device) on both
sides of the split, and evaluation rows that are older than training rows when the model will be
used on later data. These checks report the evidence; they cannot know how a model will be used,
so every result is advice, never proof. The matching checks between two files live in ``leakage``.
"""

import math

import numpy as np
import pandas as pd

from app.models.schemas import EntityProfile, SplitAdvice, SplitStrategy, TargetTask, TimeProfile
from app.services.loader import DatasetError, LoadedDataset, describe
from app.services.profiler import (
    TIME_MIN_PARSED_FRACTION,
    display_time,
    finite,
    fraction,
    label_strings,
    parse_iso_times,
    profile_column,
)
from app.services.target import class_distribution, infer_task

HOLDOUT_FRACTION = 0.2  # size of the holdout used in estimates and the time-ordered comparison
GROUP_MIN_REPEATED_FRACTION = 0.05  # rows in repeated entities needed to recommend grouping
GROUP_MIN_ENTITIES = 10  # fewer entities make a group holdout too coarse to be useful
TIME_MIN_ROWS = 10
TIME_SHIFT_MIN_ROWS = 20  # each side of the time-ordered comparison needs this many labeled rows
TVD_SHIFT_THRESHOLD = 0.1  # class-distribution change worth mentioning (total variation distance)
SMD_SHIFT_THRESHOLD = 0.2  # regression target change worth mentioning (standardized mean diff.)

HEADLINES = {
    SplitStrategy.time: "Split by time: train on earlier rows, evaluate on the latest ones.",
    SplitStrategy.stratified_group: "Split by entity, keeping class proportions similar "
    "(stratified group split).",
    SplitStrategy.group: "Split by entity: keep all rows of an entity on the same side.",
    SplitStrategy.stratified: "A stratified random split keeps class proportions in both sets.",
    SplitStrategy.random: "A plain random split fits the evidence available.",
}

LIMITATIONS = [
    "This is advice from the columns you selected. DataSentry cannot know how the model will be "
    "used: split by time when it will predict later periods, and by entity when it must work for "
    "entities it has never seen.",
    f"The expected share of test rows with a seen entity assumes each row joins a "
    f"{HOLDOUT_FRACTION:.0%} holdout independently at random; real splitters differ slightly.",
    "Dates are read as ISO 8601 only; timestamps without a timezone are treated as UTC.",
    "Entity values are compared exactly (integer-valued numbers ignore a trailing '.0').",
]


def _require_column(frame: pd.DataFrame, column: str, role: str) -> None:
    if column not in frame.columns:
        raise DatasetError(f"unknown_{role}_column", f"The selected {role} column does not exist.")


def _entity_profile(series: pd.Series) -> EntityProfile:
    values = label_strings(series)
    counts = values.value_counts()
    n_with_entity = int(counts.sum())
    repeated = counts[counts > 1]
    # Under an independent holdout of share h, a test row whose entity has k rows has at least one
    # sibling in training with probability 1 - h^(k-1).
    seen = float((counts * (1 - HOLDOUT_FRACTION ** (counts - 1))).sum())
    return EntityProfile(
        column=str(series.name),
        n_entities=len(counts),
        n_rows_missing_entity=int(series.isna().sum()),
        max_rows_per_entity=int(counts.max()) if len(counts) else 0,
        n_entities_with_repeats=len(repeated),
        rows_in_repeated_entities_fraction=fraction(int(repeated.sum()), n_with_entity),
        expected_test_rows_with_seen_entity_fraction=finite(seen / n_with_entity)
        if n_with_entity
        else 0.0,
    )


def _target_shift(
    times: pd.Series, target: pd.Series, task: TargetTask
) -> tuple[float | None, str | None]:
    """Compare the target in the latest holdout share of labeled rows with the earlier rows."""
    labeled = pd.DataFrame({"t": times, "y": target}).dropna()
    labeled = labeled.sort_values("t", kind="stable")
    n_late = math.ceil(len(labeled) * HOLDOUT_FRACTION)
    if n_late < TIME_SHIFT_MIN_ROWS or len(labeled) - n_late < TIME_SHIFT_MIN_ROWS:
        return None, None
    early, late = labeled.iloc[:-n_late]["y"], labeled.iloc[-n_late:]["y"]
    if task is TargetTask.classification:
        p_early = label_strings(early).value_counts(normalize=True)
        p_late = label_strings(late).value_counts(normalize=True)
        both = p_early.index.union(p_late.index)
        tvd = 0.5 * float(
            (p_early.reindex(both, fill_value=0) - p_late.reindex(both, fill_value=0)).abs().sum()
        )
        return finite(tvd), "total_variation_distance"
    e = pd.to_numeric(early, errors="coerce").astype("float64")
    l_ = pd.to_numeric(late, errors="coerce").astype("float64")
    e, l_ = e[np.isfinite(e)], l_[np.isfinite(l_)]
    if len(e) < 2 or len(l_) < 2:
        return None, None
    pooled = math.sqrt((e.var(ddof=1) + l_.var(ddof=1)) / 2)
    if not pooled:
        return None, None
    return finite(abs(l_.mean() - e.mean()) / pooled), "standardized_mean_difference"


def _time_profile(series: pd.Series, target: pd.Series | None, task: TargetTask | None) -> TimeProfile:
    raw = parse_iso_times(series)
    n_missing, n_unparseable = int(series.isna().sum()), int(raw.isna().sum())
    parsed = raw.reindex(series.index)  # aligned with the target; NaT where missing or unparsed
    valid = raw.dropna()
    n_parsed, n_distinct = len(valid), int(valid.nunique())
    usable = (
        n_parsed >= TIME_MIN_ROWS
        and n_distinct >= 2
        and n_parsed / (n_parsed + n_unparseable) >= TIME_MIN_PARSED_FRACTION
    )
    cutoff = shift = measure = None
    if usable:
        ordered = valid.sort_values(kind="stable")
        cutoff = ordered.iloc[-math.ceil(n_parsed * HOLDOUT_FRACTION)].isoformat()
        if target is not None and task in (TargetTask.classification, TargetTask.regression):
            shift, measure = _target_shift(parsed, target, task)
    return TimeProfile(
        column=str(series.name),
        usable=usable,
        n_parsed=n_parsed,
        n_missing=n_missing,
        n_unparseable=n_unparseable,
        n_distinct=n_distinct,
        min=valid.min().isoformat() if n_parsed else None,
        max=valid.max().isoformat() if n_parsed else None,
        rows_in_time_order=bool(valid.is_monotonic_increasing) if n_parsed else None,
        holdout_cutoff=cutoff,
        target_shift=shift,
        target_shift_measure=measure,
    )


def split_advice(
    dataset: LoadedDataset,
    target_column: str | None,
    entity_column: str | None,
    time_column: str | None,
) -> SplitAdvice:
    frame = dataset.frame
    roles = {"target": target_column, "entity": entity_column, "time": time_column}
    for role, column in roles.items():
        if column is not None:
            _require_column(frame, column, role)
    chosen = [c for c in roles.values() if c is not None]
    if len(set(chosen)) != len(chosen):
        raise DatasetError(
            "invalid_request", "The target, entity and time columns must be different columns."
        )

    reasons: list[str] = []
    task: TargetTask | None = None
    target: pd.Series | None = None
    if target_column is not None:
        target = frame[target_column]
        profile = profile_column(target, frame.columns.get_loc(target_column))
        task, _ = infer_task(profile)
        if task is TargetTask.unsupported:
            reasons.append("The target column cannot be used for a supervised task, so class "
                           "balance was not considered.")

    entity = _entity_profile(frame[entity_column]) if entity_column is not None else None
    time = _time_profile(frame[time_column], target, task) if time_column is not None else None

    needs_groups = entity is not None and (
        entity.rows_in_repeated_entities_fraction >= GROUP_MIN_REPEATED_FRACTION
    )
    can_group = needs_groups and entity.n_entities >= GROUP_MIN_ENTITIES
    stratify = False
    if task is TargetTask.classification:
        labels = label_strings(target)
        dist = class_distribution(labels)
        if dist.n_classes < 2:
            reasons.append("The target has a single class, so no split can evaluate a classifier.")
        elif dist.minority_count < 2:
            reasons.append("A class has a single labeled example, so stratified splitting is not "
                           "possible until it has at least two.")
        else:
            stratify = True
            reasons.append(
                f"The target is a classification label with {dist.n_classes} classes (the "
                f"smallest is {dist.minority_count / len(labels):.1%} of labeled rows); "
                "stratifying keeps their proportions in both sets."
            )

    if time is not None:
        if time.usable:
            reasons.append(
                f"'{time.column}' parses as dates for {time.n_parsed} rows, from "
                f"{display_time(time.min)} to {display_time(time.max)}. If the model will predict "
                f"later periods, evaluate on the latest {HOLDOUT_FRACTION:.0%} (from "
                f"{display_time(time.holdout_cutoff)}); a random split would let "
                "it train on rows newer than the ones it is tested on."
            )
            if time.target_shift is not None:
                limit = TVD_SHIFT_THRESHOLD if time.target_shift_measure == "total_variation_distance" \
                    else SMD_SHIFT_THRESHOLD
                label = time.target_shift_measure.replace("_", " ")
                if time.target_shift >= limit:
                    reasons.append(
                        f"The target in the latest {HOLDOUT_FRACTION:.0%} differs from earlier "
                        f"rows ({label} {time.target_shift:.3f}, at or above {limit}): a random "
                        "split would hide this change from evaluation."
                    )
                else:
                    reasons.append(f"The target in the latest {HOLDOUT_FRACTION:.0%} is similar "
                                   f"to earlier rows ({label} {time.target_shift:.3f}).")
        else:
            reasons.append(
                f"'{time.column}' could not be used as a time column: {time.n_parsed} of "
                f"{time.n_parsed + time.n_unparseable} non-missing values parse as ISO 8601 dates "
                f"(at least {TIME_MIN_PARSED_FRACTION:.0%} of them, {TIME_MIN_ROWS} rows and two "
                "distinct dates are needed)."
            )

    if entity is not None:
        if needs_groups:
            reasons.append(
                f"{entity.rows_in_repeated_entities_fraction:.1%} of rows belong to the "
                f"{entity.n_entities_with_repeats} '{entity.column}' values that occur more than "
                f"once (up to {entity.max_rows_per_entity} rows each). Under a random "
                f"{HOLDOUT_FRACTION:.0%} holdout, about "
                f"{entity.expected_test_rows_with_seen_entity_fraction:.1%} of test rows would "
                "share an entity with a training row."
            )
            if not can_group:
                reasons.append(f"There are only {entity.n_entities} distinct entities (fewer than "
                               f"{GROUP_MIN_ENTITIES}), too few for a useful group holdout; "
                               "collect more entities or evaluate per entity.")
        else:
            reasons.append(
                f"Only {entity.rows_in_repeated_entities_fraction:.1%} of rows share a "
                f"'{entity.column}' value (below {GROUP_MIN_REPEATED_FRACTION:.0%}), so grouping "
                "by entity is not needed."
            )

    if time is not None and time.usable:
        recommended = SplitStrategy.time
        if can_group:
            reasons.append("Entities also repeat: if the model must work for entities it has "
                           "never seen, additionally keep each entity on one side of the cut.")
    elif can_group:
        recommended = SplitStrategy.stratified_group if stratify else SplitStrategy.group
    elif stratify:
        recommended = SplitStrategy.stratified
    else:
        recommended = SplitStrategy.random
        if not reasons:
            reasons.append("No target, entity or time column was selected, so nothing argues "
                           "against a random split. Select them for more specific advice.")

    return SplitAdvice(
        dataset=describe(dataset),
        target_column=target_column,
        entity_column=entity_column,
        time_column=time_column,
        task=task,
        recommended=recommended,
        headline=HEADLINES[recommended],
        reasons=reasons,
        entity=entity,
        time=time,
        limitations=LIMITATIONS,
    )
