"""
Unit tests for ApiCache (in-memory TTL cache).
"""

import asyncio
import pytest

from app.api_tools.cache import ApiCache


@pytest.mark.asyncio
async def test_cache_set_and_get():
    cache = ApiCache()
    await cache.set("test_key", {"price": 100}, ttl_seconds=5)

    data, age = await cache.get("test_key")
    assert data == {"price": 100}
    assert age is not None
    assert age >= 0


@pytest.mark.asyncio
async def test_cache_miss():
    cache = ApiCache()
    data, age = await cache.get("nonexistent_key")
    assert data is None
    assert age is None


@pytest.mark.asyncio
async def test_cache_expiration():
    cache = ApiCache()
    # TTL of 0 or negative should not be stored
    await cache.set("instant_key", "value", ttl_seconds=0)
    data, _ = await cache.get("instant_key")
    assert data is None

    # Test short TTL
    await cache.set("short_key", "value", ttl_seconds=1)
    data, _ = await cache.get("short_key")
    assert data == "value"

    await asyncio.sleep(1.1)
    expired_data, _ = await cache.get("short_key")
    assert expired_data is None


@pytest.mark.asyncio
async def test_cache_clear_and_stats():
    cache = ApiCache()
    await cache.set("k1", "v1", ttl_seconds=60)
    await cache.set("k2", "v2", ttl_seconds=60)

    # 2 hits
    await cache.get("k1")
    await cache.get("k2")
    # 1 miss
    await cache.get("k3")

    stats = await cache.get_stats()
    assert stats["active_entries"] == 2
    assert stats["hits"] == 2
    assert stats["misses"] == 1
    assert stats["hit_ratio"] == round(2 / 3, 3)

    await cache.clear()
    stats_after = await cache.get_stats()
    assert stats_after["active_entries"] == 0
