"""Tests for core/stm/locks.py — SessionLock abstraction."""
import asyncio

import pytest

from core.stm.locks import SessionLock, SessionLockRegistry, get_registry, reset_registry_for_tests


@pytest.fixture(autouse=True)
def fresh_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


@pytest.mark.asyncio
async def test_serialises_writers():
    """Two coroutines writing to the same session must not overlap."""
    registry = SessionLockRegistry()
    order = []

    async def writer(name: str):
        async with SessionLock(registry, "sess-1"):
            order.append(f"{name}:enter")
            await asyncio.sleep(0)
            order.append(f"{name}:exit")

    await asyncio.gather(writer("A"), writer("B"))
    # A fully completes before B enters (or vice-versa, but never interleaved)
    assert order.index("A:exit") < order.index("B:enter") or \
           order.index("B:exit") < order.index("A:enter")


@pytest.mark.asyncio
async def test_cross_session_concurrent():
    """Different sessions can run concurrently without blocking each other."""
    registry = SessionLockRegistry()
    entered: list[str] = []

    async def writer(sid: str):
        async with SessionLock(registry, sid):
            entered.append(sid)
            await asyncio.sleep(0.01)

    await asyncio.gather(writer("s1"), writer("s2"), writer("s3"))
    assert set(entered) == {"s1", "s2", "s3"}


@pytest.mark.asyncio
async def test_timeout_raises():
    """Acquiring a held lock with a short timeout raises TimeoutError."""
    registry = SessionLockRegistry()
    # Hold the lock in a background task
    lock_held = asyncio.Event()
    release_signal = asyncio.Event()

    async def holder():
        async with SessionLock(registry, "sess-timeout"):
            lock_held.set()
            await release_signal.wait()

    task = asyncio.create_task(holder())
    await lock_held.wait()

    with pytest.raises(asyncio.TimeoutError):
        await registry.acquire("sess-timeout", timeout=0.01)

    release_signal.set()
    await task


@pytest.mark.asyncio
async def test_module_registry_singleton():
    """get_registry() returns the same instance on repeated calls."""
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2


@pytest.mark.asyncio
async def test_reset_registry_for_tests():
    """reset_registry_for_tests() produces a fresh registry."""
    r1 = get_registry()
    reset_registry_for_tests()
    r2 = get_registry()
    assert r1 is not r2
