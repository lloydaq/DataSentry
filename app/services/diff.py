"""Dataset diff: what changed between two versions of a dataset, before you retrain on it.

Both files are analyzed with the same settings, then compared: columns added, removed, possibly
renamed or retyped; rows kept, added and dropped; missing-rate and distribution changes per column;
and which findings are new, resolved or persisting. Shift statistics are effect sizes with fixed
thresholds, not probabilities or significance tests.
"""

import numpy as np
import pandas as pd

from app.models.schemas import (
    AnalysisResult,
    Category,
    ColumnChange,
    ColumnProfile,
    DatasetDiff,
    Finding,
    FindingChanges,
    FindingKind,
    FindingRef,
    InferredType,
    RenameCandidate,
    RowChanges,
    SchemaChanges,
    Severity,
    TypeChange,
)
from app.services import findings as F
from app.services.analysis import run_analysis
from app.services.leakage import row_hashes
from app.services.loader import LoadedDataset
from app.services.profiler import clip, finite, label_strings, numeric_values

SHIFT_MIN_VALUES = 20  # each version needs this many non-missing values to compare a distribution
KS_SHIFT_THRESHOLD = 0.1  # Kolmogorov–Smirnov statistic at which a numeric column counts as shifted
KS_MAJOR_THRESHOLD = 0.25
PSI_SHIFT_THRESHOLD = 0.1  # population stability index at which a categorical column counts as shifted
PSI_MAJOR_THRESHOLD = 0.25
PSI_FLOOR = 1e-4  # category shares are floored at this value so a new or vanished category is finite
MISSING_INCREASE_THRESHOLD = 0.05  # absolute increase in a column's missing share worth reporting
MISSING_INCREASE_MAJOR = 0.2
RENAME_MIN_OVERLAP = 0.8  # Jaccard similarity of distinct values for a removed/added pair
RENAME_MAX_PAIRS = 2500  # removed x added pairs compared at most
RENAME_MAX_DISTINCT = 10_000  # columns with more distinct values are not compared for renames
CATEGORY_EXAMPLES_LIMIT = 10

_CATEGORY_TYPES = (InferredType.categorical, InferredType.boolean)
_SEVERITY_ORDER = {s: i for i, s in enumerate(Severity)}

LIMITATIONS = [
    "Shift statistics compare whole distributions: Kolmogorov–Smirnov for numeric columns and the "
    "population stability index for categorical ones. They are effect sizes with fixed thresholds, "
    "not significance tests, and a shift can be expected (new season, new market).",
    "Possible renames are guesses from overlapping values and matching types; confirm them.",
    "Rows are matched exactly on the columns both versions share, with 64-bit hashes; edited rows "
    "count as one dropped and one added row.",
    "Both files are read with the same parsing options and analyzed with the same target.",
]


def ks_statistic(a: np.ndarray, b: np.ndarray) -> float:
    """Two-sample Kolmogorov–Smirnov statistic: the largest gap between the empirical CDFs."""
    a, b = np.sort(a), np.sort(b)
    points = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, points, side="right") / len(a)
    cdf_b = np.searchsorted(b, points, side="right") / len(b)
    return float(np.max(np.abs(cdf_a - cdf_b)))


def psi(old: pd.Series, new: pd.Series) -> float:
    """Population stability index over the union of categories, with shares floored at PSI_FLOOR."""
    p_old = old.value_counts(normalize=True)
    p_new = new.value_counts(normalize=True)
    both = p_old.index.union(p_new.index)
    o = np.maximum(p_old.reindex(both, fill_value=0).to_numpy(), PSI_FLOOR)
    n = np.maximum(p_new.reindex(both, fill_value=0).to_numpy(), PSI_FLOOR)
    return float(np.sum((n - o) * np.log(n / o)))


