"""
tests/test_harmony_publisher_base.py — Tests for the shared harmony transport layer.
"""
from __future__ import annotations
import asyncio
import json
import sys
import types as _types
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

# Stub websockets before import
_ws_mod = _types.ModuleType("websockets")
sys.modules.setdefault("websockets", _ws_mod)

# Stub _brain_client
_bc_mod = _types.ModuleType("_brain_client")
_bc_mod.get_client = lambda: None
sys.modules.setdefault("_brain_client", _bc_mod)

from harmony_publisher_base import (
    HarmonyPublisher,
    build_event,
    publish_artifact_promoted,
    publish_kg_patch,
    sync_publish,
)


# ---------------------------------------------------------------------------
# build_event
# ---------------------------------------------------------------------------

def test_build_event_structure():
    e = build_event("artifact_promoted", "MATRIX", {"artifact_name": "foo.jpg"}, "run-1")
    assert e["event_type"] == "artifact_promoted"
    assert e["source"] == "MATRIX"
    assert e["run_id"] == "run-1"
    assert "ts" in e
    assert e["payload"]["artifact_name"] == "foo.jpg"


def test_build_event_auto_run_id():
    e = build_event("test", "PSF")
    assert e["run_id"].startswith("psf-")


# ---------------------------------------------------------------------------
# HarmonyPublisher.publish — success path
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_success():
    ws_mock = AsyncMock()
    ws_ctx = AsyncMock()
    ws_ctx.__aenter__ = AsyncMock(return_value=ws_mock)
    ws_ctx.__aexit__ = AsyncMock(return_value=False)

    import websockets
    with patch.object(websockets, "connect", return_value=ws_ctx):
        pub = HarmonyPublisher(source="TEST")
        ok = await pub.publish("test_event", {"x": 1})
    assert ok is True
    ws_mock.send.assert_awaited_once()
    sent = json.loads(ws_mock.send.call_args.args[0])
    assert sent["event_type"] == "test_event"
    assert sent["source"] == "TEST"


# ---------------------------------------------------------------------------
# Retry + fallback on connection refused
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_publish_falls_back_on_connection_error():
    fallback = MagicMock()
    fallback.learn.return_value = True

    import websockets
    with patch.object(websockets, "connect", side_effect=ConnectionRefusedError("no bus")):
        pub = HarmonyPublisher(source="TEST", fallback_brain_client=fallback)
        # Speed up retries
        import harmony_publisher_base as hpb
        with patch.object(hpb, "MAX_RETRIES", 1), patch.object(hpb, "_FALLBACK_ENABLED", True):
            ok = await pub.publish("test_event", {})
    assert ok is True
    fallback.learn.assert_called_once()
    assert fallback.learn.call_args.kwargs["category"] == "harmony_fallback"


# ---------------------------------------------------------------------------
# publish_artifact_promoted payload
# ---------------------------------------------------------------------------

def test_publish_artifact_promoted_payload(monkeypatch):
    captured = {}

    def fake_sync_publish(self, event_type, payload=None, run_id=None):
        captured["event_type"] = event_type
        captured["payload"] = payload
        return True

    monkeypatch.setattr(HarmonyPublisher, "sync_publish", fake_sync_publish)
    ok = publish_artifact_promoted("photo.jpg", status="indexed", trace_id="tr-1",
                                    source="MATRIX")
    assert ok is True
    assert captured["event_type"] == "artifact_promoted"
    assert captured["payload"]["artifact_name"] == "photo.jpg"
    assert captured["payload"]["promotion_status"] == "indexed"
    assert captured["payload"]["trace_id"] == "tr-1"


# ---------------------------------------------------------------------------
# publish_kg_patch payload
# ---------------------------------------------------------------------------

def test_publish_kg_patch_payload(monkeypatch):
    captured = {}

    def fake_sync_publish(self, event_type, payload=None, run_id=None):
        captured["event_type"] = event_type
        captured["payload"] = payload
        return True

    monkeypatch.setattr(HarmonyPublisher, "sync_publish", fake_sync_publish)
    ok = publish_kg_patch(
        nodes=[{"node_id": "n1", "node_type": "concept"}],
        edges=[{"source_id": "n1", "target_id": "n2", "relation": "linked"}],
        source="PSF",
    )
    assert ok is True
    assert captured["event_type"] == "kg_patch"
    assert len(captured["payload"]["nodes"]) == 1
    assert len(captured["payload"]["edges"]) == 1


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------

def test_auth_header_included(monkeypatch):
    monkeypatch.setenv("HARMONY_TOKEN", "secret-tok")
    pub = HarmonyPublisher(source="TEST")
    headers = pub._headers()
    assert headers["Authorization"] == "Bearer secret-tok"


def test_no_auth_header_when_no_token(monkeypatch):
    monkeypatch.delenv("HARMONY_TOKEN", raising=False)
    pub = HarmonyPublisher(source="TEST", token="")
    headers = pub._headers()
    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# sync_publish convenience wrapper
# ---------------------------------------------------------------------------

def test_sync_publish_calls_publish(monkeypatch):
    called = {}
    def fake_sync_publish(self, event_type, payload=None, run_id=None):
        called["event_type"] = event_type
        return True
    monkeypatch.setattr(HarmonyPublisher, "sync_publish", fake_sync_publish)
    ok = sync_publish("custom_event", {"a": 1}, source="TEST")
    assert ok is True
    assert called["event_type"] == "custom_event"
