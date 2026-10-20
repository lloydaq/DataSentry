"""Typed response contracts.

Every float in these models is finite or None (``allow_inf_nan=False``): diagnostics convert
NaN and infinity to None before building a model, so serialized output is always strict JSON.
"""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1"

EvidenceValue = bool | int | float | str | None


class Model(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False, extra="forbid")


# --- Dataset and column profiles -------------------------------------------------------------


class InferredType(StrEnum):
    numeric = "numeric"
    boolean = "boolean"
    datetime = "datetime"
    categorical = "categorical"
    text = "text"
    empty = "empty"


class DatasetInfo(Model):
    filename: str
    size_bytes: int
    sha256: str
    n_rows: int
    n_columns: int


class TypeCount(Model):
    inferred_type: InferredType
    n_columns: int


class Overview(Model):
    n_rows: int
    n_columns: int
    memory_bytes: int = Field(description="Approximate in-memory size reported by pandas.")
    type_counts: list[TypeCount] | None = Field(description="None if column profiling failed.")
    n_cells: int
    n_missing_cells: int
    missing_cell_fraction: float
    n_rows_with_missing: int
    rows_with_missing_fraction: float


class OutlierSummary(Model):
    method: Literal["iqr_1.5"] = "iqr_1.5"
    status: Literal["computed", "unavailable"]
    reason: str | None = None
    lower_fence: float | None = None
    upper_fence: float | None = None
    n_below: int = 0
    n_above: int = 0
    fraction: float | None = None


class NumericStats(Model):
    n_finite: int
    n_infinite: int
    min: float | None
    max: float | None
    mean: float | None
    median: float | None
    std: float | None = Field(description="Sample standard deviation (ddof=1); None below 2 values.")
    p05: float | None
    q1: float | None
    q3: float | None
    p95: float | None
    n_zeros: int
    n_negative: int
    all_integer: bool
    outliers: OutlierSummary


class ValueCount(Model):
    value: str
    count: int
    fraction: float


class VariantGroup(Model):
    variants: list[str]
    n_rows: int


class CategoricalStats(Model):
    n_unique: int
    top_values: list[ValueCount]
    top_values_truncated: bool
    n_rare_categories: int | None = Field(
        description="Categories below the rare threshold; None when not evaluated."
    )
    rare_rows_fraction: float | None
    n_variant_groups: int
    variant_groups: list[VariantGroup]
    n_whitespace_values: int
    n_numeric_like: int
    mean_length: float | None
    max_length: int | None
    values_redacted: bool = False


class DatetimeStats(Model):
    min: str | None
    max: str | None
    n_unparseable: int


class ColumnProfile(Model):
    name: str
    position: int
    pandas_dtype: str
    inferred_type: InferredType
    n_non_null: int
    n_missing: int
    missing_fraction: float
    all_missing: bool
    n_unique: int
    unique_fraction: float | None
    is_constant: bool
    dominant_fraction: float | None
    identifier_like: bool
    numeric: NumericStats | None = None
    categorical: CategoricalStats | None = None
    datetime: DatetimeStats | None = None


class DuplicateSummary(Model):
    n_duplicate_rows: int
    duplicate_fraction: float
    n_duplicate_groups: int
    example_row_indices: list[int]
    semantics: str


class CorrelatedPair(Model):
    column_a: str
    column_b: str
    pearson_r: float
    n_pairs: int


class RedundancySummary(Model):
    duplicate_column_groups: list[list[str]]
    correlated_pairs: list[CorrelatedPair]
    correlation_status: Literal["computed", "skipped"]
    correlation_note: str | None = None


# --- Target analysis -------------------------------------------------------------------------


class TargetTask(StrEnum):
    classification = "classification"
    regression = "regression"
    unsupported = "unsupported"


class ClassCount(Model):
    label: str
    count: int
    fraction: float


class ClassDistribution(Model):
    n_classes: int
    classes: list[ClassCount]
    truncated: bool
    majority_count: int
    minority_count: int
    imbalance_ratio: float | None
    rare_class_threshold: int
    n_rare_classes: int
    rare_classes: list[str]


class LabelConflictSummary(Model):
    n_conflicting_groups: int
    n_rows_involved: int
    example_row_indices: list[int]


class LeakageSignal(Model):
    column: str
    method: Literal["category_mapping", "single_feature_auc", "pearson_correlation"]
    statistic: float
    description: str


class TargetAnalysis(Model):
    column: str
    task: TargetTask
    task_reason: str
    n_labeled: int
    n_missing_labels: int
    classes: ClassDistribution | None = None
    regression: NumericStats | None = None
    label_conflicts: LabelConflictSummary | None = None
    leakage_signals: list[LeakageSignal] = []


# --- Findings and summary --------------------------------------------------------------------


class Severity(StrEnum):
    high = "high"
    medium = "medium"
    low = "low"
    info = "info"


class FindingKind(StrEnum):
    likely_issue = "likely_issue"
    potential_issue = "potential_issue"
    observation = "observation"
    inconclusive = "inconclusive"


