"""In-memory CSV ingestion and validation.

The loader never writes uploads to disk, never executes content, and never places cell values in
error messages. Structure is validated with the standard-library ``csv`` module before pandas
parses the data, because pandas silently renames duplicate headers and pads short rows.
"""

import csv
import hashlib
import io
import re
from dataclasses import dataclass

import pandas as pd

from app.config import Limits

_BINARY_SIGNATURES = (
    (b"PK\x03\x04", "a ZIP archive or Excel workbook"),
    (b"\xd0\xcf\x11\xe0", "a legacy Excel or Office file"),
    (b"%PDF", "a PDF document"),
    (b"\x1f\x8b", "a gzip archive"),
    (b"PAR1", "a Parquet file"),
)
_ALLOWED_EXTENSIONS = (".csv",)
_SAFE_FILENAME = re.compile(r"[^A-Za-z0-9._-]+")


class DatasetError(Exception):
    """An expected validation failure. ``message`` is safe to show to users."""

    def __init__(self, code: str, message: str, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class LoadedDataset:
    frame: pd.DataFrame
    filename: str
    size_bytes: int
    sha256: str


def sanitize_filename(filename: str | None, default: str = "dataset.csv") -> str:
    """Reduce a client-supplied filename to a display-only basename of safe characters."""
    if not filename:
        return default
    base = re.split(r"[\\/]", filename)[-1]
    cleaned = _SAFE_FILENAME.sub("_", base).strip("._")[:100]
    return cleaned or default


def _check_format(raw: bytes, filename: str | None) -> None:
    if filename and not filename.lower().endswith(_ALLOWED_EXTENSIONS):
        raise DatasetError(
            "unsupported_format", "Only .csv files are supported.", status_code=415
        )
    for signature, description in _BINARY_SIGNATURES:
        if raw.startswith(signature):
            raise DatasetError(
                "unsupported_format",
                f"The file appears to be {description}, not CSV text. Export it as CSV first.",
                status_code=415,
            )
    if b"\x00" in raw:
        raise DatasetError(
            "unsupported_format",
            "The file contains binary data (NUL bytes) and is not CSV text.",
            status_code=415,
        )


def _validate_structure(raw: bytes, limits: Limits) -> tuple[list[str], int]:
    """Return (header, n_data_rows) after validating encoding, header and row widths."""
    text = io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8-sig", newline="")
    reader = csv.reader(text, strict=True)
    try:
        header: list[str] | None = None
        for record in reader:
            if record:  # pandas also skips blank lines before the header
                header = record
                break
        if header is None:
            raise DatasetError("empty_file", "The file is empty.")
        _validate_header(header, limits)

        n_rows = 0
        for record in reader:
            if not record:
                continue
            if len(record) != len(header):
                raise DatasetError(
                    "malformed_csv",
                    f"Data row {n_rows + 1} (line {reader.line_num}) has {len(record)} fields; "
                    f"the header has {len(header)}.",
                )
            n_rows += 1
            if n_rows > limits.max_rows:
                raise DatasetError(
                    "too_many_rows",
                    f"The file has more than the maximum of {limits.max_rows} data rows.",
                    status_code=413,
                )
    except UnicodeDecodeError:
        raise DatasetError("invalid_encoding", "The file is not valid UTF-8 text.") from None
    except csv.Error:
        raise DatasetError(
            "malformed_csv",
            f"The file could not be parsed as CSV near line {reader.line_num} "
            "(for example an unclosed quote or an oversized field).",
        ) from None
    if n_rows == 0:
        raise DatasetError("no_data_rows", "The file has a header row but no data rows.")
    return header, n_rows


def _validate_header(header: list[str], limits: Limits) -> None:
    if len(header) > limits.max_columns:
        raise DatasetError(
            "too_many_columns",
            f"The file has {len(header)} columns; the maximum is {limits.max_columns}.",
            status_code=413,
        )
    empty = [str(i + 1) for i, name in enumerate(header) if not name.strip()]
    if empty:
        raise DatasetError(
            "empty_header", f"Column(s) at position {', '.join(empty)} have an empty name."
        )
    positions: dict[str, list[int]] = {}
    for i, name in enumerate(header):
        positions.setdefault(name, []).append(i + 1)
    duplicated = [p for p in positions.values() if len(p) > 1]
    if duplicated:
        groups = "; ".join(" and ".join(str(i) for i in group) for group in duplicated)
        raise DatasetError(
            "duplicate_header", f"Columns at positions {groups} share the same name."
        )


def load_csv(raw: bytes, limits: Limits, filename: str | None = None) -> LoadedDataset:
    if len(raw) > limits.max_upload_bytes:
        raise DatasetError(
            "file_too_large",
            f"The file exceeds the maximum size of {limits.max_upload_bytes} bytes.",
            status_code=413,
        )
    if not raw:
        raise DatasetError("empty_file", "The file is empty.")
    _check_format(raw, filename)
    header, n_rows = _validate_structure(raw, limits)

    try:
        frame = pd.read_csv(
            io.BytesIO(raw), encoding="utf-8-sig", low_memory=False, skip_blank_lines=True
        )
    except (pd.errors.ParserError, ValueError, OverflowError):
        raise DatasetError("malformed_csv", "The file could not be parsed as CSV.") from None
    if frame.shape != (n_rows, len(header)) or list(frame.columns) != header:
        # The structural pass and pandas disagree; refuse rather than analyze a misread file.
        raise DatasetError("malformed_csv", "The file's CSV structure is ambiguous.")

    return LoadedDataset(
        frame=frame,
        filename=sanitize_filename(filename),
        size_bytes=len(raw),
        sha256=hashlib.sha256(raw).hexdigest(),
    )


def load_csv_as_text(raw: bytes) -> pd.DataFrame:
    """Re-read an already validated CSV with every cell kept as its original text."""
    return pd.read_csv(
        io.BytesIO(raw),
        encoding="utf-8-sig",
        dtype=str,
        keep_default_na=False,
        na_filter=False,
        skip_blank_lines=True,
    )
