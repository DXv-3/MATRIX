from __future__ import annotations

import hashlib
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

from matrix.config import SUPPORTED_EXTENSIONS, XMP_SUFFIX
from matrix.db import Database
from matrix.hasher import HashResult, classify_file, hash_file
from matrix.security import MAX_XMP_BYTES, assert_asset_readable, safe_file_size


def _is_supported(path: Path) -> bool:
    if path.name.startswith("."):
        return False
    ext = path.suffix.lower()
    return ext in SUPPORTED_EXTENSIONS or ext == XMP_SUFFIX


def discover_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for dirpath, _, filenames in os.walk(root, followlinks=False):
        for name in filenames:
            p = Path(dirpath) / name
            if _is_supported(p):
                try:
                    files.append(p.resolve())
                except OSError:
                    continue
    return files


def _xmp_for_raw(path: Path) -> str | None:
    if classify_file(path) != "RAW":
        return None
    sidecar = path.with_suffix(path.suffix + XMP_SUFFIX)
    if sidecar.is_file():
        return str(sidecar.resolve())
    alt = path.with_suffix(XMP_SUFFIX)
    if alt.is_file():
        return str(alt.resolve())
    return None


def _file_stat(path: Path) -> tuple[float, int]:
    st = path.stat()
    return st.st_mtime, st.st_size


def _upsert_asset(
    db: Database,
    path: Path,
    result: HashResult,
    mtime: float,
    size_bytes: int,
    parent_id: int | None,
    xmp_path: str | None,
) -> int:
    row = db.fetchone("SELECT id, mtime, sha256 FROM assets WHERE path = ?", (str(path),))
    if row and row["mtime"] == mtime and row["sha256"] == result.sha256:
        return int(row["id"])

    now = datetime.now(timezone.utc).isoformat()
    if row:
        db.execute(
            """
            UPDATE assets SET
                sha256=?, phash=?, file_type=?, mime_type=?, size_bytes=?,
                width=?, height=?, mtime=?, parent_id=?, xmp_sidecar_path=?,
                updated_at=?
            WHERE id=?
            """,
            (
                result.sha256,
                result.phash,
                result.file_type,
                result.mime_type,
                size_bytes,
                result.width,
                result.height,
                mtime,
                parent_id,
                xmp_path,
                now,
                row["id"],
            ),
        )
        return int(row["id"])

    cur = db.execute(
        """
        INSERT INTO assets (
            path, filename, sha256, phash, file_type, mime_type, size_bytes,
            width, height, mtime, parent_id, xmp_sidecar_path, updated_at, scanned_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(path),
            path.name,
            result.sha256,
            result.phash,
            result.file_type,
            result.mime_type,
            size_bytes,
            result.width,
            result.height,
            mtime,
            parent_id,
            xmp_path,
            now,
            now,
        ),
    )
    return int(cur.lastrowid)


def _sha256_xmp(path: Path) -> str:
    safe_file_size(path, MAX_XMP_BYTES)
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            block = f.read(1024 * 1024)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _link_xmp_parent(db: Database, raw_id: int, xmp_path: str) -> None:
    xmp = Path(xmp_path)
    if not xmp.is_file():
        return
    mtime, size_bytes = _file_stat(xmp)
    result = HashResult(
        sha256=_sha256_xmp(xmp),
        phash=None,
        width=None,
        height=None,
        file_type="OTHER",
        mime_type="application/xml",
    )
    _upsert_asset(db, xmp, result, mtime, size_bytes, parent_id=raw_id, xmp_path=None)


def scan_file(db: Database, path: Path, scan_root: Path | None = None) -> int:
    path = path.resolve()
    if path.suffix.lower() == XMP_SUFFIX:
        return 0
    extra = [scan_root.resolve()] if scan_root else None
    assert_asset_readable(path, extra_roots=extra)
    mtime, size_bytes = _file_stat(path)
    result = hash_file(path)
    xmp_path = _xmp_for_raw(path)
    asset_id = _upsert_asset(db, path, result, mtime, size_bytes, None, xmp_path)
    if xmp_path:
        _link_xmp_parent(db, asset_id, xmp_path)
    return asset_id


def scan_directory(db: Database, root: Path, workers: int = 4) -> dict[str, int]:
    db.init_schema()
    root = root.resolve()
    paths = [p for p in discover_files(root) if p.suffix.lower() != XMP_SUFFIX]
    workers = max(1, min(workers, 32))

    scanned = 0
    errors = 0

    def _work(p: Path) -> bool:
        try:
            scan_file(db, p, scan_root=root)
            return True
        except Exception:
            return False

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_work, p): p for p in paths}
        for fut in as_completed(futures):
            if fut.result():
                scanned += 1
            else:
                errors += 1

    return {
        "root": str(root),
        "files": len(paths),
        "scanned": scanned,
        "errors": errors,
        "skipped": 0,
    }