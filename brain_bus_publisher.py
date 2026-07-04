"""brain_bus_publisher.py — MATRIX → the-brain live event wiring.

Drop this file in the MATRIX repo root.
Call publish_event() from any MATRIX pipeline stage to push events to brain.db
via the harmony-engine-protocol brain bus.

Usage:
    from brain_bus_publisher import publish_event

    publish_event(
        event_type="photo_catalogued",
        category="media",
        detail=f"Catalogued {filename}, hash={sha256}, dedup=False",
        outcome="pass",
        metadata={"path": str(filepath), "size_mb": size_mb}
    )
"""
from __future__ import annotations
import json, os, sys, uuid
from datetime import datetime, timezone
from pathlib import Path

_SOURCE = "MATRIX"
_REPO_ROOT = Path(__file__).resolve().parent

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _get_brain():
    candidates = [
        _REPO_ROOT.parent / "the-brain",
        Path.home() / "the-brain",
        Path.home() / "repos" / "the-brain",
    ]
    env_path = os.environ.get("BRAIN_REPO_PATH", "")
    if env_path:
        candidates.insert(0, Path(env_path))
    for c in candidates:
        if (c / "brain_sync.py").exists():
            if str(c) not in sys.path:
                sys.path.insert(0, str(c))
            try:
                from brain_sync import BrainSync  # type: ignore
                return BrainSync()
            except Exception as e:
                print(f"[MATRIX brain_bus] import error: {e}")
                return None
    print("[MATRIX brain_bus] WARNING: the-brain not found. Set BRAIN_REPO_PATH.")
    return None

_brain = None
_brain_resolved = False

def _client():
    global _brain, _brain_resolved
    if not _brain_resolved:
        _brain = _get_brain()
        _brain_resolved = True
    return _brain

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
    brain = _client()
    if brain is None:
        return False
    detail_full = detail
    if metadata:
        detail_full = f"{detail} | meta={json.dumps(metadata)}"
    try:
        ok = brain.learn(
            run_id=rid,
            source=_SOURCE,
            category=category,
            event_type=event_type,
            detail=detail_full,
            outcome=outcome,
        )
        if category == "media" and metadata and "path" in metadata:
            brain.kg_add_node(
                node_id=f"media:{metadata.get('path','unknown')}",
                node_type="media_asset",
                label=Path(metadata["path"]).name,
                properties={"source": _SOURCE, "run_id": rid},
            )
            brain.kg_add_edge(
                source_id=_SOURCE,
                target_id=f"media:{metadata.get('path','unknown')}",
                relation="catalogued",
                weight=1.0,
            )
        return ok
    except Exception as e:
        print(f"[MATRIX brain_bus] write error: {e}")
        return False

def publish_dedup_event(original: str, duplicate: str, run_id: str | None = None) -> bool:
    """Shortcut for deduplication events — writes a KG edge between the two assets."""
    rid = run_id or f"matrix_dedup_{uuid.uuid4().hex[:8]}"
    brain = _client()
    ok = publish_event("photo_deduped", "dedup", f"dedup: {duplicate} → {original}", "pass", rid)
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
