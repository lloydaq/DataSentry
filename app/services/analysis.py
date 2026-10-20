"""Run every diagnostic stage and assemble a single, deterministic result.

Stages after the overview are isolated: if one fails, the result is marked ``partial``, the
failure is listed in ``stages``, and the summary names the checks that are missing. A failure in
the overview itself propagates, because nothing meaningful can be reported without it.
"""

import logging
from collections.abc import Callable
from typing import TypeVar

from app.config import APP_VERSION
from app.models.schemas import AnalysisResult, AnalysisSettings, DatasetInfo, StageStatus
from app.services import corrections, findings, profiler, target
from app.services.loader import DatasetError, LoadedDataset

logger = logging.getLogger("datasentry.analysis")
T = TypeVar("T")

LIMITATIONS = [
    "Checks are heuristic screens with documented thresholds; findings are prompts for review, "
    "not verdicts about the data.",
    "Only exact duplicates are detected. Near-duplicates and related records are not.",
    "Datetime columns are recognized only in ISO 8601 form (YYYY-MM-DD with optional time).",
    "Values such as NA, N/A, null, NaN and empty cells are read as missing (pandas defaults).",
    "No single numeric quality score is produced; see the summary's score policy.",
]


def _run(name: str, fn: Callable[[], T], stages: list[StageStatus]) -> T | None:
    try:
        value = fn()
    except Exception as exc:  # isolate the stage; never log exception text, which may hold values
        logger.error("Analysis stage %s failed with %s", name, type(exc).__name__)
        stages.append(StageStatus(name=name, status="failed", detail="This stage failed unexpectedly."))
        return None
    stages.append(StageStatus(name=name, status="completed"))
    return value


def run_analysis(dataset: LoadedDataset, target_column: str | None = None) -> AnalysisResult:
    frame = dataset.frame
    if target_column is not None and target_column not in frame.columns:
        raise DatasetError(
            "unknown_target_column", "The selected target column does not exist in the dataset."
        )
    stages: list[StageStatus] = []
    n_rows = len(frame)

    profiles = _run("columns", lambda: profiler.profile_columns(frame), stages)
    overview = profiler.overview(frame, profiles)
    duplicates = _run("duplicates", lambda: profiler.duplicate_rows(frame), stages)
    redundancy = (
        _run("redundancy", lambda: profiler.redundancy(frame, profiles), stages)
        if profiles is not None
        else None
    )
    target_result = None
    if target_column is not None:
        if profiles is None:
            stages.append(
                StageStatus(name="target", status="skipped", detail="Column profiling failed.")
            )
        else:
            target_result = _run(
                "target", lambda: target.analyze_target(frame, target_column, profiles), stages
            )

    found = []
    if profiles is not None:
        found += findings.column_findings(profiles, n_rows, target_column)
    if duplicates is not None:
        found += findings.duplicate_findings(duplicates, n_rows)
    if redundancy is not None:
        found += findings.redundancy_findings(redundancy)
    if target_result is not None:
        found += findings.target_findings(target_result)
    found = findings.sort_findings(found)

    notes = []
    if redundancy is not None and redundancy.correlation_note:
        notes.append(redundancy.correlation_note)
    notes.append("Label review and train/test overlap are separate, opt-in checks.")
    summary = findings.summarize(found, stages, target_column is not None, notes)

    return AnalysisResult(
        tool_version=APP_VERSION,
        status="complete" if all(s.status == "completed" for s in stages) else "partial",
        dataset=DatasetInfo(
            filename=dataset.filename,
            size_bytes=dataset.size_bytes,
            sha256=dataset.sha256,
            n_rows=n_rows,
            n_columns=frame.shape[1],
        ),
        settings=AnalysisSettings(target_column=target_column),
        stages=stages,
        overview=overview,
        columns=profiles,
        duplicates=duplicates,
        redundancy=redundancy,
        target=target_result,
        findings=found,
        summary=summary,
        corrections=corrections.propose_corrections(profiles, duplicates, redundancy, target_result),
        limitations=LIMITATIONS,
    )