def _column_change(name: str, old: pd.Series, new: pd.Series, po: ColumnProfile, pn: ColumnProfile) -> ColumnChange:
    change = ColumnChange(
        column=name,
        old_type=po.inferred_type,
        new_type=pn.inferred_type,
        old_missing_fraction=po.missing_fraction,
        new_missing_fraction=pn.missing_fraction,
        shift_measure=None,
        shift_statistic=None,
        shifted=False,
    )
    if po.inferred_type != pn.inferred_type:
        change.note = "The inferred type changed, so the distributions were not compared."
        return change
    if po.inferred_type is InferredType.numeric:
        change.old_mean = po.numeric.mean if po.numeric else None
        change.new_mean = pn.numeric.mean if pn.numeric else None
        a = numeric_values(old).to_numpy()
        b = numeric_values(new).to_numpy()
        a, b = a[np.isfinite(a)], b[np.isfinite(b)]
        if min(len(a), len(b)) < SHIFT_MIN_VALUES:
            change.note = f"Fewer than {SHIFT_MIN_VALUES} values in a version; not compared."
            return change
        change.shift_measure, change.shift_statistic = "ks", finite(ks_statistic(a, b))
        change.shifted = change.shift_statistic >= KS_SHIFT_THRESHOLD
    elif po.inferred_type in _CATEGORY_TYPES:
        a, b = label_strings(old), label_strings(new)
        added = sorted(set(b) - set(a))
        gone = sorted(set(a) - set(b))
        change.n_new_categories, change.n_vanished_categories = len(added), len(gone)
        change.new_categories = [clip(v) for v in added[:CATEGORY_EXAMPLES_LIMIT]]
        change.vanished_categories = [clip(v) for v in gone[:CATEGORY_EXAMPLES_LIMIT]]
        if min(len(a), len(b)) < SHIFT_MIN_VALUES:
            change.note = f"Fewer than {SHIFT_MIN_VALUES} values in a version; not compared."
            return change
        change.shift_measure, change.shift_statistic = "psi", finite(psi(a, b))
        change.shifted = change.shift_statistic >= PSI_SHIFT_THRESHOLD
    else:
        change.note = f"Distributions of {po.inferred_type.value} columns are not compared."
    return change


def _rename_candidates(
    old: pd.DataFrame, new: pd.DataFrame, removed: list[str], added: list[str],
    types_old: dict[str, InferredType], types_new: dict[str, InferredType],
) -> tuple[list[RenameCandidate], bool]:
    if len(removed) * len(added) > RENAME_MAX_PAIRS:
        return [], False

    def distinct(series: pd.Series) -> set[str] | None:
        values = set(label_strings(series))
        return values if 0 < len(values) <= RENAME_MAX_DISTINCT else None

    old_sets = {c: distinct(old[c]) for c in removed}
    new_sets = {c: distinct(new[c]) for c in added}
    scored = []
    for r in removed:
        for a in added:
            if types_old[r] != types_new[a] or old_sets[r] is None or new_sets[a] is None:
                continue
            overlap = len(old_sets[r] & new_sets[a]) / len(old_sets[r] | new_sets[a])
            if overlap >= RENAME_MIN_OVERLAP:
                scored.append((-overlap, r, a))
    used_old, used_new, result = set(), set(), []
    for neg, r, a in sorted(scored):  # greedy, best overlap first, ties by name
        if r in used_old or a in used_new:
            continue
        used_old.add(r)
        used_new.add(a)
        result.append(RenameCandidate(old_name=r, new_name=a, value_overlap=finite(-neg)))
    return result, True


def _rows(old: pd.DataFrame, new: pd.DataFrame, common: list[str]) -> RowChanges:
    if not common:
        return RowChanges(
            n_old=len(old), n_new=len(new), n_columns_compared=0,
            n_new_rows_found_in_old=0, n_new_rows_not_in_old=len(new), n_old_rows_not_in_new=len(old),
        )
    h_old, h_new = row_hashes(old, new, common)
    found = int(np.isin(h_new, h_old).sum())
    return RowChanges(
        n_old=len(old),
        n_new=len(new),
        n_columns_compared=len(common),
        n_new_rows_found_in_old=found,
        n_new_rows_not_in_old=len(new) - found,
        n_old_rows_not_in_new=int((~np.isin(h_old, h_new)).sum()),
    )


def _finding_changes(old: AnalysisResult, new: AnalysisResult) -> FindingChanges | None:
    if old.status != "complete" or new.status != "complete":
        return None

    def refs(result: AnalysisResult) -> dict[tuple[str, tuple[str, ...]], FindingRef]:
        return {
            (f.code, tuple(f.columns)): FindingRef(
                code=f.code, title=f.title, severity=f.severity, columns=f.columns
            )
            for f in result.findings
        }

    a, b = refs(old), refs(new)

    def ordered(items: list[FindingRef]) -> list[FindingRef]:
        return sorted(items, key=lambda r: (_SEVERITY_ORDER[r.severity], r.code, r.columns))

    return FindingChanges(
        new=ordered([b[k] for k in b.keys() - a.keys()]),
        resolved=ordered([a[k] for k in a.keys() - b.keys()]),
        persisting=ordered([b[k] for k in b.keys() & a.keys()]),
    )


