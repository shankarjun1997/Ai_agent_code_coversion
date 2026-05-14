"""SSE broker for STM agentic sessions.

SseBroker — per-session asyncio.Queue fanout for Server-Sent Events.
EventKind — canonical event type enum used by all stages and the coordinator.
"""
from __future__ import annotations

import asyncio
import json
from enum import Enum
from typing import Any, AsyncIterator, Dict, List, Optional


class EventKind(str, Enum):
    # Stage lifecycle
    stage_started = "stage_started"
    stage_ready = "stage_ready"
    stage_stale = "stage_stale"
    stage_failed = "stage_failed"

    # Artifact published by a stage
    artifact = "artifact"

    # Gate lifecycle
    gate_waiting = "gate_waiting"
    gate_decided = "gate_decided"

    # Session lifecycle
    session_started = "session_started"
    session_done = "session_done"
    session_failed = "session_failed"

    # Progress / heartbeat
    progress = "progress"
    stage_progress = "stage_progress"
    heartbeat = "heartbeat"


class SseEvent:
    """A single SSE event payload."""

    __slots__ = ("kind", "stage", "data", "session_id")

    def __init__(
        self,
        kind: EventKind,
        stage: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None,
    ) -> None:
        self.kind = kind
        self.stage = stage
        self.data = data or {}
        self.session_id = session_id

    def to_sse(self) -> str:
        """Encode as SSE wire format: ``data: <json>\\n\\n``."""
        payload = {
            "event": self.kind.value,
            "stage": self.stage,
            "data": self.data,
        }
        if self.session_id:
            payload["session_id"] = self.session_id
        return f"data: {json.dumps(payload)}\n\n"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event": self.kind.value,
            "stage": self.stage,
            "data": self.data,
            "session_id": self.session_id,
        }


class _Subscriber:
    """A single SSE subscriber holding its own asyncio.Queue."""

    def __init__(self, maxsize: int = 256) -> None:
        self.queue: asyncio.Queue[Optional[SseEvent]] = asyncio.Queue(maxsize=maxsize)

    def put_nowait(self, event: Optional[SseEvent]) -> None:
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            # Slow consumer: drop the oldest item then enqueue
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
            self.queue.put_nowait(event)

    async def __aiter__(self) -> AsyncIterator[SseEvent]:
        while True:
            item = await self.queue.get()
            if item is None:
                break
            yield item


class SseBroker:
    """Fan-out SSE broker keyed by session_id.

    Usage::

        broker = SseBroker()

        # Publisher side (coordinator):
        await broker.publish("sess-1", SseEvent(EventKind.stage_started, stage="L1"))

        # Subscriber side (HTTP handler):
        async for event in broker.subscribe("sess-1"):
            yield event.to_sse()
    """

    def __init__(self) -> None:
        self._sessions: Dict[str, List[_Subscriber]] = {}
        self._lock = asyncio.Lock()

    async def publish(self, session_id: str, event: SseEvent) -> None:
        """Publish *event* to all active subscribers for *session_id*."""
        async with self._lock:
            subs = list(self._sessions.get(session_id, []))
        for sub in subs:
            sub.put_nowait(event)

    async def subscribe(self, session_id: str) -> AsyncIterator[SseEvent]:
        """Async-generator that yields events for *session_id* until closed."""
        sub = _Subscriber()
        async with self._lock:
            self._sessions.setdefault(session_id, []).append(sub)
        try:
            async for event in sub:
                yield event
        finally:
            async with self._lock:
                subs = self._sessions.get(session_id, [])
                if sub in subs:
                    subs.remove(sub)
                if not subs:
                    self._sessions.pop(session_id, None)

    async def close(self, session_id: str) -> None:
        """Signal all subscribers for *session_id* to stop (send sentinel None)."""
        async with self._lock:
            subs = list(self._sessions.get(session_id, []))
        for sub in subs:
            sub.put_nowait(None)

    def subscriber_count(self, session_id: str) -> int:
        return len(self._sessions.get(session_id, []))


# Module-level default broker (singleton for the process).
_default_broker: Optional[SseBroker] = None


def get_broker() -> SseBroker:
    global _default_broker
    if _default_broker is None:
        _default_broker = SseBroker()
    return _default_broker


def reset_broker_for_tests() -> None:
    """Replace the module-level broker with a fresh one (test helper)."""
    global _default_broker
    _default_broker = SseBroker()
