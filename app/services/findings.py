"""Turn profiling observations into explainable findings and a qualitative summary.

Each rule is fixed and documented. ``kind`` states how strong the evidence is: ``likely_issue`` for
facts that are almost always a problem for modeling (e.g. an all-missing column),
``potential_issue`` for patterns that are often but not always problems, ``observation`` for
neutral facts worth knowing, and ``inconclusive`` when a check could not reach a result.
"""

from app.models.schemas import (
    Category,
    CategoryStatus,
    ColumnProfile,
    DuplicateSummary,
    Finding,
    FindingKind,
    InferredType,
    QualitySummary,
    RedundancySummary,
    Severity,
    SeverityCount,
    StageStatus,
    TargetAnalysis,
    TargetTask,
)

MISSING_REPORT_FRACTION = 0.05  # below this, missing values are summarized as one observation
MISSING_HIGH_FRACTION = 0.5
DUPLICATE_MEDIUM_FRACTION = 0.05
NEAR_CONSTANT_FRACTION = 0.95
NEAR_CONSTANT_MIN_ROWS = 20
HIGH_CARDINALITY_MIN_UNIQUE = 50
HIGH_CARDINALITY_FRACTION = 0.5
MIXED_TYPE_MIN_VALUES = 5
MIXED_TYPE_NUMERIC_FRACTION = 0.8
IMBALANCE_OBSERVATION_RATIO = 3.0
HIGH_CARDINALITY_TARGET_CLASSES = 50
MISSING_TARGET_MEDIUM_FRACTION = 0.05

_SEVERITY_ORDER = {s: i for i, s in enumerate(Severity)}
_KIND_ORDER = {k: i for i, k in enumerate(FindingKind)}
_CATEGORY_ORDER = {c: i for i, c in enumerate(Category)}
_PROBLEM_KINDS = (FindingKind.likely_issue, FindingKind.potential_issue)

SCORE_POLICY = (
    "DataSentry does not compute a single numeric quality score. Any weighting of missing values "
    "against duplicates, leakage or label problems would be arbitrary, would depend on the "
    "modeling task, and could let a high score hide a severe individual problem. Instead each "
    "category is reported separately and every finding states its own evidence. Nothing here "
    "predicts model accuracy."
)


def _pct(value: float) -> str:
    return f"{value:.1%}"