def _finding(code, kind, severity, category, title, explanation, why, next_step, columns, evidence, limitations=None):
    return Finding(
        code=code, kind=kind, severity=severity, category=category, title=title,
        explanation=explanation, why_it_matters=why, recommendation=next_step,
        limitations=limitations, columns=columns, evidence=evidence,
    )


def _diff_findings(
    schema: SchemaChanges, changes: list[ColumnChange], target: str | None
) -> list[Finding]:
    found: list[Finding] = []
    if schema.removed:
        renamed = len(schema.possible_renames)
        found.append(_finding(
            "diff_columns_removed", FindingKind.potential_issue, Severity.medium, Category.consistency,
            "Columns from the previous version are missing",
            f"{len(schema.removed)} column(s) exist only in the previous version"
            + (f"; {renamed} of them look renamed." if renamed else "."),
            "Pipelines, features and models that read these columns will fail or silently change.",
            "Confirm the removals are intended, and update feature code for any renamed columns.",
            schema.removed, {"n_removed": len(schema.removed), "n_possible_renames": renamed},
        ))
    if schema.type_changes:
        found.append(_finding(
            "diff_type_changes", FindingKind.potential_issue, Severity.medium, Category.consistency,
            "Column types changed between versions",
            f"{len(schema.type_changes)} shared column(s) are inferred as a different type, for "
            "example numbers that now contain text.",
            "A type change usually breaks preprocessing or changes how a model reads the column.",
            "Check how these columns are produced; a few bad values can turn a numeric column into text.",
            [t.column for t in schema.type_changes], {"n_type_changes": len(schema.type_changes)},
        ))
    shifted = sorted((c for c in changes if c.shifted), key=lambda c: (-c.shift_statistic, c.column))
    if shifted:
        major = any(
            c.shift_statistic >= (KS_MAJOR_THRESHOLD if c.shift_measure == "ks" else PSI_MAJOR_THRESHOLD)
            for c in shifted
        )
        with_target = target is not None and any(c.column == target for c in shifted)
        found.append(_finding(
            "diff_distribution_shift", FindingKind.potential_issue,
            Severity.medium if major else Severity.low, Category.distribution,
            "Column distributions shifted between versions",
            f"{len(shifted)} column(s) changed distribution at or above the shift thresholds"
            + (", including the target." if with_target else ".")
            + f" The largest is '{shifted[0].column}' ({shifted[0].shift_measure.upper()} "
            f"{shifted[0].shift_statistic:.3f}).",
            "A model trained on the previous version may perform differently on data that looks like "
            "the new one, and evaluation on old data will not show it.",
            "Find out whether the change is real (new population, season, source) or a pipeline "
            "error, and re-evaluate on recent data before retraining or deploying.",
            [c.column for c in shifted],
            {"n_shifted": len(shifted), "max_statistic": shifted[0].shift_statistic,
             "target_shifted": with_target},
            limitations="Effect sizes with fixed thresholds, not significance tests.",
        ))
    worse = sorted(
        (c for c in changes
         if c.new_missing_fraction - c.old_missing_fraction >= MISSING_INCREASE_THRESHOLD),
        key=lambda c: (c.old_missing_fraction - c.new_missing_fraction, c.column),
    )
    if worse:
        top = worse[0].new_missing_fraction - worse[0].old_missing_fraction
        found.append(_finding(
            "diff_missing_rate_increase", FindingKind.potential_issue,
            Severity.medium if top >= MISSING_INCREASE_MAJOR else Severity.low, Category.completeness,
            "More missing values than in the previous version",
            f"{len(worse)} column(s) gained at least {MISSING_INCREASE_THRESHOLD:.0%} more missing "
            f"values; the largest increase is '{worse[0].column}' "
            f"({worse[0].old_missing_fraction:.1%} to {worse[0].new_missing_fraction:.1%}).",
            "A sudden rise in missing values often points to a broken upstream source or join.",
            "Check the data source for these columns before training on the new version.",
            [c.column for c in worse],
            {"n_columns": len(worse), "max_increase": finite(top)},
        ))
    if schema.added:
        found.append(_finding(
            "diff_columns_added", FindingKind.observation, Severity.info, Category.consistency,
            "New columns in this version",
            f"{len(schema.added)} column(s) exist only in the new version.",
            "New columns are not used by existing models until feature code includes them.",
            "Decide whether the new columns should become features, and check them for leakage.",
            schema.added, {"n_added": len(schema.added)},
        ))
    with_new = [c for c in changes if c.n_new_categories]
    if with_new:
        found.append(_finding(
            "diff_new_categories", FindingKind.observation, Severity.info, Category.consistency,
            "Categorical columns gained new values",
            f"{len(with_new)} column(s) contain values that never occur in the previous version.",
            "Encoders fitted on the previous version may fail on, or ignore, unseen categories.",
            "Check that encoders handle unknown categories, and whether the new values are spelling "
            "variants of old ones.",
            [c.column for c in with_new],
            {"n_columns": len(with_new), "n_new_values": sum(c.n_new_categories for c in with_new)},
        ))
    return F.sort_findings(found)


