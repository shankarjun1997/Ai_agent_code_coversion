"""Tests for core/stm/events.py — SseBroker + EventKind."""
import asyncio
import json

import pytest

from core.stm.events import (
    EventKind, SseEvent, SseBroker,
    get_broker, reset_broker_for_tests,
)


@pytest.fixture(autouse=True)
def fresh_broker():
    reset_broker_for_tests()
    yield
    reset_broker_for_tests()


# ── EventKind ─────────────────────────────────────────────────────────────────

def test_event_kind_values():
    assert EventKind.stage_started == "stage_started"
    assert EventKind.gate_decided == "gate_decided"
    assert EventKind.session_done == "session_done"


def test_sse_event_to_sse_wire():
    ev = SseEvent(EventKind.stage_ready, stage="L1", data={"x": 1}, session_id="s1")
    wire = ev.to_sse()
    assert wire.startswith("data: ")
    assert wire.endswith("\n\n")
    payload = json.loads(wire[len("data: "):].strip())
    assert payload["event"] == "stage_ready"
    assert payload["stage"] == "L1"
    assert payload["data"] == {"x": 1}
    assert payload["session_id"] == "s1"


def test_sse_event_to_dict():
    ev = SseEvent(EventKind.heartbeat)
    d = ev.to_dict()
    assert d["event"] == "heartbeat"
    assert d["stage"] is None


# ── SseBroker basic fanout ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_single_subscriber_receives_event():
    broker = SseBroker()
    received = []

    async def reader():
        async for ev in broker.subscribe("s1"):
            received.append(ev.kind)

    task = asyncio.create_task(reader())
    await asyncio.sleep(0)  # let reader attach

    ev = SseEvent(EventKind.stage_started, stage="L1")
    await broker.publish("s1", ev)
    await broker.close("s1")
    await task

    assert received == [EventKind.stage_started]


@pytest.mark.asyncio
async def test_fanout_to_multiple_subscribers():
    broker = SseBroker()
    results: dict[str, list] = {"a": [], "b": []}

    async def reader(key: str):
        async for ev in broker.subscribe("sess"):
            results[key].append(ev.kind)

    t1 = asyncio.create_task(reader("a"))
    t2 = asyncio.create_task(reader("b"))
    await asyncio.sleep(0)

    await broker.publish("sess", SseEvent(EventKind.progress))
    await broker.publish("sess", SseEvent(EventKind.stage_ready, stage="L2"))
    await broker.close("sess")
    await asyncio.gather(t1, t2)

    assert results["a"] == [EventKind.progress, EventKind.stage_ready]
    assert results["b"] == [EventKind.progress, EventKind.stage_ready]


@pytest.mark.asyncio
async def test_cross_session_isolation():
    broker = SseBroker()
    received_s1 = []
    received_s2 = []

    async def reader(sid: str, out: list):
        async for ev in broker.subscribe(sid):
            out.append(ev.kind)

    t1 = asyncio.create_task(reader("s1", received_s1))
    t2 = asyncio.create_task(reader("s2", received_s2))
    await asyncio.sleep(0)

    await broker.publish("s1", SseEvent(EventKind.stage_started))
    await broker.close("s1")
    await broker.close("s2")
    await asyncio.gather(t1, t2)

    assert received_s1 == [EventKind.stage_started]
    assert received_s2 == []


@pytest.mark.asyncio
async def test_subscriber_count():
    broker = SseBroker()

    async def reader():
        async for _ in broker.subscribe("sess"):
            break

    t = asyncio.create_task(reader())
    await asyncio.sleep(0)
    assert broker.subscriber_count("sess") == 1

    await broker.close("sess")
    await t
    assert broker.subscriber_count("sess") == 0


@pytest.mark.asyncio
async def test_module_singleton():
    b1 = get_broker()
    b2 = get_broker()
    assert b1 is b2


@pytest.mark.asyncio
async def test_reset_broker_for_tests():
    b1 = get_broker()
    reset_broker_for_tests()
    b2 = get_broker()
    assert b1 is not b2