def column_findings(
    profiles: list[ColumnProfile], n_rows: int, target: str | None = None
) -> list[Finding]:
    """Column-level findings. Missing target values are reported by ``target_findings``."""
    findings: list[Finding] = []
    minor_missing: list[ColumnProfile] = []
    for p in profiles:
        if p.all_missing:
            findings.append(
                Finding(
                    code="all_missing_column",
                    kind=FindingKind.likely_issue,
                    severity=Severity.medium,
                    category=Category.completeness,
                    title=f"Column '{p.name}' contains only missing values",
                    explanation=f"All {n_rows} values are missing (empty or a recognized missing "
                    "token such as NA or null).",
                    why_it_matters="The column carries no information and some tools fail on "
                    "all-missing inputs. It can also signal a broken export or join.",
                    recommendation="Check the data source; if the column is not expected to be "
                    "populated, drop it.",
                    columns=[p.name],
                    evidence={"n_missing": p.n_missing, "n_rows": n_rows},
                    correction="drop_columns",
                )
            )
            continue
        if p.n_missing and p.name != target:
            if p.missing_fraction < MISSING_REPORT_FRACTION:
                minor_missing.append(p)
            else:
                high = p.missing_fraction >= MISSING_HIGH_FRACTION
                findings.append(
                    Finding(
                        code="missing_values",
                        kind=FindingKind.potential_issue,
                        severity=Severity.medium if high else Severity.low,
                        category=Category.completeness,
                        title=f"Column '{p.name}' is missing {_pct(p.missing_fraction)} of values",
                        explanation=f"{p.n_missing} of {n_rows} values are missing.",
                        why_it_matters="Many estimators reject missing values, and the way they are "
                        "filled can bias a model, especially when values are not missing at random.",
                        recommendation="Investigate why values are missing. Handle them inside the "
                        "modeling pipeline (imputation fitted on training data only, a missing "
                        "indicator, or a model that supports missing values) rather than before "
                        "splitting.",
                        limitations="Whether missingness is a problem depends on the task; missing "
                        "can be informative.",
                        columns=[p.name],
                        evidence={
                            "n_missing": p.n_missing,
                            "missing_fraction": p.missing_fraction,
                            "high_threshold": MISSING_HIGH_FRACTION,
                        },
                    )
                )
        if p.is_constant:
            note = (
                " The only other variation is missingness."
                if p.n_missing
                else ""
            )
            findings.append(
                Finding(
                    code="constant_column",
                    kind=FindingKind.likely_issue,
                    severity=Severity.low,
                    category=Category.column_quality,
                    title=f"Column '{p.name}' has a single distinct value",
                    explanation=f"Every non-missing value in the column is identical.{note}",
                    why_it_matters="A constant feature cannot help a model distinguish examples and "
                    "adds noise to feature-importance and preprocessing steps.",
                    recommendation="Drop the column for modeling unless it is expected to vary in "
                    "future data.",
                    columns=[p.name],
                    evidence={"n_unique": p.n_unique, "n_missing": p.n_missing},
                    correction="drop_columns",
                )
            )
        elif (
            p.dominant_fraction is not None
            and p.dominant_fraction >= NEAR_CONSTANT_FRACTION
            and p.n_non_null >= NEAR_CONSTANT_MIN_ROWS
        ):
            findings.append(
                Finding(
                    code="near_constant_column",
                    kind=FindingKind.observation,
                    severity=Severity.info,
                    category=Category.column_quality,
                    title=f"Column '{p.name}' is dominated by one value",
                    explanation=f"The most frequent value accounts for "
                    f"{_pct(p.dominant_fraction)} of non-missing values.",
                    why_it_matters="Near-constant features carry little signal and can be "
                    "unstable across cross-validation folds.",
                    recommendation="Keep the column if the rare values are meaningful (such as a "
                    "rare-event flag); otherwise consider dropping it.",
                    columns=[p.name],
                    evidence={
                        "dominant_fraction": p.dominant_fraction,
                        "threshold": NEAR_CONSTANT_FRACTION,
                    },
                )
            )
        if p.identifier_like:
            findings.append(
                Finding(
                    code="possible_identifier",
                    kind=FindingKind.observation,
                    severity=Severity.info,
                    category=Category.column_quality,
                    title=f"Column '{p.name}' looks like an identifier",
                    explanation="Every row has a different, non-missing value.",
                    why_it_matters="Identifiers rarely generalize as features; a model can memorize "
                    "them. They are still useful for joins and deduplication.",
                    recommendation="Exclude the column from model features unless it encodes "
                    "meaningful information.",
                    limitations="Based on uniqueness only; column names are not used.",
                    columns=[p.name],
                    evidence={"n_unique": p.n_unique, "n_rows": n_rows},
                )
            )
        elif (
            p.inferred_type in (InferredType.categorical, InferredType.text)
            and p.n_unique >= HIGH_CARDINALITY_MIN_UNIQUE
            and (p.unique_fraction or 0) >= HIGH_CARDINALITY_FRACTION
        ):
            findings.append(
                Finding(
                    code="high_cardinality_column",
                    kind=FindingKind.observation,
                    severity=Severity.info,
                    category=Category.column_quality,
                    title=f"Column '{p.name}' has many distinct values",
                    explanation=f"{p.n_unique} distinct values ({_pct(p.unique_fraction or 0)} of "
                    "non-missing values).",
                    why_it_matters="One-hot encoding a high-cardinality column creates very wide, "
                    "sparse inputs; the column may be free text or an identifier.",
                    recommendation="Consider target or frequency encoding, text features, or "
                    "excluding the column.",
                    columns=[p.name],
                    evidence={"n_unique": p.n_unique, "unique_fraction": p.unique_fraction},
                )
            )
        findings.extend(_consistency_findings(p))
        findings.extend(_numeric_findings(p))

    if minor_missing:
        findings.append(
            Finding(
                code="minor_missing_values",
                kind=FindingKind.observation,
                severity=Severity.info,
                category=Category.completeness,
                title=f"{len(minor_missing)} column(s) have a small share of missing values",
                explanation=f"Each of these columns is missing less than "
                f"{_pct(MISSING_REPORT_FRACTION)} of its values.",
                why_it_matters="Even a few missing values make some estimators fail.",
                recommendation="Handle missing values inside the modeling pipeline.",
                columns=[p.name for p in minor_missing],
                evidence={"n_columns": len(minor_missing), "threshold": MISSING_REPORT_FRACTION},
            )
        )
    return findings


