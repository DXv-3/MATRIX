from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from matrix.config import data_dir, quarantine_dir, scan_roots
from matrix.db import Database
from matrix.dedup_engine import build_group_maps, export_group_map_json, run_dedup
from matrix.lineage_resolver import run_lineage
from matrix.scanner import scan_directory
from matrix.security import PathValidationError, assert_asset_readable, resolve_directory


def row_to_dict(row: Any) -> dict[str, Any]:
    if row is None:
        return {}
    return dict(row)


def get_report(db: Database) -> dict[str, Any]:
    return {
        "catalog": str(db.path),
        "data_dir": str(data_dir()),
        "scan_roots": [str(p) for p in scan_roots()],
        "assets": db.fetchone("SELECT COUNT(*) AS c FROM assets")["c"],
        "duplicate_groups": db.fetchone("SELECT COUNT(*) AS c FROM duplicate_groups")["c"],
        "lineage_groups": db.fetchone("SELECT COUNT(*) AS c FROM lineage_groups")["c"],
        "pending_review": db.fetchone(
            """
            SELECT COUNT(*) AS c FROM assets
            WHERE review_status='PENDING' AND duplicate_group_id IS NOT NULL
            """
        )["c"],
        "quarantine_moves": db.fetchone("SELECT COUNT(*) AS c FROM quarantine_moves")["c"],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def list_assets(db: Database, limit: int = 100, offset: int = 0) -> dict[str, Any]:
    limit = max(1, min(limit, 500))
    offset = max(0, offset)
    rows = db.fetchall(
        """
        SELECT id, path, filename, file_type, sha256, phash, size_bytes,
               width, height, review_status, confidence, is_master,
               duplicate_group_id, lineage_group_id, roll_number, frame_number
        FROM assets ORDER BY updated_at DESC LIMIT ? OFFSET ?
        """,
        (limit, offset),
    )
    total = db.fetchone("SELECT COUNT(*) AS c FROM assets")["c"]
    return {"total": total, "items": [row_to_dict(r) for r in rows]}


def get_asset(db: Database, asset_id: int) -> dict[str, Any] | None:
    if asset_id < 1:
        return None
    row = db.fetchone("SELECT * FROM assets WHERE id=?", (asset_id,))
    return row_to_dict(row) if row else None


def list_pending_groups(db: Database) -> list[dict[str, Any]]:
    groups = db.fetchall(
        """
        SELECT dg.* FROM duplicate_groups dg
        WHERE dg.group_type IN ('EXACT', 'VISUAL')
        AND EXISTS (
            SELECT 1 FROM assets a
            WHERE a.duplicate_group_id = dg.id AND a.review_status = 'PENDING'
        )
        ORDER BY dg.id
        """
    )
    result = []
    for g in groups:
        members = db.fetchall(
            "SELECT * FROM assets WHERE duplicate_group_id=? ORDER BY is_master DESC",
            (g["id"],),
        )
        result.append(
            {
                "group": row_to_dict(g),
                "members": [row_to_dict(m) for m in members],
            }
        )
    return result


def list_lineage(db: Database, limit: int = 50) -> list[dict[str, Any]]:
    limit = max(1, min(limit, 200))
    groups = db.fetchall(
        "SELECT * FROM lineage_groups ORDER BY roll_number, frame_number LIMIT ?",
        (limit,),
    )
    out = []
    for lg in groups:
        assets = db.fetchall(
            """
            SELECT id, path, filename, file_type, lineage_role, parent_id
            FROM assets WHERE lineage_group_id=? ORDER BY lineage_role, id
            """,
            (lg["id"],),
        )
        out.append(
            {
                "lineage_group": row_to_dict(lg),
                "assets": [row_to_dict(a) for a in assets],
            }
        )
    return out


def run_scan(db: Database, root: Path, workers: int = 4) -> dict[str, Any]:
    workers = max(1, min(workers, 32))
    return scan_directory(db, root, workers=workers)


def run_scan_from_path(db: Database, root_str: str, workers: int = 4) -> dict[str, Any]:
    root = resolve_directory(root_str)
    return run_scan(db, root, workers=workers)


def run_dedup_pipeline(db: Database) -> dict[str, Any]:
    stats = run_dedup(db)
    stats.update(run_lineage(db))
    out = data_dir() / "group_map.json"
    export_group_map_json(db, out)
    stats["group_map"] = str(out)
    return stats


def run_full_pipeline(db: Database, root_str: str, workers: int = 4) -> dict[str, Any]:
    root = resolve_directory(root_str)
    scan_stats = run_scan(db, root, workers=workers)
    dedup_stats = run_dedup_pipeline(db)
    return {"scan": scan_stats, "dedup": dedup_stats, "report": get_report(db)}


def approve_group(
    db: Database,
    group_id: int,
    action: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    from matrix.quarantine_handler import move_to_quarantine

    if action not in ("KEEP_ALL", "DELETE_DUPLICATES", "SKIP", "MANUAL"):
        raise ValueError("invalid action")
    if group_id < 1:
        raise ValueError("invalid group_id")
    g = db.fetchone("SELECT id FROM duplicate_groups WHERE id=?", (group_id,))
    if not g:
        raise LookupError("group not found")

    cur = db.execute(
        "INSERT INTO review_decisions (duplicate_group_id, action, dry_run) VALUES (?, ?, ?)",
        (group_id, action, 1 if dry_run else 0),
    )
    decision_id = int(cur.lastrowid)
    now = datetime.now(timezone.utc).isoformat()

    if action == "DELETE_DUPLICATES":
        members = db.fetchall(
            "SELECT * FROM assets WHERE duplicate_group_id=? AND is_master=0",
            (group_id,),
        )
        moved = []
        for m in members:
            dest = move_to_quarantine(
                db,
                int(m["id"]),
                Path(m["path"]),
                dry_run=dry_run,
                review_decision_id=decision_id,
            )
            moved.append({"asset_id": m["id"], "quarantine": str(dest)})
        db.execute(
            "UPDATE assets SET review_status='APPROVED', updated_at=? WHERE duplicate_group_id=? AND is_master=1",
            (now, group_id),
        )
        return {"decision_id": decision_id, "action": action, "moved": moved}

    status = "APPROVED" if action == "KEEP_ALL" else ("SKIPPED" if action == "SKIP" else "PENDING")
    db.execute(
        "UPDATE assets SET review_status=?, updated_at=? WHERE duplicate_group_id=?",
        (status, now, group_id),
    )
    return {"decision_id": decision_id, "action": action, "status": status}


def get_groups_export(db: Database) -> dict[str, Any]:
    maps = build_group_maps(db)
    return {"count": len(maps), "groups": [m.to_dict() for m in maps]}


def asset_path_allowed(db: Database, asset_id: int) -> Path | None:
    if asset_id < 1:
        return None
    row = db.fetchone("SELECT path FROM assets WHERE id=?", (asset_id,))
    if not row:
        return None
    try:
        return assert_asset_readable(Path(row["path"]))
    except PathValidationError:
        return None