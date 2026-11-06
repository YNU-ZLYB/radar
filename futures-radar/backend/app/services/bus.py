"""进程内 SSE 事件总线（P0 不依赖 Redis）。"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue] = set()
        self._lock = asyncio.Lock()

    async def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        async with self._lock:
            self._subscribers.add(q)
        return q

    async def unsubscribe(self, q: asyncio.Queue) -> None:
        async with self._lock:
            self._subscribers.discard(q)

    async def publish(self, event: str, data: dict) -> None:
        payload = {
            "event": event,
            "ts": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass


bus = EventBus()


def sse_format(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