def _consistency_findings(p: ColumnProfile) -> list[Finding]:
    stats = p.categorical
    if stats is None:
        return []
    out: list[Finding] = []
    if (
        p.inferred_type in (InferredType.categorical, InferredType.text)
        and p.n_non_null >= MIXED_TYPE_MIN_VALUES
        and MIXED_TYPE_NUMERIC_FRACTION * p.n_non_null <= stats.n_numeric_like < p.n_non_null
    ):
        n_text = p.n_non_null - stats.n_numeric_like
        out.append(
            Finding(
                code="mixed_numeric_text",
                kind=FindingKind.potential_issue,
                severity=Severity.medium,
                category=Category.consistency,
                title=f"Column '{p.name}' is mostly numbers stored as text",
                explanation=f"{stats.n_numeric_like} of {p.n_non_null} non-missing values parse "
                f"as numbers, but {n_text} do not, so the whole column was read as text.",
                why_it_matters="The numeric information is lost unless the non-numeric entries "
                "(units, thousands separators, placeholders such as '?') are cleaned.",
                recommendation="Inspect the non-numeric entries and convert the column explicitly.",
                columns=[p.name],
                evidence={"n_numeric_like": stats.n_numeric_like, "n_non_numeric": n_text},
            )
        )
    if stats.n_variant_groups:
        out.append(
            Finding(
                code="inconsistent_category_variants",
                kind=FindingKind.potential_issue,
                severity=Severity.low,
                category=Category.consistency,
                title=f"Column '{p.name}' has categories that differ only in case or spacing",
                explanation=f"{stats.n_variant_groups} group(s) of values become identical after "
                "trimming, collapsing whitespace and ignoring case.",
                why_it_matters="Variants such as 'Yes', 'yes ' and 'YES' are treated as different "
                "categories, splitting their signal.",
                recommendation="Normalize the values if the variants mean the same thing.",
                limitations="Case or spacing can be meaningful (codes, identifiers).",
                columns=[p.name],
                evidence={"n_variant_groups": stats.n_variant_groups},
            )
        )
    if stats.n_whitespace_values:
        out.append(
            Finding(
                code="surrounding_whitespace",
                kind=FindingKind.potential_issue,
                severity=Severity.low,
                category=Category.consistency,
                title=f"Column '{p.name}' has values with leading or trailing whitespace",
                explanation=f"{stats.n_whitespace_values} values start or end with whitespace.",
                why_it_matters="Hidden whitespace creates distinct categories and breaks joins.",
                recommendation="Trim whitespace if it is not meaningful.",
                columns=[p.name],
                evidence={"n_values": stats.n_whitespace_values},
            )
        )
    return out


def _numeric_findings(p: ColumnProfile) -> list[Finding]:
    stats = p.numeric
    if stats is None:
        return []
    out: list[Finding] = []
    if stats.n_infinite:
        out.append(
            Finding(
                code="infinite_values",
                kind=FindingKind.likely_issue,
                severity=Severity.medium,
                category=Category.consistency,
                title=f"Column '{p.name}' contains infinite values",
                explanation=f"{stats.n_infinite} values are positive or negative infinity. They "
                "are excluded from the statistics shown.",
                why_it_matters="Most estimators and scalers fail or produce NaN on infinite inputs; "
                "infinities often come from division by zero upstream.",
                recommendation="Trace how the values were computed and replace or remove them.",
                columns=[p.name],
                evidence={"n_infinite": stats.n_infinite},
            )
        )
    o = stats.outliers
    if o.status == "computed" and (o.n_below or o.n_above):
        out.append(
            Finding(
                code="outlier_candidates",
                kind=FindingKind.observation,
                severity=Severity.info,
                category=Category.distribution,
                title=f"Column '{p.name}' has values outside the IQR fences",
                explanation=f"{o.n_below} value(s) fall below {o.lower_fence} and {o.n_above} "
                f"above {o.upper_fence} (Tukey fences at 1.5 x IQR).",
                why_it_matters="Extreme values can dominate scale-sensitive models. They may be "
                "errors, or genuine and important observations.",
                recommendation="Review these values against domain knowledge before deciding to "
                "keep, cap or remove them.",
                limitations="IQR fences flag many points in skewed or heavy-tailed distributions; "
                "being flagged does not make a value wrong.",
                columns=[p.name],
                evidence={
                    "n_below": o.n_below,
                    "n_above": o.n_above,
                    "lower_fence": o.lower_fence,
                    "upper_fence": o.upper_fence,
                    "fraction": o.fraction,
                },
            )
        )
    elif o.status == "unavailable" and stats.n_finite >= 10 and p.n_unique > 2:
        out.append(
            Finding(
                code="outlier_screen_inconclusive",
                kind=FindingKind.inconclusive,
                severity=Severity.info,
                category=Category.distribution,
                title=f"Outlier screening was inconclusive for '{p.name}'",
                explanation=o.reason or "The IQR method could not be applied.",
                why_it_matters="Unusual values in this column were not screened.",
                recommendation="Inspect the value distribution directly.",
                columns=[p.name],
                evidence={"n_finite": stats.n_finite},
            )
        )
    return out


