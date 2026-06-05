from __future__ import annotations

import asyncio
import json
import threading
from collections import deque
from datetime import datetime, timezone
from typing import Any


class EventBus:
    """Thread-safe in-process event bus for SSE clients."""

    def __init__(self, maxlen: int = 200) -> None:
        self._history: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._subscribers: list[asyncio.Queue[dict[str, Any]]] = []
        self._lock = threading.Lock()

    def publish(self, event_type: str, payload: dict[str, Any] | None = None) -> None:
        msg = {
            "type": event_type,
            "payload": payload or {},
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._history.append(msg)
            subscribers = list(self._subscribers)

        for q in subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                pass

    def history(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._history)[-limit:]

    async def subscribe(self) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=50)
        with self._lock:
            self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[dict[str, Any]]) -> None:
        with self._lock:
            if q in self._subscribers:
                self._subscribers.remove(q)

    async def sse_stream(self):
        q = await self.subscribe()
        try:
            for item in self.history(20):
                yield f"data: {json.dumps(item)}\n\n"
            while True:
                item = await q.get()
                yield f"data: {json.dumps(item)}\n\n"
        finally:
            self.unsubscribe(q)


bus = EventBus()