class Category(StrEnum):
    completeness = "completeness"
    uniqueness = "uniqueness"
    column_quality = "column_quality"
    consistency = "consistency"
    distribution = "distribution"
    target = "target"
    leakage = "leakage"


class Finding(Model):
    code: str
    kind: FindingKind
    severity: Severity
    category: Category
    title: str
    explanation: str
    why_it_matters: str
    recommendation: str
    limitations: str | None = None
    columns: list[str]
    evidence: dict[str, EvidenceValue]
    correction: str | None = Field(
        default=None, description="Id of a proposed correction that addresses this finding."
    )


class CategoryStatus(Model):
    category: Category
    status: Literal["pass", "review", "issue", "not_evaluated"]
    n_findings: int
    highest_severity: Severity | None


class SeverityCount(Model):
    severity: Severity
    count: int


class QualitySummary(Model):
    status: Literal["no_issues_detected", "review_recommended", "issues_detected"]
    headline: str
    severity_counts: list[SeverityCount]
    categories: list[CategoryStatus]
    not_evaluated: list[str]
    score_policy: str


# --- Corrections -----------------------------------------------------------------------------


class CorrectionOperation(StrEnum):
    drop_rows_missing_target = "drop_rows_missing_target"
    drop_duplicate_rows = "drop_duplicate_rows"
    drop_columns = "drop_columns"


class ProposedCorrection(Model):
    id: str
    operation: CorrectionOperation
    title: str
    description: str
    implications: str
    columns: list[str]
    rows_affected: int
    source_findings: list[str]


class CorrectionStep(Model):
    operation: CorrectionOperation
    columns: list[str] = []


class CorrectionPlan(Model):
    approved: bool
    target_column: str | None = None
    steps: list[CorrectionStep] = Field(min_length=1, max_length=3)


class AuditStep(Model):
    operation: CorrectionOperation
    columns: list[str]
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int


class AuditFile(Model):
    filename: str
    sha256: str
    n_rows: int
    n_columns: int


class CorrectionAudit(Model):
    tool_version: str
    applied_at: str
    approved_by_user: bool
    original_modified: Literal[False] = False
    input: AuditFile
    output: AuditFile
    steps: list[AuditStep]
    notes: list[str]


class CorrectionResult(Model):
    audit: CorrectionAudit
    filename: str
    csv: str


# --- Analysis result -------------------------------------------------------------------------


class StageStatus(Model):
    name: str
    status: Literal["completed", "failed", "skipped"]
    detail: str | None = None


class AnalysisSettings(Model):
    target_column: str | None


class AnalysisResult(Model):
    schema_version: str = SCHEMA_VERSION
    tool_version: str
    status: Literal["complete", "partial"]
    dataset: DatasetInfo
    settings: AnalysisSettings
    stages: list[StageStatus]
    overview: Overview
    columns: list[ColumnProfile] | None
    duplicates: DuplicateSummary | None
    redundancy: RedundancySummary | None
    target: TargetAnalysis | None
    findings: list[Finding]
    summary: QualitySummary
    corrections: list[ProposedCorrection]
    limitations: list[str]


# --- Advanced ML checks ----------------------------------------------------------------------


class ExcludedFeature(Model):
    column: str
    reason: str


class LabelCandidate(Model):
    row_index: int
    given_label: str
    predicted_label: str
    given_label_probability: float
    predicted_label_probability: float


class LabelReviewResult(Model):
    status: Literal["completed", "unsupported"]
    reason: str | None = None
    target_column: str
    model: str | None = None
    cv_folds: int | None = None
    random_seed: int | None = None
    n_rows_used: int = 0
    n_rows_excluded: int = 0
    features_used: list[str] = []
    excluded_features: list[ExcludedFeature] = []
    oof_accuracy: float | None = None
    oof_balanced_accuracy: float | None = None
    majority_baseline_accuracy: float | None = None
    n_disagreements: int = 0
    candidates: list[LabelCandidate] = []
    candidates_truncated: bool = False
    limitations: list[str] = []


class TrainTestOverlapResult(Model):
    train: DatasetInfo
    test: DatasetInfo
    target_column: str | None
    common_columns: list[str]
    train_only_columns: list[str]
    test_only_columns: list[str]
    n_test_rows_in_train: int
    test_rows_in_train_fraction: float
    n_test_feature_matches: int | None
    n_feature_matches_with_different_label: int | None
    example_test_row_indices: list[int]
    findings: list[Finding]
    limitations: list[str]


# --- Reports and errors ----------------------------------------------------------------------


class ReportMetadata(Model):
    report_format_version: str = "1"
    tool: str = "DataSentry"
    tool_version: str
    generated_at: str
    include_value_examples: bool
    serialization_policy: str
    privacy_note: str


class ReportDocument(Model):
    metadata: ReportMetadata
    analysis: AnalysisResult
    methodology: list[str]


class LimitsInfo(Model):
    max_upload_bytes: int
    max_rows: int
    max_columns: int
    max_label_review_rows: int


class HealthResponse(Model):
    status: Literal["ok"]
    version: str
    limits: LimitsInfo


class ErrorResponse(Model):
    error: str
    message: str
