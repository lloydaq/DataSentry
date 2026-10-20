"""Bounded, in-memory multipart parsing.

Starlette's default parser spools uploads larger than 1 MB to temporary files on disk. This
module caps the request body while it streams and keeps every part in memory, so an upload is
never persisted and an oversized body is rejected without being read in full.
"""

from dataclasses import dataclass

from starlette.datastructures import UploadFile
from starlette.formparsers import MultiPartException, MultiPartParser
from starlette.requests import Request

from app.services.loader import DatasetError

FIELD_MAX_BYTES = 64 * 1024
_MULTIPART_OVERHEAD = 64 * 1024


@dataclass(frozen=True)
class UploadedFile:
    data: bytes
    filename: str | None


class _InMemoryParser(MultiPartParser):
    def __init__(self, *args, spool_bytes: int, **kwargs):
        super().__init__(*args, **kwargs)
        self.spool_max_size = spool_bytes  # never roll over to a temporary file


async def read_form(
    request: Request, *, file_fields: tuple[str, ...], max_file_bytes: int, max_text_fields: int = 8
) -> tuple[dict[str, UploadedFile], dict[str, str]]:
    content_type = request.headers.get("content-type", "")
    if not content_type.lower().startswith("multipart/form-data"):
        raise DatasetError(
            "unsupported_media_type", "Send the file as multipart/form-data.", status_code=415
        )
    max_body = len(file_fields) * max_file_bytes + _MULTIPART_OVERHEAD
    declared = request.headers.get("content-length")
    if declared is not None and declared.isdigit() and int(declared) > max_body:
        raise _too_large(max_file_bytes)

    async def capped_stream():
        total = 0
        async for chunk in request.stream():
            total += len(chunk)
            if total > max_body:
                raise _too_large(max_file_bytes)
            yield chunk

    parser = _InMemoryParser(
        request.headers,
        capped_stream(),
        max_files=len(file_fields),
        max_fields=max_text_fields,
        max_part_size=FIELD_MAX_BYTES,
        spool_bytes=max_body,
    )
    try:
        form = await parser.parse()
    except MultiPartException:
        raise DatasetError(
            "malformed_request", "The multipart request could not be parsed.", status_code=400
        ) from None

    try:
        files: dict[str, UploadedFile] = {}
        fields: dict[str, str] = {}
        for key, value in form.multi_items():
            if isinstance(value, UploadFile):
                if key in file_fields and key not in files:
                    files[key] = UploadedFile(data=await value.read(), filename=value.filename)
            elif key not in fields:
                fields[key] = value
    finally:
        await form.close()
    missing = [name for name in file_fields if name not in files]
    if missing:
        raise DatasetError(
            "missing_file", f"The request must include a file field named '{missing[0]}'."
        )
    return files, fields


def _too_large(max_file_bytes: int) -> DatasetError:
    return DatasetError(
        "file_too_large",
        f"The upload exceeds the maximum size of {max_file_bytes} bytes per file.",
        status_code=413,
    )
