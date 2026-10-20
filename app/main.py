"""Application setup: routes, error handling, security headers and the static frontend."""

import logging
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import MutableHeaders
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.api.routes import router
from app.config import APP_VERSION, Limits
from app.models.schemas import ErrorResponse
from app.services.loader import DatasetError

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger("datasentry")

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
}
_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'; "
    "frame-ancestors 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")  # Swagger UI loads its assets from a CDN


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(ErrorResponse(error=code, message=message).model_dump(), status_code=status)


class SafetyMiddleware:
    """Adds security headers and turns unhandled exceptions into a generic 500 response.

    Only the exception type and request path are logged: exception messages from parsing
    libraries can quote cell values.
    """

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        started = False
        path = scope.get("path", "")

        async def send_with_headers(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                headers = MutableHeaders(scope=message)
                for name, value in _SECURITY_HEADERS.items():
                    headers.setdefault(name, value)
                if not path.startswith(_DOCS_PATHS):
                    headers.setdefault("Content-Security-Policy", _CSP)
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        except Exception as exc:
            logger.error("Unhandled %s while serving %s", type(exc).__name__, path)
            if not started:
                response = _error(500, "internal_error", "An unexpected error occurred.")
                await response(scope, receive, send_with_headers)


def create_app(limits: Limits | None = None) -> FastAPI:
    app = FastAPI(
        title="DataSentry",
        version=APP_VERSION,
        description="Local-first dataset diagnostics for machine-learning practitioners.",
    )
    app.state.limits = limits or Limits.from_env()
    app.state.analysis_slots = threading.BoundedSemaphore(app.state.limits.max_concurrent_analyses)

    @app.exception_handler(DatasetError)
    async def dataset_error(_: Request, exc: DatasetError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        # FastAPI's default body echoes the submitted input; return field locations only.
        fields = sorted({".".join(str(p) for p in e.get("loc", ())) for e in exc.errors()})
        return _error(422, "invalid_request", f"Invalid request fields: {', '.join(fields)}.")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        messages = {404: "Not found.", 405: "Method not allowed."}
        message = messages.get(exc.status_code, "The request could not be completed.")
        return _error(exc.status_code, "http_error", message)

    app.include_router(router)
    app.mount("/samples", StaticFiles(directory=ROOT / "sample_data"), name="samples")
    app.mount("/", StaticFiles(directory=ROOT / "frontend", html=True), name="frontend")
    app.add_middleware(SafetyMiddleware)
    return app


app = create_app()
