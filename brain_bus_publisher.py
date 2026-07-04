"""brain_bus_publisher.py — MATRIX → the-brain live event wiring.

Usage:
    from brain_bus_publisher import publish_event, publish_dedup_event

    publish_event(
        event_type="photo_catalogued",
        category="media",
        detail=f"Catalogued {filename}, hash={sha256}",
        outcome="pass",
        metadata={"path": str(filepath), "size_mb": size_mb}
    )

Requires:
    Set BRAIN_SYNC_PATH env var to the directory containing brain_sync.py
    (usually the path to your local the-brain repo).
    Optionally set BRAIN_DB_PATH to override brain.db location.
"""
from __future__ import annotations
import json, uuid
from pathlib import Path
from _brain_client import get_client

_SOURCE = "MATRIX"

def publish_event(
    event_type: str,
    category: str = "media",
    detail: str = "",
    outcome: str = "pass",
    run_id: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Publish a MATRIX pipeline event to brain.db."""
    rid = run_id or f"matrix_{uuid.uuid4().hex[:8]}"
    brain = get_client()
    if brain is None:
        return False
    detail_full = f"{detail} | meta={json.dumps(metadata)}" if metadata else detail
    try:
        ok = brain.learn(
            run_id=rid, source=_SOURCE, category=category,
            event_type=event_type, detail=detail_full, outcome=outcome,
        )
        if category == "media" and metadata and "path" in metadata:
            brain.kg_add_node(
                node_id=f"media:{metadata['path']}",
                node_type="media_asset",
                label=Path(metadata["path"]).name,
                properties={"source": _SOURCE, "run_id": rid},
            )
            brain.kg_add_edge(
                source_id=_SOURCE,
                target_id=f"media:{metadata['path']}",
                relation="catalogued",
                weight=1.0,
            )
        return ok
    except Exception as e:
        print(f"[MATRIX brain_bus] error: {e}")
        return False

def publish_dedup_event(original: str, duplicate: str, run_id: str | None = None) -> bool:
    """Shortcut for deduplication events — writes a KG edge between the two assets."""
    rid = run_id or f"matrix_dedup_{uuid.uuid4().hex[:8]}"
    brain = get_client()
    ok = publish_event("photo_deduped", "dedup",
                       f"dedup: {duplicate} → {original}", "pass", rid)
    if brain and ok:
        try:
            brain.kg_add_edge(
                source_id=f"media:{duplicate}",
                target_id=f"media:{original}",
                relation="duplicate_of",
                weight=0.99,
            )
        except Exception:
            pass
    return ok

def publish_human_review(path: str, decision: str, run_id: str | None = None) -> bool:
    """Log a human review decision from the review stage."""
    return publish_event(
        "human_review", "review",
        detail=f"path={path} decision={decision}",
        outcome="pass", run_id=run_id,
        metadata={"path": path, "decision": decision},
    )

def publish_lineage_event(asset: str, lineage_type: str,
                          parent: str = "", run_id: str | None = None) -> bool:
    """Log a photo lineage/provenance event."""
    brain = get_client()
    rid = run_id or f"matrix_lin_{uuid.uuid4().hex[:8]}"
    ok = publish_event("lineage_recorded", "lineage",
                       detail=f"asset={asset} type={lineage_type} parent={parent}",
                       outcome="pass", run_id=rid)
    if brain and parent:
        try:
            brain.kg_add_edge(
                source_id=f"media:{asset}",
                target_id=f"media:{parent}",
                relation=lineage_type,
                weight=1.0,
            )
        except Exception:
            pass
    return ok
