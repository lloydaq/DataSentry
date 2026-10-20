"""HTTP endpoints. Parsing and diagnostics live in ``app.services``; this module only adapts HTTP.

Uploads are multipart/form-data with the CSV in a ``file`` field (``train_file``/``test_file`` for
overlap checks). Options travel as form fields rather than query parameters, so column names do
not appear in access logs.
"""

import threading
from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, Request, Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from app.api.uploads import UploadedFile, read_form
from app.config import APP_VERSION, Limits
from app.models.schemas import (
    AnalysisResult,
    CorrectionPlan,
    CorrectionResult,
    ErrorResponse,
    HealthResponse,
    LabelReviewResult,
    LimitsInfo,
    TrainTestOverlapResult,
)
from app.services import corrections, label_review, leakage, report
from app.services.analysis import run_analysis
from app.services.loader import DatasetError, load_csv

T = TypeVar("T")
router = APIRouter(prefix="/api")
_ERRORS = {
    status: {"model": ErrorResponse}
    for status in (400, 413, 415, 422, 500, 503)
}
_BUSY_TIMEOUT_SECONDS = 30
_TRUE = {"true", "1", "on", "yes"}
_FALSE = {"false", "0", "off", "no", ""}


def _limits(request: Request) -> Limits:
    return request.app.state.limits


def _guarded(request: Request, fn: Callable[[], T]) -> T:
    """Run CPU-heavy work in a worker thread while holding a concurrency slot."""
    slots: threading.BoundedSemaphore = request.app.state.analysis_slots
    if not slots.acquire(timeout=_BUSY_TIMEOUT_SECONDS):
        raise DatasetError("server_busy", "The server is busy; try again shortly.", status_code=503)
    try:
        return fn()
    finally:
        slots.release()


async def _run(request: Request, fn: Callable[[], T]) -> T:
    return await run_in_threadpool(_guarded, request, fn)


async def _single_upload(request: Request) -> tuple[UploadedFile, dict[str, str]]:
    files, fields = await read_form(
        request, file_fields=("file",), max_file_bytes=_limits(request).max_upload_bytes
    )
    return files["file"], fields


def _target(fields: dict[str, str]) -> str | None:
    value = fields.get("target_column", "")
    return value if value.strip() else None


def _flag(fields: dict[str, str], name: str) -> bool:
    value = fields.get(name, "").strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise DatasetError("invalid_request", f"Field '{name}' must be true or false.")


@router.get("/health", response_model=HealthResponse)
def health(request: Request) -> HealthResponse:
    limits = _limits(request)
    return HealthResponse(
        status="ok",
        version=APP_VERSION,
        limits=LimitsInfo(
            max_upload_bytes=limits.max_upload_bytes,
            max_rows=limits.max_rows,
            max_columns=limits.max_columns,
            max_label_review_rows=limits.max_label_review_rows,
        ),
    )


@router.post("/analyze", response_model=AnalysisResult, responses=_ERRORS)
async def analyze(request: Request) -> AnalysisResult:
    """Profile an uploaded CSV. Form fields: ``file`` and optional ``target_column``."""
    upload, fields = await _single_upload(request)
    target = _target(fields)
    limits = _limits(request)
    return await _run(
        request, lambda: run_analysis(load_csv(upload.data, limits, upload.filename), target)
    )


@router.post("/report", responses={200: {"content": {"text/html": {}}}, **_ERRORS})
async def download_report(request: Request) -> Response:
    """Analyze and return a downloadable report. Fields: ``file``, ``target_column``,
    ``format`` (``json`` or ``html``) and ``include_values`` (default false)."""
    upload, fields = await _single_upload(request)
    fmt = fields.get("format", "json").strip().lower()
    if fmt not in ("json", "html"):
        raise DatasetError("invalid_request", "Field 'format' must be 'json' or 'html'.")
    include_values = _flag(fields, "include_values")
    target = _target(fields)
    limits = _limits(request)

    def build() -> tuple[str, str]:
        dataset = load_csv(upload.data, limits, upload.filename)
        doc = report.build_report(run_analysis(dataset, target), include_values)
        if fmt == "html":
            return report.render_html(doc), dataset.filename
        return doc.model_dump_json(indent=2), dataset.filename

    body, filename = await _run(request, build)
    stem = filename.rsplit(".", 1)[0]
    return Response(
        content=body,
        media_type="text/html; charset=utf-8" if fmt == "html" else "application/json",
        headers={
            "Content-Disposition": f'attachment; filename="datasentry-report-{stem}.{fmt}"'
        },
    )


@router.post("/label-review", response_model=LabelReviewResult, responses=_ERRORS)
async def review_labels(request: Request) -> LabelReviewResult:
    """Opt-in out-of-fold label review. Fields: ``file`` and required ``target_column``."""
    upload, fields = await _single_upload(request)
    target = _target(fields)
    if target is None:
        raise DatasetError("missing_target_column", "Label review requires a target column.")
    limits = _limits(request)
    return await _run(
        request,
        lambda: label_review.review_labels(
            load_csv(upload.data, limits, upload.filename), target, limits
        ),
    )


@router.post("/train-test-overlap", response_model=TrainTestOverlapResult, responses=_ERRORS)
async def train_test_overlap(request: Request) -> TrainTestOverlapResult:
    """Compare two files. Fields: ``train_file``, ``test_file`` and optional ``target_column``."""
    limits = _limits(request)
    files, fields = await read_form(
        request, file_fields=("train_file", "test_file"), max_file_bytes=limits.max_upload_bytes
    )
    target = _target(fields)
    train, test = files["train_file"], files["test_file"]
    return await _run(
        request,
        lambda: leakage.train_test_overlap(
            load_csv(train.data, limits, train.filename),
            load_csv(test.data, limits, test.filename),
            target,
        ),
    )


@router.post("/corrections/apply", response_model=CorrectionResult, responses=_ERRORS)
async def apply_corrections(request: Request) -> CorrectionResult:
    """Apply an explicitly approved plan to a copy. Fields: ``file`` and ``plan`` (JSON)."""
    upload, fields = await _single_upload(request)
    try:
        plan = CorrectionPlan.model_validate_json(fields.get("plan", ""))
    except ValidationError:
        raise DatasetError(
            "invalid_plan", "Field 'plan' must be a valid correction plan (JSON)."
        ) from None
    limits = _limits(request)
    return await _run(
        request,
        lambda: corrections.apply_corrections(
            upload.data, load_csv(upload.data, limits, upload.filename), plan
        ),
    )