def _headline(identical: bool, schema: SchemaChanges, rows: RowChanges, changes: list[ColumnChange]) -> str:
    if identical:
        return "The two files are identical."
    parts = []
    if schema.added or schema.removed:
        parts.append(f"{len(schema.added)} column(s) added and {len(schema.removed)} removed")
    if schema.type_changes:
        parts.append(f"{len(schema.type_changes)} type change(s)")
    n_shifted = sum(c.shifted for c in changes)
    if n_shifted:
        parts.append(f"{n_shifted} shifted distribution(s)")
    n_missing = sum(
        c.new_missing_fraction - c.old_missing_fraction >= MISSING_INCREASE_THRESHOLD for c in changes
    )
    if n_missing:
        parts.append(f"{n_missing} column(s) with more missing values")
    n_new_values = sum(bool(c.n_new_categories) for c in changes)
    if n_new_values:
        parts.append(f"{n_new_values} column(s) with new categories")
    rows_text = f"Rows: {rows.n_old} to {rows.n_new} ({rows.n_new_rows_not_in_old} new, " \
        f"{rows.n_old_rows_not_in_new} dropped)."
    if not parts:
        return "No schema, type, missing-value or distribution changes above the thresholds. " + rows_text
    summary = "; ".join(parts)
    return summary[0].upper() + summary[1:] + ". " + rows_text


def dataset_diff(old: LoadedDataset, new: LoadedDataset, target_column: str | None) -> DatasetDiff:
    a_old = run_analysis(old, target_column)
    a_new = run_analysis(new, target_column)
    fo, fn = old.frame, new.frame
    common = [c for c in fo.columns if c in fn.columns]
    removed = [c for c in fo.columns if c not in fn.columns]
    added = [c for c in fn.columns if c not in fo.columns]
    prof_old = {p.name: p for p in a_old.columns or []}
    prof_new = {p.name: p for p in a_new.columns or []}
    limitations = list(LIMITATIONS)

    changes: list[ColumnChange] = []
    renames: list[RenameCandidate] = []
    type_changes: list[TypeChange] = []
    if prof_old and prof_new:
        changes = [_column_change(c, fo[c], fn[c], prof_old[c], prof_new[c]) for c in common]
        type_changes = [
            TypeChange(column=c.column, old_type=c.old_type, new_type=c.new_type)
            for c in changes if c.old_type != c.new_type
        ]
        renames, compared = _rename_candidates(
            fo, fn, removed, added,
            {k: v.inferred_type for k, v in prof_old.items()},
            {k: v.inferred_type for k, v in prof_new.items()},
        )
        if not compared:
            limitations.append(f"Renames were not checked: more than {RENAME_MAX_PAIRS} removed x "
                               "added column pairs.")
    else:
        limitations.append("Column profiling failed for a version, so columns were not compared.")

    finding_changes = _finding_changes(a_old, a_new)
    if finding_changes is None:
        limitations.append("A version's analysis was partial, so findings were not compared.")

    schema = SchemaChanges(added=added, removed=removed, possible_renames=renames, type_changes=type_changes)
    rows = _rows(fo, fn, common)
    identical = old.sha256 == new.sha256
    return DatasetDiff(
        old=a_old.dataset,
        new=a_new.dataset,
        identical=identical,
        target_column=target_column,
        headline=_headline(identical, schema, rows, changes),
        schema_changes=schema,
        rows=rows,
        columns=changes,
        finding_changes=finding_changes,
        findings=[] if identical else _diff_findings(schema, changes, target_column),
        limitations=limitations,
    )

