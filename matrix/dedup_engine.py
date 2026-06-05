from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from matrix.config import PHASH_HAMMING_MAX
from matrix.db import Database
from matrix.hasher import hamming_distance


@dataclass
class GroupMember:
    asset_id: int
    path: str
    file_type: str
    size_bytes: int
    width: int | None
    height: int | None
    mtime: float
    is_master: bool
    confidence: float
    match_type: str


@dataclass
class DuplicateGroupMap:
    group_id: int
    group_type: str
    master_asset_id: int
    confidence: float
    members: list[GroupMember]

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_id": self.group_id,
            "group_type": self.group_type,
            "master_asset_id": self.master_asset_id,
            "confidence": self.confidence,
            "members": [asdict(m) for m in self.members],
        }


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pixel_count(row: Any) -> int:
    w, h = row["width"], row["height"]
    if w and h:
        return int(w) * int(h)
    return int(row["size_bytes"] or 0)


def _pick_master(rows: list[Any]) -> Any:
    return max(rows, key=lambda r: (_pixel_count(r), float(r["mtime"] or 0)))


def _confidence_visual(distance: int) -> float:
    if distance <= 0:
        return 0.99
    if distance >= PHASH_HAMMING_MAX:
        return 0.85
    span = max(PHASH_HAMMING_MAX, 1)
    return round(0.99 - (distance / span) * 0.14, 3)


def _is_derivative_pair(a: Any, b: Any) -> bool:
    if a["xmp_sidecar_path"] and b["path"] == a["xmp_sidecar_path"]:
        return True
    if b["xmp_sidecar_path"] and a["path"] == b["xmp_sidecar_path"]:
        return True
    # parent_id only marks XMP/sidecar derivatives, not film lineage
    if a["parent_id"] and int(b["id"]) == int(a["parent_id"]):
        if b["file_type"] == "OTHER" or a["xmp_sidecar_path"]:
            return True
    if b["parent_id"] and int(a["id"]) == int(b["parent_id"]):
        if a["file_type"] == "OTHER" or b["xmp_sidecar_path"]:
            return True
    return False


def _psd_tiff_raw_guard(a: Any, b: Any) -> bool:
    types = {a["file_type"], b["file_type"]}
    if "RAW" in types and types & {"PSD", "TIFF"}:
        if a["parent_id"] == b["id"] or b["parent_id"] == a["id"]:
            return True
    return False


def _union_find_clusters(n: int, should_link) -> dict[int, list[int]]:
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    for i in range(n):
        for j in range(i + 1, n):
            if should_link(i, j):
                union(i, j)

    clusters: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        clusters[find(i)].append(i)
    return clusters


def clear_group_types(db: Database, group_types: tuple[str, ...]) -> None:
    if not group_types:
        return
    placeholders = ",".join("?" * len(group_types))
    db.execute(
        f"""
        UPDATE assets SET duplicate_group_id = NULL, is_master = 0, confidence = NULL
        WHERE duplicate_group_id IN (
            SELECT id FROM duplicate_groups WHERE group_type IN ({placeholders})
        )
        """,
        group_types,
    )
    db.execute(
        f"DELETE FROM duplicate_groups WHERE group_type IN ({placeholders})",
        group_types,
    )


def _assign_group(
    db: Database,
    group_type: str,
    members: list[Any],
    default_confidence: float,
    review_status: str = "PENDING",
) -> int:
    master = _pick_master(members)
    cur = db.execute(
        "INSERT INTO duplicate_groups (group_type, master_asset_id, confidence) VALUES (?, ?, ?)",
        (group_type, master["id"], default_confidence),
    )
    gid = int(cur.lastrowid)
    now = _now()
    for m in members:
        conf = default_confidence
        if group_type == "VISUAL" and m["id"] != master["id"]:
            dists = [
                hamming_distance(m["phash"], o["phash"])
                for o in members
                if o["id"] != m["id"] and m["phash"] and o["phash"]
            ]
            conf = _confidence_visual(min(dists)) if dists else default_confidence
        db.execute(
            """
            UPDATE assets SET duplicate_group_id=?, confidence=?, is_master=?,
            review_status=?, updated_at=?
            WHERE id=?
            """,
            (
                gid,
                conf,
                1 if m["id"] == master["id"] else 0,
                review_status,
                now,
                m["id"],
            ),
        )
    return gid


