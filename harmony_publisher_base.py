"""
harmony_publisher_base.py — Canonical shared harmony bus transport layer.

This is the authoritative publish-side implementation for the harmony-engine-protocol
message bus. Both MATRIX and PersonalStorageForge import from this module —
it is the single source of truth for event envelope construction and WebSocket
transport. Neither repo duplicates this logic.

Architecture:
  MATRIX/PSF pipeline code
       ↓
  HarmonyPublisher (this file)  — builds HarmonyEvent envelopes, manages WS
       ↓
  harmony-engine-protocol (ws://localhost:9002/harmony)
       ↓
  harmony_subscriber.py in the-brain  — routes events into brain.db

Event types emitted by this module:
  artifact_promoted   — file/asset indexed, deduped, promoted, or reviewed
  kg_patch            — bulk node+edge upsert into the knowledge graph
  custom              — arbitrary event_type passed by caller

Fallback behaviour:
  If the harmony bus is unreachable, events fall back to a direct brain_client
  write (learning_memory row) so nothing is lost. Set HARMONY_FALLBACK=0 to
  disable the fallback (strict mode).

Environment variables:
  HARMONY_WS_URL      ws://localhost:9002/harmony (default)
  HARMONY_TOKEN       Bearer token (optional)
  HARMONY_FALLBACK    1 = fall back to brain_client on bus failure (default)
  MATRIX_PATH         Path to MATRIX repo root (for PersonalStorageForge to import)

Usage:
  # Simple
  from harmony_publisher_base import sync_publish, publish_artifact_promoted
  publish_artifact_promoted("photo.jpg", status="indexed", trace_id="run-abc")

  # Full control
  from harmony_publisher_base import HarmonyPublisher
  pub = HarmonyPublisher(source="MATRIX")
  pub.sync_publish(event_type="photo_catalogued", payload={"path": "/foo/bar.jpg"})
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

DEFAULT_URL = os.environ.get("HARMONY_WS_URL", "ws://localhost:9002/harmony")
_FALLBACK_ENABLED = os.environ.get("HARMONY_FALLBACK", "1") != "0"
MAX_RETRIES = 3
INITIAL_RETRY_DELAY = 0.5


# ---------------------------------------------------------------------------
# Event envelope builder
# ---------------------------------------------------------------------------

def build_event(
    event_type: str,
    source: str,
    payload: dict[str, Any] | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    """
    Build a HarmonyEvent envelope conforming to HARMONY_EVENT_SCHEMA.
    All events published to the harmony bus must use this envelope.
    """
    return {
        "event_type": event_type,
        "source": source,
        "ts": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id or f"{source.lower().replace(' ', '-')}-{uuid.uuid4().hex[:8]}",
        "payload": payload or {},
    }


# ---------------------------------------------------------------------------
# Harmony bus publisher
# ---------------------------------------------------------------------------

class HarmonyPublisher:
    """
    Async WebSocket publisher for the harmony-engine-protocol bus.

    Instantiate once per component and reuse. Maintains no persistent
    connection — each publish() opens, sends, and closes. This keeps
    the pipeline simple; long-lived connections belong in subscribers.
    """

    def __init__(
        self,
        source: str,
        url: str = DEFAULT_URL,
        token: str = "",
        fallback_brain_client: Any | None = None,
    ):
        self.source = source
        self._url = url
        self._token = token or os.environ.get("HARMONY_TOKEN", "")
        self._fallback = fallback_brain_client  # BrainSync instance or compatible
        self._available = True  # flipped to False after repeated failures

    def _headers(self) -> dict:
        h = {"User-Agent": f"harmony-publisher/{self.source}"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    async def publish(self, event_type: str, payload: dict | None = None,
                      run_id: str | None = None) -> bool:
        """
        Publish one event to the harmony bus.
        Returns True on success, False on failure (after fallback attempt).
        """
        try:
            import websockets
        except ImportError:
            log.warning("[harmony_publisher] websockets not installed — falling back to brain_client")
            return self._fallback_write(event_type, payload or {}, run_id)

        envelope = build_event(event_type, self.source, payload, run_id)
        msg = json.dumps(envelope)

        delay = INITIAL_RETRY_DELAY
        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            try:
                async with websockets.connect(
                    self._url,
                    additional_headers=self._headers(),
                    open_timeout=3,
                    close_timeout=2,
                ) as ws:
                    await ws.send(msg)
                    log.debug("[harmony_publisher] Published %s from %s (attempt %d)",
                               event_type, self.source, attempt + 1)
                    self._available = True
                    return True
            except (OSError, ConnectionRefusedError, Exception) as exc:
                last_exc = exc
                log.debug("[harmony_publisher] Attempt %d failed: %s", attempt + 1, exc)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(delay)
                    delay = min(delay * 2, 8.0)

        log.warning("[harmony_publisher] Harmony bus unreachable after %d attempts: %s",
                     MAX_RETRIES, last_exc)
        self._available = False

        if _FALLBACK_ENABLED:
            return self._fallback_write(event_type, payload or {}, run_id)
        return False

    def _fallback_write(self, event_type: str, payload: dict, run_id: str | None) -> bool:
        """Write to brain_client directly when harmony bus is unavailable."""
        if self._fallback is None:
            # Try to lazily acquire a brain client
            try:
                import sys
                sys.path.insert(0, str(Path(__file__).parent))
                from _brain_client import get_client
                self._fallback = get_client()
            except Exception:
                pass

        if self._fallback is None:
            log.warning("[harmony_publisher] No fallback brain_client available — event lost: %s",
                         event_type)
            return False

        try:
            rid = run_id or f"{self.source}-{uuid.uuid4().hex[:8]}"
            return self._fallback.learn(
                run_id=rid,
                source=self.source,
                category="harmony_fallback",
                event_type=event_type,
                detail=json.dumps(payload)[:2000],
                outcome="fallback",
            )
        except Exception as exc:
            log.error("[harmony_publisher] Fallback write failed: %s", exc)
            return False

    def sync_publish(self, event_type: str, payload: dict | None = None,
                     run_id: str | None = None) -> bool:
        """
        Synchronous wrapper for use in non-async pipeline code.
        Runs publish() in a new event loop if none is running,
        or schedules it as a task if an event loop is already running.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside an async context — fire-and-forget as a task
                asyncio.ensure_future(self.publish(event_type, payload, run_id))
                return True  # optimistic; task runs after current frame
            else:
                return loop.run_until_complete(self.publish(event_type, payload, run_id))
        except RuntimeError:
            # No event loop at all — create one
            return asyncio.run(self.publish(event_type, payload, run_id))


