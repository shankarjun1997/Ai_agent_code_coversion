"""Per-session asyncio lock registry.

Provides a SessionLock abstraction that serialises concurrent writes to the
same STM session while allowing different sessions to run in parallel.

v1 assumption: single-worker uvicorn.  Multi-worker upgrade path: replace
_registry with DB advisory locks (documented non-goal for this iteration).
"""
from __future__ import annotations

import asyncio
from typing import Dict, Optional


class SessionLockRegistry:
    """Registry of per-session asyncio.Lock instances."""

    def __init__(self) -> None:
        self._registry: Dict[str, asyncio.Lock] = {}
        self._meta_lock = asyncio.Lock()

    async def acquire(self, session_id: str, timeout: Optional[float] = None) -> None:
        """Acquire the lock for *session_id*.

        Raises asyncio.TimeoutError if *timeout* seconds elapse before the
        lock becomes available.
        """
        lock = await self._get_or_create(session_id)
        if timeout is not None:
            acquired = await asyncio.wait_for(lock.acquire(), timeout=timeout)  # noqa: F841
        else:
            await lock.acquire()

    async def release(self, session_id: str) -> None:
        """Release the lock for *session_id*."""
        lock = self._registry.get(session_id)
        if lock is not None and lock.locked():
            lock.release()

    async def _get_or_create(self, session_id: str) -> asyncio.Lock:
        async with self._meta_lock:
            if session_id not in self._registry:
                self._registry[session_id] = asyncio.Lock()
            return self._registry[session_id]

    def __contains__(self, session_id: str) -> bool:
        return session_id in self._registry


class SessionLock:
    """Async context manager for a single session lock."""

    def __init__(
        self,
        registry: SessionLockRegistry,
        session_id: str,
        timeout: Optional[float] = None,
    ) -> None:
        self._registry = registry
        self._session_id = session_id
        self._timeout = timeout

    async def __aenter__(self) -> "SessionLock":
        await self._registry.acquire(self._session_id, timeout=self._timeout)
        return self

    async def __aexit__(self, *_) -> None:
        await self._registry.release(self._session_id)


# Module-level default registry (singleton for the process).
_default_registry: Optional[SessionLockRegistry] = None


def get_registry() -> SessionLockRegistry:
    global _default_registry
    if _default_registry is None:
        _default_registry = SessionLockRegistry()
    return _default_registry


def reset_registry_for_tests() -> None:
    """Replace the module-level registry with a fresh one (test helper)."""
    global _default_registry
    _default_registry = SessionLockRegistry()