def run_exact_dedup(db: Database) -> int:
    rows = db.fetchall(
        "SELECT * FROM assets WHERE sha256 IS NOT NULL AND sha256 != ''"
    )
    by_sha: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        by_sha[r["sha256"]].append(r)

    groups = 0
    for members in by_sha.values():
        if len(members) < 2:
            continue

        def should_link(i: int, j: int) -> bool:
            a, b = members[i], members[j]
            if _is_derivative_pair(a, b) or _psd_tiff_raw_guard(a, b):
                return False
            return True

        clusters = _union_find_clusters(len(members), should_link)
        for indices in clusters.values():
            if len(indices) < 2:
                continue
            cluster = [members[i] for i in indices]
            _assign_group(db, "EXACT", cluster, 1.0)
            groups += 1
    return groups


def _phash_bucket(phash: str, prefix_len: int = 6) -> str:
    """Bucket by hash prefix — O(n²) per bucket, not global (100k-safe)."""
    return phash[:prefix_len] if len(phash) >= prefix_len else phash


def run_visual_dedup(db: Database) -> int:
    rows = db.fetchall(
        """
        SELECT * FROM assets
        WHERE phash IS NOT NULL AND phash != ''
        AND duplicate_group_id IS NULL
        """
    )
    buckets: dict[str, list[Any]] = defaultdict(list)
    for r in rows:
        buckets[_phash_bucket(r["phash"])].append(r)

    groups = 0

    def should_link(i: int, j: int, members: list[Any]) -> bool:
        a, b = members[i], members[j]
        if _is_derivative_pair(a, b) or _psd_tiff_raw_guard(a, b):
            return False
        return hamming_distance(a["phash"], b["phash"]) <= PHASH_HAMMING_MAX

    for members in buckets.values():
        if len(members) < 2:
            continue
        clusters = _union_find_clusters(
            len(members),
            lambda i, j, m=members: should_link(i, j, m),
        )
        for indices in clusters.values():
            if len(indices) < 2:
                continue
            cluster = [members[i] for i in indices]
            _assign_group(db, "VISUAL", cluster, 0.85)
            groups += 1

    return groups


def mark_derivative_groups(db: Database) -> int:
    """XMP sidecar / explicit derivative children only — not film lineage."""
    clear_group_types(db, ("DERIVATIVE",))
    parents = db.fetchall(
        "SELECT * FROM assets WHERE xmp_sidecar_path IS NOT NULL AND xmp_sidecar_path != ''"
    )
    count = 0
    for parent in parents:
        children = db.fetchall(
            "SELECT * FROM assets WHERE parent_id = ?",
            (parent["id"],),
        )
        if not children:
            continue
        _assign_group(db, "DERIVATIVE", [parent, *children], 1.0, review_status="SKIPPED")
        count += 1
    return count


def build_group_maps(db: Database) -> list[DuplicateGroupMap]:
    groups = db.fetchall(
        "SELECT * FROM duplicate_groups WHERE group_type IN ('EXACT', 'VISUAL') ORDER BY id"
    )
    result: list[DuplicateGroupMap] = []
    for g in groups:
        members_rows = db.fetchall(
            "SELECT * FROM assets WHERE duplicate_group_id = ? ORDER BY is_master DESC",
            (g["id"],),
        )
        members = [
            GroupMember(
                asset_id=m["id"],
                path=m["path"],
                file_type=m["file_type"],
                size_bytes=m["size_bytes"],
                width=m["width"],
                height=m["height"],
                mtime=m["mtime"],
                is_master=bool(m["is_master"]),
                confidence=float(m["confidence"] or g["confidence"]),
                match_type=g["group_type"],
            )
            for m in members_rows
        ]
        result.append(
            DuplicateGroupMap(
                group_id=g["id"],
                group_type=g["group_type"],
                master_asset_id=g["master_asset_id"],
                confidence=float(g["confidence"]),
                members=members,
            )
        )
    return result


def export_group_map_json(db: Database, out_path: Path) -> Path:
    maps = build_group_maps(db)
    payload = {
        "generated_at": _now(),
        "schema_version": "1.0",
        "hamming_max": PHASH_HAMMING_MAX,
        "groups": [m.to_dict() for m in maps],
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return out_path


def run_dedup(db: Database) -> dict[str, int]:
    clear_group_types(db, ("EXACT", "VISUAL"))
    derivative = mark_derivative_groups(db)
    exact = run_exact_dedup(db)
    visual = run_visual_dedup(db)
    return {
        "derivative_groups": derivative,
        "exact_groups": exact,
        "visual_groups": visual,
    }