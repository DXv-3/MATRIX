from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from matrix.db import Database
from matrix.dedup_engine import clear_group_types

PATTERNS = [
    re.compile(r"(?i)roll[_\-\s]?(\d+)[_\-\s]+frame[_\-\s]?(\d+)"),
    re.compile(r"(?i)r(\d+)[_\-\s]+f(\d+)"),
    re.compile(
        r"(?i)(\d{1,3})[_\-](\d{1,3})_(?:lab|scan|nlp|export|instagram|fuji)"
    ),
]

ROLE_KEYWORDS: list[tuple[str, str]] = [
    ("negative", "NEGATIVE"),
    ("lab", "LAB_SCAN"),
    ("fujiscan", "CAMERA_SCAN"),
    ("scan", "CAMERA_SCAN"),
    ("nlp", "DNG"),
    (".dng", "DNG"),
    ("instagram", "EXPORT"),
    ("export", "EXPORT"),
    ("web", "EXPORT"),
]


def parse_roll_frame(filename: str) -> tuple[str | None, str | None]:
    stem = Path(filename).stem
    for pat in PATTERNS:
        m = pat.search(stem)
        if m:
            return m.group(1), m.group(2)
    return None, None


def infer_lineage_role(filename: str, file_type: str) -> str:
    low = filename.lower()
    for key, role in ROLE_KEYWORDS:
        if key in low:
            return role
    if file_type == "RAW":
        return "NEGATIVE"
    if file_type == "DNG":
        return "DNG"
    if file_type in ("TIFF", "JPEG", "HEIC"):
        return "EXPORT"
    return "OTHER"


def infer_lab_scanner(filename: str) -> tuple[str | None, str | None]:
    low = filename.lower()
    lab = "Lab" if "lab" in low else None
    scanner = None
    for name in ("fuji", "noritsu", "frontier", "imacon", "epson"):
        if name in low:
            scanner = name.title()
    return lab, scanner


def run_lineage(db: Database) -> dict[str, int]:
    clear_group_types(db, ("LINEAGE",))
    # Clear stale parent_id from older runs (lineage no longer uses parent_id)
    db.execute(
        """
        UPDATE assets SET parent_id = NULL
        WHERE parent_id IS NOT NULL
        AND (xmp_sidecar_path IS NULL OR xmp_sidecar_path = '')
        AND file_type != 'OTHER'
        """
    )
    rows = db.fetchall("SELECT id, filename, file_type, path FROM assets")
    buckets: dict[tuple[str, str], list] = defaultdict(list)

    for r in rows:
        roll, frame = parse_roll_frame(r["filename"])
        if roll and frame:
            buckets[(roll, frame)].append(r)

    groups = 0
    linked = 0
    now = datetime.now(timezone.utc).isoformat()
    role_order = {
        "NEGATIVE": 0,
        "LAB_SCAN": 1,
        "CAMERA_SCAN": 2,
        "DNG": 3,
        "EXPORT": 4,
        "OTHER": 5,
    }

    for (roll, frame), members in buckets.items():
        existing = db.fetchone(
            "SELECT id FROM lineage_groups WHERE roll_number=? AND frame_number=?",
            (roll, frame),
        )
        if existing:
            lg_id = int(existing["id"])
        else:
            cur = db.execute(
                "INSERT INTO lineage_groups (roll_number, frame_number) VALUES (?, ?)",
                (roll, frame),
            )
            lg_id = int(cur.lastrowid)
            groups += 1

        sorted_members = sorted(
            members,
            key=lambda m: role_order.get(
                infer_lineage_role(m["filename"], m["file_type"]), 99
            ),
        )
        for m in sorted_members:
            role = infer_lineage_role(m["filename"], m["file_type"])
            lab, scanner = infer_lab_scanner(m["filename"])
            # parent_id is reserved for XMP/derivative links only (not film lineage)
            db.execute(
                """
                UPDATE assets SET lineage_group_id=?,
                roll_number=?, frame_number=?, lab=?, scanner=?, lineage_role=?,
                updated_at=?
                WHERE id=?
                """,
                (
                    lg_id,
                    roll,
                    frame,
                    lab,
                    scanner,
                    role,
                    now,
                    m["id"],
                ),
            )
            linked += 1

        master_id = sorted_members[-1]["id"] if sorted_members else None
        cur = db.execute(
            "INSERT INTO duplicate_groups (group_type, master_asset_id, confidence) VALUES (?, ?, ?)",
            ("LINEAGE", master_id, 1.0),
        )
        gid = int(cur.lastrowid)
        for m in sorted_members:
            db.execute(
                "UPDATE assets SET duplicate_group_id=? WHERE id=?",
                (gid, m["id"]),
            )

    return {"lineage_groups": groups, "assets_linked": linked}