def duplicate_findings(dup: DuplicateSummary, n_rows: int) -> list[Finding]:
    if not dup.n_duplicate_rows:
        return []
    return [
        Finding(
            code="duplicate_rows",
            kind=FindingKind.potential_issue,
            severity=Severity.medium
            if dup.duplicate_fraction >= DUPLICATE_MEDIUM_FRACTION
            else Severity.low,
            category=Category.uniqueness,
            title=f"{dup.n_duplicate_rows} exact duplicate row(s)",
            explanation=f"{dup.n_duplicate_rows} of {n_rows} rows "
            f"({_pct(dup.duplicate_fraction)}) repeat an earlier row exactly, across "
            f"{dup.n_duplicate_groups} distinct repeated record(s).",
            why_it_matters="Duplicates over-weight some examples and, when they land on both "
            "sides of a train/test split, inflate evaluation metrics.",
            recommendation="Confirm the duplicates are not legitimate repeated events, then "
            "deduplicate before splitting.",
            limitations="Only exact duplicates are detected; near-duplicates are not.",
            columns=[],
            evidence={
                "n_duplicate_rows": dup.n_duplicate_rows,
                "duplicate_fraction": dup.duplicate_fraction,
                "n_duplicate_groups": dup.n_duplicate_groups,
            },
            correction="drop_duplicate_rows",
        )
    ]


def redundancy_findings(red: RedundancySummary) -> list[Finding]:
    out = [
        Finding(
            code="duplicate_columns",
            kind=FindingKind.likely_issue,
            severity=Severity.low,
            category=Category.column_quality,
            title=f"{len(group)} columns hold identical values",
            explanation=f"Columns {', '.join(repr(c) for c in group)} are identical in every row.",
            why_it_matters="Exact copies add no information and distort feature importance.",
            recommendation=f"Keep one of them (for example '{group[0]}') and drop the others.",
            columns=group,
            evidence={"n_columns": len(group)},
            correction="drop_columns",
        )
        for group in red.duplicate_column_groups
    ]
    for pair in red.correlated_pairs:
        out.append(
            Finding(
                code="highly_correlated_columns",
                kind=FindingKind.observation,
                severity=Severity.info,
                category=Category.column_quality,
                title=f"'{pair.column_a}' and '{pair.column_b}' are almost perfectly correlated",
                explanation=f"Pearson r = {pair.pearson_r} across {pair.n_pairs} rows.",
                why_it_matters="Near-duplicate features make linear model coefficients unstable "
                "and split importance between them.",
                recommendation="Consider keeping only one, or use regularization.",
                limitations="Correlation measures linear association only.",
                columns=[pair.column_a, pair.column_b],
                evidence={"pearson_r": pair.pearson_r, "n_pairs": pair.n_pairs},
            )
        )
    return out


