from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from matrix.config import quarantine_dir
from matrix.db import Database
from matrix.security import (
    PathValidationError,
    assert_asset_readable,
    assert_quarantine_destination,
)


def quarantine_path_for(asset_path: Path, base: Path | None = None) -> Path:
    base = base or quarantine_dir()
    base.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe_name = asset_path.name.replace("/", "_").replace("\\", "_").replace(" ", "_")
    dest = base / stamp / safe_name
    return assert_quarantine_destination(dest)


def move_to_quarantine(
    db: Database,
    asset_id: int,
    source: Path,
    dry_run: bool,
    review_decision_id: int | None = None,
) -> Path:
    row = db.fetchone("SELECT path FROM assets WHERE id=?", (asset_id,))
    if not row or Path(row["path"]).resolve() != source.resolve():
        raise PathValidationError("Source path does not match catalog asset")

    source = assert_asset_readable(source)
    dest = quarantine_path_for(source)

    if dry_run:
        return dest

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(source), str(dest))
    db.execute(
        """
        INSERT INTO quarantine_moves (asset_id, source_path, quarantine_path, review_decision_id)
        VALUES (?, ?, ?, ?)
        """,
        (asset_id, str(source), str(dest), review_decision_id),
    )
    db.execute(
        "UPDATE assets SET path=?, review_status='REJECTED', updated_at=? WHERE id=?",
        (
            str(dest),
            datetime.now(timezone.utc).isoformat(),
            asset_id,
        ),
    )
    return dest


def restore_from_quarantine(db: Database, move_id: int) -> None:
    if move_id < 1:
        raise ValueError("invalid move_id")
    row = db.fetchone("SELECT * FROM quarantine_moves WHERE id=?", (move_id,))
    if not row:
        raise FileNotFoundError(f"quarantine move {move_id} not found")
    src = Path(row["quarantine_path"])
    dst = Path(row["source_path"])
    if src.exists():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
    db.execute(
        "UPDATE assets SET path=?, review_status='PENDING' WHERE id=?",
        (str(dst), row["asset_id"]),
    )