from __future__ import annotations

import os
from pathlib import Path

from matrix.config import data_dir, quarantine_dir, scan_roots

# Block scanning system/sensitive trees (prefix match after resolve)
_BLOCKED_PREFIXES = tuple(
    Path(p).resolve()
    for p in (
        "/etc",
        "/usr",
        "/bin",
        "/sbin",
        "/System",
        "/Library",
        "/private/etc",
        os.path.expanduser("~/.ssh"),
        os.path.expanduser("~/.gnupg"),
    )
)

MAX_HASH_BYTES = int(os.environ.get("MATRIX_MAX_HASH_BYTES", str(512 * 1024 * 1024)))  # 512 MiB
MAX_XMP_BYTES = int(os.environ.get("MATRIX_MAX_XMP_BYTES", str(32 * 1024 * 1024)))  # 32 MiB


class PathValidationError(ValueError):
    pass


def resolve_directory(path: str | Path) -> Path:
    """Resolve and validate a user-supplied directory for scan/API."""
    p = Path(path).expanduser()
    if ".." in p.parts:
        raise PathValidationError("Path must not contain '..' segments before resolve")
    resolved = p.resolve(strict=False)
    if not resolved.is_dir():
        raise PathValidationError(f"Not a directory: {resolved}")
    _assert_not_blocked(resolved)
    return resolved


def allowed_read_roots() -> list[Path]:
    roots = [r.resolve() for r in scan_roots() if r.exists() and r.is_dir()]
    roots.extend(
        [
            data_dir().resolve(),
            quarantine_dir().resolve(),
        ]
    )
    return roots


def path_under_allowed_roots(path: Path, extra_roots: list[Path] | None = None) -> bool:
    """True if resolved path is under a configured scan/data/quarantine root."""
    resolved = path.resolve()
    if resolved.is_symlink():
        resolved = resolved.resolve()
    roots = extra_roots if extra_roots is not None else allowed_read_roots()
    for root in roots:
        try:
            resolved.relative_to(root)
            return True
        except ValueError:
            continue
    return False


def assert_asset_readable(path: Path, extra_roots: list[Path] | None = None) -> Path:
    """Enforce file reads stay under allowed MATRIX roots (and optional scan root)."""
    resolved = path.resolve()
    if resolved.is_symlink():
        resolved = resolved.resolve()
    if not resolved.is_file():
        raise PathValidationError(f"File not found: {resolved}")
    roots = list(extra_roots or []) + allowed_read_roots()
    if not path_under_allowed_roots(resolved, extra_roots=roots):
        raise PathValidationError("Path outside allowed MATRIX roots")
    return resolved


def assert_quarantine_destination(dest: Path) -> Path:
    base = quarantine_dir().resolve()
    resolved = dest.resolve()
    try:
        resolved.relative_to(base)
    except ValueError as exc:
        raise PathValidationError("Quarantine destination must be under MATRIX_QUARANTINE") from exc
    return resolved


def _is_under(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _assert_not_blocked(path: Path) -> None:
    resolved = path.resolve()
    for blocked in _BLOCKED_PREFIXES:
        b = blocked.resolve()
        if resolved == b or _is_under(resolved, b):
            raise PathValidationError(f"Refusing blocked path: {resolved}")


def safe_file_size(path: Path, max_bytes: int) -> int:
    size = path.stat().st_size
    if size > max_bytes:
        raise PathValidationError(f"File too large ({size} bytes > {max_bytes}): {path}")
    return size