# ---------------------------------------------------------------------------
# Domain shortcuts — shared by MATRIX and PSF
# ---------------------------------------------------------------------------

def publish_artifact_promoted(
    artifact_name: str,
    status: str = "indexed",
    trace_id: str = "",
    notes: str = "",
    source: str = "MATRIX",
    metadata: dict | None = None,
    run_id: str | None = None,
) -> bool:
    """
    Emit an artifact_promoted event.
    harmony_subscriber.py will write this into brain.db artifacts table.

    Args:
        artifact_name:  canonical file/asset identifier (path, hash, or name)
        status:         'indexed' | 'promoted' | 'deduped' | 'reviewed' | 'rejected'
        trace_id:       run or pipeline ID for lineage tracing
        notes:          human-readable notes for the artifacts.notes column
        source:         emitting component name (default: 'MATRIX')
        metadata:       arbitrary extra data (stored in notes as JSON if provided)
        run_id:         explicit run ID (auto-generated if omitted)
    """
    pub = HarmonyPublisher(source=source)
    payload: dict[str, Any] = {
        "artifact_name": artifact_name,
        "promotion_status": status,
        "trace_id": trace_id or run_id or "",
        "notes": notes or (json.dumps(metadata) if metadata else ""),
    }
    return pub.sync_publish("artifact_promoted", payload, run_id)


def publish_kg_patch(
    nodes: list[dict] | None = None,
    edges: list[dict] | None = None,
    source: str = "MATRIX",
    run_id: str | None = None,
) -> bool:
    """
    Emit a kg_patch event to bulk-upsert nodes and edges into the brain KG.

    Node dict format:  {"node_id": str, "node_type": str, "label": str, "properties": dict}
    Edge dict format:  {"source_id": str, "target_id": str, "relation": str, "weight": float}
    """
    pub = HarmonyPublisher(source=source)
    payload = {"nodes": nodes or [], "edges": edges or []}
    return pub.sync_publish("kg_patch", payload, run_id)


def sync_publish(
    event_type: str,
    payload: dict | None = None,
    source: str = "MATRIX",
    run_id: str | None = None,
) -> bool:
    """Convenience wrapper: create a publisher and sync_publish in one call."""
    pub = HarmonyPublisher(source=source)
    return pub.sync_publish(event_type, payload, run_id)
