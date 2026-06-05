from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from matrix.config import catalog_db, data_dir


def backup_catalog(dest: Path | None = None) -> Path:
    """Copy catalog.db + WAL/SHM to timestamped backup folder."""
    src = catalog_db()
    if not src.is_file():
        raise FileNotFoundError(f"No catalog at {src}")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = dest or (data_dir() / "backups" / stamp)
    out.mkdir(parents=True, exist_ok=True)

    for name in (src.name, f"{src.name}-wal", f"{src.name}-shm"):
        p = src.parent / name
        if p.is_file():
            shutil.copy2(p, out / name)
    return out