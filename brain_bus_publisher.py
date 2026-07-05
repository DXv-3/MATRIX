"""
brain_bus_publisher.py — MATRIX → the-brain live event wiring.

This module is the MATRIX-specific publish API. It wraps harmony_publisher_base
(the canonical shared transport) with MATRIX domain semantics: photo cataloguing,
deduplication, human review, and lineage events.

NOTE: PersonalStorageForge should NOT copy this file. Instead it should do:
    import sys; sys.path.insert(0, MATRIX_PATH)
    from brain_bus_publisher import publish_event  # or use matrix_adapter.py

Usage (unchanged from before — fully backwards-compatible):
    from brain_bus_publisher import publish_event, publish_dedup_event
    publish_event("photo_catalogued", detail="...", metadata={"path": "/foo.jpg"})
"""
from __future__ import annotations
import json
import uuid
from pathlib import Path

from _brain_client import get_client
from harmony_publisher_base import (
    HarmonyPublisher,
    publish_artifact_promoted,
    publish_kg_patch,
)

_SOURCE = "MATRIX"


def publish_event(
    event_type: str,
    category: str = "media",
    detail: str = "",
    outcome: str = "pass",
    run_id: str | None = None,
    metadata: dict | None = None,
) -> bool:
    """Publish a MATRIX pipeline event to brain.db (direct) + harmony bus."""
    rid = run_id or f"matrix_{uuid.uuid4().hex[:8]}"
    brain = get_client()
    detail_full = f"{detail} | meta={json.dumps(metadata)}" if metadata else detail

    # 1. Direct brain write (always — immediate, no bus dependency)
    ok = False
    if brain is not None:
        try:
            ok = brain.learn(
                run_id=rid, source=_SOURCE, category=category,
                event_type=event_type, detail=detail_full[:2000], outcome=outcome,
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
        except Exception as e:
            print(f"[MATRIX brain_bus] direct write error: {e}")

    # 2. Harmony bus publish (async transport — feeds harmony_subscriber in the-brain)
    #    Fire-and-forget: bus failure does NOT fail the pipeline step.
    if metadata and "path" in metadata:
        try:
            publish_artifact_promoted(
                artifact_name=metadata["path"],
                status=outcome if outcome in ("pass", "fail", "skip") else "indexed",
                trace_id=rid,
                notes=detail_full[:500],
                source=_SOURCE,
                run_id=rid,
            )
        except Exception as e:
            print(f"[MATRIX brain_bus] harmony publish error (non-fatal): {e}")

    return ok


def publish_dedup_event(original: str, duplicate: str, run_id: str | None = None) -> bool:
    """Deduplication event: writes direct + harmony bus."""
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
    # Harmony bus: emit kg_patch with the dedup edge
    try:
        publish_kg_patch(
            edges=[{"source_id": f"media:{duplicate}",
                    "target_id": f"media:{original}",
                    "relation": "duplicate_of",
                    "weight": 0.99}],
            source=_SOURCE,
            run_id=rid,
        )
    except Exception:
        pass
    return ok


def publish_human_review(path: str, decision: str, run_id: str | None = None) -> bool:
    """Log a human review decision."""
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
    # Harmony bus: kg_patch for the lineage edge
    if parent:
        try:
            publish_kg_patch(
                nodes=[
                    {"node_id": f"media:{asset}", "node_type": "media_asset", "label": asset},
                    {"node_id": f"media:{parent}", "node_type": "media_asset", "label": parent},
                ],
                edges=[{"source_id": f"media:{asset}",
                        "target_id": f"media:{parent}",
                        "relation": lineage_type,
                        "weight": 1.0}],
                source=_SOURCE,
                run_id=rid,
            )
        except Exception:
            pass
    return ok
