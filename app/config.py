"""Resource limits. Defaults suit a local workstation; override them with environment variables."""

import os
from dataclasses import dataclass

APP_VERSION = "0.1.0"


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer.") from exc
    if value < 1:
        raise RuntimeError(f"Environment variable {name} must be at least 1.")
    return value


@dataclass(frozen=True)
class Limits:
    max_upload_bytes: int = 10 * 1024 * 1024
    max_rows: int = 200_000
    max_columns: int = 500
    max_concurrent_analyses: int = 2
    max_label_review_rows: int = 20_000

    @classmethod
    def from_env(cls) -> "Limits":
        defaults = cls()
        return cls(
            max_upload_bytes=_env_int("DATASENTRY_MAX_UPLOAD_BYTES", defaults.max_upload_bytes),
            max_rows=_env_int("DATASENTRY_MAX_ROWS", defaults.max_rows),
            max_columns=_env_int("DATASENTRY_MAX_COLUMNS", defaults.max_columns),
            max_concurrent_analyses=_env_int(
                "DATASENTRY_MAX_CONCURRENT_ANALYSES", defaults.max_concurrent_analyses
            ),
            max_label_review_rows=_env_int(
                "DATASENTRY_MAX_LABEL_REVIEW_ROWS", defaults.max_label_review_rows
            ),
        )
