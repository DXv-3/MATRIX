from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from matrix.config import catalog_db, data_dir, quarantine_dir, scan_roots

# Load .env from project root or ~/.matrix/.env before reading vars
_ENV_LOADED = False


def load_env() -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    candidates = [
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        data_dir() / ".env",
    ]
    try:
        from dotenv import load_dotenv

        for path in candidates:
            if path.is_file():
                load_dotenv(path, override=False)
        _ENV_LOADED = True
    except ImportError:
        _ENV_LOADED = True


@lru_cache
def settings() -> "MatrixSettings":
    load_env()
    return MatrixSettings()


def reload_settings() -> MatrixSettings:
    settings.cache_clear()
    return settings()


class MatrixSettings:
    def __init__(self) -> None:
        self.env = os.environ.get("MATRIX_ENV", "development").strip().lower()
        self.production = self.env in ("production", "prod")
        self.api_host = os.environ.get("MATRIX_API_HOST", "127.0.0.1")
        self.api_port = int(os.environ.get("MATRIX_API_PORT", "8765"))
        self.api_token = os.environ.get("MATRIX_API_TOKEN", "").strip()
        self.log_level = os.environ.get("MATRIX_LOG_LEVEL", "INFO" if self.production else "DEBUG")
        self.log_file = os.environ.get("MATRIX_LOG_FILE", str(data_dir() / "matrix.log"))
        self.bind_public = os.environ.get("MATRIX_BIND_PUBLIC", "0") == "1"
        self.workers_default = max(1, min(int(os.environ.get("MATRIX_SCAN_WORKERS", "4")), 32))

    def validate_production(self) -> list[str]:
        errors: list[str] = []
        if not self.production:
            return errors
        if not self.api_token or len(self.api_token) < 16:
            errors.append("MATRIX_API_TOKEN must be set (16+ chars) in production")
        if self.bind_public and self.api_host == "0.0.0.0" and not self.api_token:
            errors.append("Public bind requires MATRIX_API_TOKEN")
        if not scan_roots():
            errors.append("MATRIX_SCAN_ROOTS must list at least one archive directory")
        if not catalog_db().parent.exists():
            errors.append(f"Data directory missing: {data_dir()}")
        for root in scan_roots():
            if not root.is_dir():
                errors.append(f"Scan root not found: {root}")
        q = quarantine_dir()
        if not q.exists():
            try:
                q.mkdir(parents=True, exist_ok=True)
            except OSError:
                errors.append(f"Cannot create quarantine: {q}")
        return errors

    @staticmethod
    def generate_token() -> str:
        return secrets.token_urlsafe(32)