def target_findings(t: TargetAnalysis) -> list[Finding]:
    col = [t.column]
    out = [
        Finding(
            code="target_task_inferred",
            kind=FindingKind.observation,
            severity=Severity.info,
            category=Category.target,
            title=f"Target '{t.column}' analyzed as {t.task.value}",
            explanation=t.task_reason,
            why_it_matters="The task type determines which target checks apply.",
            recommendation="Confirm that this matches the intended modeling task.",
            columns=col,
            evidence={"task": t.task.value, "n_labeled": t.n_labeled},
        )
    ]
    if t.n_missing_labels:
        frac = t.n_missing_labels / (t.n_labeled + t.n_missing_labels)
        out.append(
            Finding(
                code="missing_target_labels",
                kind=FindingKind.potential_issue,
                severity=Severity.medium if frac >= MISSING_TARGET_MEDIUM_FRACTION else Severity.low,
                category=Category.target,
                title=f"{t.n_missing_labels} row(s) have no target value",
                explanation=f"{_pct(frac)} of rows are missing the target.",
                why_it_matters="Unlabeled rows cannot be used for supervised training or "
                "evaluation, and silently dropping them can bias the sample.",
                recommendation="Find out why labels are missing, then exclude those rows from "
                "supervised training explicitly.",
                columns=col,
                evidence={"n_missing_labels": t.n_missing_labels, "missing_fraction": round(frac, 6)},
                correction="drop_rows_missing_target",
            )
        )
    if t.task is TargetTask.unsupported:
        out.append(
            Finding(
                code="target_unsupported",
                kind=FindingKind.inconclusive,
                severity=Severity.info,
                category=Category.target,
                title=f"Target '{t.column}' could not be analyzed",
                explanation=t.task_reason,
                why_it_matters="No class or label checks were run.",
                recommendation="Select a different target column.",
                columns=col,
                evidence={},
            )
        )
    c = t.classes
    if c is not None:
        if c.n_classes == 1:
            out.append(
                Finding(
                    code="single_class_target",
                    kind=FindingKind.likely_issue,
                    severity=Severity.high,
                    category=Category.target,
                    title="The target has only one class",
                    explanation="Every labeled row has the same target value.",
                    why_it_matters="A classifier cannot be trained or evaluated on a single class.",
                    recommendation="Check whether the data was filtered or the wrong column was "
                    "selected as the target.",
                    columns=col,
                    evidence={"n_classes": 1},
                )
            )
        if c.n_classes > HIGH_CARDINALITY_TARGET_CLASSES:
            out.append(
                Finding(
                    code="high_cardinality_target",
                    kind=FindingKind.potential_issue,
                    severity=Severity.medium,
                    category=Category.target,
                    title=f"The target has {c.n_classes} classes",
                    explanation=f"More than {HIGH_CARDINALITY_TARGET_CLASSES} distinct target "
                    "values; only the most frequent are listed.",
                    why_it_matters="This may be an identifier, free text, or a continuous quantity "
                    "rather than a class label.",
                    recommendation="Confirm the target column and the task type.",
                    columns=col,
                    evidence={"n_classes": c.n_classes},
                )
            )
        if c.n_rare_classes and c.n_classes > 1:
            out.append(
                Finding(
                    code="rare_classes",
                    kind=FindingKind.potential_issue,
                    severity=Severity.medium,
                    category=Category.target,
                    title=f"{c.n_rare_classes} class(es) have fewer than "
                    f"{c.rare_class_threshold} examples",
                    explanation="Rare classes: " + ", ".join(repr(x) for x in c.rare_classes[:10])
                    + ("…" if c.n_rare_classes > 10 else "") + ".",
                    why_it_matters=f"A class with fewer than {c.rare_class_threshold} examples "
                    "cannot appear in every fold of 5-fold stratified cross-validation, and "
                    "metrics for it are very noisy.",
                    recommendation="Collect more examples, merge rare classes if that is "
                    "meaningful, or use fewer folds.",
                    columns=col,
                    evidence={"n_rare_classes": c.n_rare_classes, "threshold": c.rare_class_threshold},
                )
            )
        if c.imbalance_ratio is not None and c.imbalance_ratio >= IMBALANCE_OBSERVATION_RATIO:
            out.append(
                Finding(
                    code="class_imbalance",
                    kind=FindingKind.observation,
                    severity=Severity.info,
                    category=Category.target,
                    title=f"Classes are imbalanced (ratio {c.imbalance_ratio:.1f}:1)",
                    explanation=f"The largest class has {c.majority_count} examples and the "
                    f"smallest {c.minority_count}.",
                    why_it_matters="Imbalance is common and not a defect, but accuracy becomes "
                    "misleading and minority classes need enough examples to learn from.",
                    recommendation="Use stratified splits and metrics such as balanced accuracy, "
                    "per-class recall or PR-AUC. Resample or reweight only inside training folds.",
                    columns=col,
                    evidence={
                        "imbalance_ratio": c.imbalance_ratio,
                        "majority_count": c.majority_count,
                        "minority_count": c.minority_count,
                    },
                )
            )
    lc = t.label_conflicts
    if lc is not None and lc.n_conflicting_groups:
        out.append(
            Finding(
                code="conflicting_labels",
                kind=FindingKind.potential_issue,
                severity=Severity.medium,
                category=Category.target,
                title="Identical feature rows carry different labels",
                explanation=f"{lc.n_conflicting_groups} group(s) of rows ({lc.n_rows_involved} rows) "
                "share every feature value but have different target values.",
                why_it_matters="This indicates label noise or that the features do not contain "
                "enough information to separate these cases.",
                recommendation="Review the example rows to decide which explanation applies.",
                columns=col,
                evidence={
                    "n_conflicting_groups": lc.n_conflicting_groups,
                    "n_rows_involved": lc.n_rows_involved,
                },
            )
        )
    for s in t.leakage_signals:
        out.append(
            Finding(
                code="possible_target_leakage",
                kind=FindingKind.potential_issue,
                severity=Severity.high,
                category=Category.leakage,
                title=f"Feature '{s.column}' almost perfectly predicts the target",
                explanation=s.description,
                why_it_matters="A feature this predictive is often derived from the target or "
                "recorded after the outcome, which inflates validation scores and fails in "
                "production.",
                recommendation="Verify that the feature is available at prediction time and is not "
                "computed from the target. If it is legitimate, the task may simply be easy.",
                limitations="A strong association does not prove leakage.",
                columns=[s.column, t.column],
                evidence={"method": s.method, "statistic": s.statistic},
            )
        )
    return out


