"""15-minute TTL in-memory cache for discovery results."""
from __future__ import annotations

import asyncio
import time
from typing import Any, Awaitable, Callable, Dict, Hashable, Tuple

_DEFAULT_TTL = 900  # 15 min; overridden by STM_METADATA_CACHE_TTL_SEC at runtime


class DiscoveryCache:
    def __init__(self, ttl_seconds: int = _DEFAULT_TTL):
        self.ttl = ttl_seconds
        self._store: Dict[Tuple[str, str, Tuple[Hashable, ...]], Tuple[float, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_or_load(
        self,
        profile_id: str,
        method: str,
        args: Tuple[Hashable, ...],
        loader: Callable[[], Awaitable[Any]],
        bypass: bool = False,
    ) -> Any:
        key = (profile_id, method, args)
        now = time.time()
        if not bypass:
            async with self._lock:
                hit = self._store.get(key)
            if hit is not None:
                ts, val = hit
                if now - ts <= self.ttl:
                    return val
        val = await loader()
        async with self._lock:
            self._store[key] = (now, val)
        return val

    def invalidate(self, profile_id: str | None = None) -> None:
        if profile_id is None:
            self._store.clear()
            return
        keys = [k for k in self._store if k[0] == profile_id]
        for k in keys:
            self._store.pop(k, None)


_default = DiscoveryCache()


def default_cache() -> DiscoveryCache:
    return _default
