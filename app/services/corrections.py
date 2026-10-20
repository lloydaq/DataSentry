"""Proposed corrections and their explicit, audited application.

Corrections are never applied automatically. ``apply_corrections`` requires ``approved=True``,
works on a copy that keeps every cell's original text, and returns an audit trail. Imputation is
deliberately not offered: filling values before a train/test split leaks information, so it
belongs inside the modeling pipeline.
"""

import hashlib
from datetime import UTC, datetime

import pandas as pd

from app.config import APP_VERSION
from app.models.schemas import (
    AuditFile,
    AuditStep,
    ColumnProfile,
    CorrectionAudit,
    CorrectionOperation,
    CorrectionPlan,
    CorrectionResult,
    DuplicateSummary,
    ProposedCorrection,
    RedundancySummary,
    TargetAnalysis,
)
from app.services.loader import DatasetError, LoadedDataset, load_csv_as_text

# Steps always run in this order so the result does not depend on how the request lists them.
_ORDER = [
    CorrectionOperation.drop_rows_missing_target,
    CorrectionOperation.drop_duplicate_rows,
    CorrectionOperation.drop_columns,
]


def propose_corrections(
    profiles: list[ColumnProfile] | None,
    duplicates: DuplicateSummary | None,
    redundancy: RedundancySummary | None,
    target: TargetAnalysis | None,
) -> list[ProposedCorrection]:
    proposals: list[ProposedCorrection] = []
    target_name = target.column if target else None
    if target is not None and target.n_missing_labels:
        proposals.append(
            ProposedCorrection(
                id="drop_rows_missing_target",
                operation=CorrectionOperation.drop_rows_missing_target,
                title="Remove rows without a target value",
                description=f"Remove the {target.n_missing_labels} row(s) where '{target.column}' "
                "is missing.",
                implications="These rows can no longer be used for semi-supervised learning or to "
                "study why labels are missing. If labels are missing for a systematic reason, the "
                "remaining sample may be biased.",
                columns=[target.column],
                rows_affected=target.n_missing_labels,
                source_findings=["missing_target_labels"],
            )
        )
    if duplicates is not None and duplicates.n_duplicate_rows:
        proposals.append(
            ProposedCorrection(
                id="drop_duplicate_rows",
                operation=CorrectionOperation.drop_duplicate_rows,
                title="Remove exact duplicate rows",
                description=f"Keep the first occurrence of each row and remove the "
                f"{duplicates.n_duplicate_rows} repeat(s).",
                implications="If repeats are genuine repeated events (for example two identical "
                "purchases), removing them changes the data distribution.",
                columns=[],
                rows_affected=duplicates.n_duplicate_rows,
                source_findings=["duplicate_rows"],
            )
        )
    if profiles is not None:
        columns = [p.name for p in profiles if p.all_missing or p.is_constant]
        sources = {"all_missing_column", "constant_column"}
        if redundancy is not None:
            for group in redundancy.duplicate_column_groups:
                columns.extend(group[1:])
            if redundancy.duplicate_column_groups:
                sources.add("duplicate_columns")
        ordered = [p.name for p in profiles if p.name in set(columns) and p.name != target_name]
        if ordered:
            proposals.append(
                ProposedCorrection(
                    id="drop_columns",
                    operation=CorrectionOperation.drop_columns,
                    title="Drop columns that carry no extra information",
                    description=f"Drop {len(ordered)} column(s) that are empty, constant, or exact "
                    "copies of another column.",
                    implications="Constant columns may vary in future data; dropping them here "
                    "means a model never sees them. Copies are dropped while the first column of "
                    "each identical group is kept.",
                    columns=ordered,
                    rows_affected=0,
                    source_findings=sorted(sources),
                )
            )
    return proposals


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def apply_corrections(raw: bytes, dataset: LoadedDataset, plan: CorrectionPlan) -> CorrectionResult:
    if not plan.approved:
        raise DatasetError(
            "approval_required", "Corrections are only applied after explicit approval."
        )
    operations = [s.operation for s in plan.steps]
    if len(set(operations)) != len(operations):
        raise DatasetError("invalid_plan", "Each correction may appear only once in a plan.")

    parsed = dataset.frame
    text = load_csv_as_text(raw)
    if text.shape != parsed.shape:
        raise DatasetError("malformed_csv", "The file's CSV structure is ambiguous.")

    by_op = {s.operation: s for s in plan.steps}
    keep = pd.Series(True, index=parsed.index)
    drop_cols: list[str] = []
    steps: list[AuditStep] = []
    n_rows, n_cols = parsed.shape

    for op in _ORDER:
        step = by_op.get(op)
        if step is None:
            continue
        rows_before, cols_before = int(keep.sum()), n_cols - len(drop_cols)
        if op is CorrectionOperation.drop_rows_missing_target:
            if plan.target_column is None or plan.target_column not in parsed.columns:
                raise DatasetError(
                    "unknown_target_column",
                    "Removing rows without a target requires a valid target column.",
                )
            keep &= parsed[plan.target_column].notna()
            columns = [plan.target_column]
        elif op is CorrectionOperation.drop_duplicate_rows:
            keep &= ~(parsed[keep].duplicated(keep="first").reindex(parsed.index, fill_value=False))
            columns = []
        else:
            unknown = [c for c in step.columns if c not in parsed.columns]
            if not step.columns or unknown:
                raise DatasetError(
                    "invalid_plan", "Dropping columns requires a list of existing column names."
                )
            if plan.target_column in step.columns:
                raise DatasetError("invalid_plan", "The target column cannot be dropped.")
            columns = [c for c in parsed.columns if c in set(step.columns)]
            drop_cols = columns
        steps.append(
            AuditStep(
                operation=op,
                columns=columns,
                rows_before=rows_before,
                rows_after=int(keep.sum()),
                columns_before=cols_before,
                columns_after=n_cols - len(drop_cols),
            )
        )

    result = text.loc[keep.to_numpy()].drop(columns=drop_cols)
    if result.shape[0] == 0 or result.shape[1] == 0:
        raise DatasetError("invalid_plan", "The corrections would leave an empty dataset.")
    csv_text = result.to_csv(index=False, lineterminator="\n")
    stem = dataset.filename.rsplit(".", 1)[0]
    out_name = f"{stem}.corrected.csv"
    audit = CorrectionAudit(
        tool_version=APP_VERSION,
        applied_at=datetime.now(UTC).isoformat(timespec="seconds"),
        approved_by_user=True,
        input=AuditFile(
            filename=dataset.filename, sha256=dataset.sha256, n_rows=n_rows, n_columns=n_cols
        ),
        output=AuditFile(
            filename=out_name,
            sha256=_sha256_text(csv_text),
            n_rows=int(result.shape[0]),
            n_columns=int(result.shape[1]),
        ),
        steps=steps,
        notes=[
            "The uploaded file was not modified; this is a corrected copy.",
            "Cell text is preserved exactly; the file is re-quoted where CSV syntax requires it "
            "and written as UTF-8 without a byte-order mark.",
            "Steps run in a fixed order: rows without a target, duplicate rows, then columns. "
            "Duplicates are identified using all original columns.",
        ],
    )
    return CorrectionResult(audit=audit, filename=out_name, csv=csv_text)
