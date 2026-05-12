import asyncio
import time
import pytest
from core.discovery.cache import DiscoveryCache


@pytest.mark.asyncio
async def test_cache_hit_within_ttl():
    cache = DiscoveryCache(ttl_seconds=60)
    calls = {"n": 0}
    async def loader():
        calls["n"] += 1
        return "value"
    assert await cache.get_or_load("p1", "list_schemas", (), loader) == "value"
    assert await cache.get_or_load("p1", "list_schemas", (), loader) == "value"
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_cache_miss_after_ttl():
    cache = DiscoveryCache(ttl_seconds=0)
    calls = {"n": 0}
    async def loader():
        calls["n"] += 1
        return "v"
    await cache.get_or_load("p", "m", (), loader)
    time.sleep(0.01)
    await cache.get_or_load("p", "m", (), loader)
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_bypass_cache_forces_reload():
    cache = DiscoveryCache(ttl_seconds=60)
    calls = {"n": 0}
    async def loader():
        calls["n"] += 1
        return "v"
    await cache.get_or_load("p", "m", (), loader)
    await cache.get_or_load("p", "m", (), loader, bypass=True)
    assert calls["n"] == 2