def sort_findings(findings: list[Finding]) -> list[Finding]:
    return sorted(
        findings,
        key=lambda f: (
            _SEVERITY_ORDER[f.severity],
            _KIND_ORDER[f.kind],
            _CATEGORY_ORDER[f.category],
            f.code,
            f.columns,
        ),
    )


def summarize(
    findings: list[Finding], stages: list[StageStatus], target_selected: bool, notes: list[str]
) -> QualitySummary:
    failed = {s.name for s in stages if s.status != "completed"}
    unevaluated_categories = set()
    if not target_selected or "target" in failed:
        unevaluated_categories |= {Category.target, Category.leakage}
    if "duplicates" in failed:
        unevaluated_categories.add(Category.uniqueness)
    if "columns" in failed:
        unevaluated_categories |= {
            Category.completeness,
            Category.column_quality,
            Category.consistency,
            Category.distribution,
        }

    categories: list[CategoryStatus] = []
    for category in Category:
        items = [f for f in findings if f.category is category]
        highest = min((f.severity for f in items), key=_SEVERITY_ORDER.get, default=None)
        if category in unevaluated_categories and not items:
            status = "not_evaluated"
        elif any(
            f.kind in _PROBLEM_KINDS and f.severity in (Severity.high, Severity.medium)
            for f in items
        ):
            status = "issue"
        elif any(f.kind in _PROBLEM_KINDS or f.kind is FindingKind.inconclusive for f in items):
            status = "review"
        else:
            status = "pass"
        categories.append(
            CategoryStatus(
                category=category, status=status, n_findings=len(items), highest_severity=highest
            )
        )

    problems = [f for f in findings if f.kind in _PROBLEM_KINDS]
    n_high = sum(f.severity is Severity.high for f in problems)
    n_obs = len(findings) - len(problems)
    if any(c.status == "issue" for c in categories):
        status = "issues_detected"
    elif any(c.status == "review" for c in categories):
        status = "review_recommended"
    else:
        status = "no_issues_detected"
    if problems:
        headline = f"{len(problems)} potential problem(s) found"
        headline += f", {n_high} of high severity." if n_high else "."
    else:
        headline = "No potential problems detected by the checks that ran."
    if n_obs:
        headline += f" {n_obs} observation(s) recorded."

    not_evaluated = list(notes)
    if not target_selected:
        not_evaluated.append("Target and leakage checks: no target column was selected.")
    for s in stages:
        if s.status == "failed":
            not_evaluated.append(f"Stage '{s.name}' failed; its checks are missing from this report.")
    return QualitySummary(
        status=status,
        headline=headline,
        severity_counts=[
            SeverityCount(severity=s, count=sum(f.severity is s for f in findings)) for s in Severity
        ],
        categories=categories,
        not_evaluated=not_evaluated,
        score_policy=SCORE_POLICY,
    )
