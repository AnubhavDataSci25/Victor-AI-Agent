"""
In-memory TTL cache for Victor's Free Public API Tools.

Ensures short-lived, reliable caching of external API results to:
- Minimize external network calls and latency.
- Protect free endpoints from rate-limiting.
- Clearly track data freshness (age in seconds) to avoid stale data confusion.
- Strictly remain ephemeral in-memory without persistent disk writes.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, NamedTuple, Optional, Tuple


class CacheEntry(NamedTuple):
    data: Any
    created_at: float
    expires_at: float


class ApiCache:
    """Thread-safe, asynchronous in-memory TTL cache."""

    def __init__(self) -> None:
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._hits = 0
        self._misses = 0

    async def get(self, key: str) -> Tuple[Optional[Any], Optional[int]]:
        """
        Retrieve an item from cache.
        Returns: (data, age_in_seconds) if found and not expired, else (None, None).
        """
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                self._misses += 1
                return None, None

            now = time.monotonic()
            if now > entry.expires_at:
                # Expired
                del self._cache[key]
                self._misses += 1
                return None, None

            self._hits += 1
            age = int(now - entry.created_at)
            return entry.data, age

    async def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        """Store an item in the cache with the given TTL in seconds."""
        if ttl_seconds <= 0:
            return

        now = time.monotonic()
        expires_at = now + ttl_seconds
        async with self._lock:
            self._cache[key] = CacheEntry(
                data=value,
                created_at=now,
                expires_at=expires_at,
            )

    async def delete(self, key: str) -> None:
        """Remove a specific key from cache."""
        async with self._lock:
            self._cache.pop(key, None)

    async def clear(self) -> None:
        """Clear all entries from cache."""
        async with self._lock:
            self._cache.clear()

    async def get_stats(self) -> Dict[str, Any]:
        """Return cache performance statistics."""
        async with self._lock:
            # Purge expired items on stats check
            now = time.monotonic()
            keys_to_delete = [k for k, v in self._cache.items() if now > v.expires_at]
            for k in keys_to_delete:
                del self._cache[k]

            total = self._hits + self._misses
            hit_ratio = (self._hits / total) if total > 0 else 0.0
            return {
                "active_entries": len(self._cache),
                "hits": self._hits,
                "misses": self._misses,
                "hit_ratio": round(hit_ratio, 3),
            }


# Singleton cache instance
_GLOBAL_API_CACHE: Optional[ApiCache] = None


def get_api_cache() -> ApiCache:
    """Get or initialize the global ApiCache instance."""
    global _GLOBAL_API_CACHE
    if _GLOBAL_API_CACHE is None:
        _GLOBAL_API_CACHE = ApiCache()
    return _GLOBAL_API_CACHE
