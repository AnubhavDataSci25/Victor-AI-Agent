"""
Base provider abstraction for Victor's Free Public API Tools.
"""

from __future__ import annotations

from abc import ABC
import logging
from typing import Any, Optional, Tuple

from app.api_tools.cache import ApiCache, get_api_cache
from app.api_tools.client import ApiClient
from app.api_tools.config import ApiToolsConfig

logger = logging.getLogger(__name__)


class BaseApiProvider(ABC):
    """Abstract base class for all public API service providers."""

    name: str = "BaseProvider"

    def __init__(
        self,
        config: Optional[ApiToolsConfig] = None,
        client: Optional[ApiClient] = None,
        cache: Optional[ApiCache] = None,
    ) -> None:
        self.config = config or ApiToolsConfig()
        self.client = client or ApiClient(self.config)
        self.cache = cache or get_api_cache()

    async def get_cached(self, key: str) -> Tuple[Optional[Any], Optional[int]]:
        """Retrieve data and age from cache."""
        return await self.cache.get(key)

    async def set_cached(self, key: str, value: Any, ttl: int) -> None:
        """Store value into cache."""
        await self.cache.set(key, value, ttl)
