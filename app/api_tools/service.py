"""
Centralized ApiToolsService orchestrating all public API capabilities.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.api_tools.cache import ApiCache, get_api_cache
from app.api_tools.client import ApiClient
from app.api_tools.config import ApiToolsConfig
from app.api_tools.models import (
    ApiResponse,
    CryptoPrice,
    ForexRate,
    HolidayList,
    NetworkInfo,
    NewsFeed,
    StockQuote,
    WeatherInfo,
)
from app.api_tools.providers.crypto import CryptoProvider
from app.api_tools.providers.forex import ForexProvider
from app.api_tools.providers.holidays import HolidayProvider
from app.api_tools.providers.network import NetworkProvider
from app.api_tools.providers.news import NewsProvider
from app.api_tools.providers.stocks import StockProvider
from app.api_tools.providers.weather import WeatherProvider

logger = logging.getLogger(__name__)


class ApiToolsService:
    """Unified service interface for Victor's public data utilities."""

    def __init__(
        self,
        config: Optional[ApiToolsConfig] = None,
        cache: Optional[ApiCache] = None,
        client: Optional[ApiClient] = None,
    ) -> None:
        self.config = config or ApiToolsConfig()
        self.cache = cache or get_api_cache()
        self.client = client or ApiClient(self.config)

        # Initialize domain providers
        self.weather = WeatherProvider(self.config, self.client, self.cache)
        self.stocks = StockProvider(self.config, self.client, self.cache)
        self.forex = ForexProvider(self.config, self.client, self.cache)
        self.crypto = CryptoProvider(self.config, self.client, self.cache)
        self.news = NewsProvider(self.config, self.client, self.cache)
        self.network = NetworkProvider(self.config, self.client, self.cache)
        self.holidays = HolidayProvider(self.config, self.client, self.cache)

    async def get_weather(self, location: str, units: str = "celsius") -> ApiResponse[WeatherInfo]:
        """Fetch current weather and conditions for any location worldwide."""
        return await self.weather.get_weather(location, units=units)

    async def get_stock_price(self, ticker: str) -> ApiResponse[StockQuote]:
        """Fetch real-time stock price and market metrics for a ticker symbol."""
        return await self.stocks.get_quote(ticker)

    async def get_forex_rate(
        self,
        base_currency: str = "USD",
        target_currency: str = "INR",
        amount: float = 1.0,
    ) -> ApiResponse[ForexRate]:
        """Fetch foreign exchange rates and calculate currency conversion."""
        return await self.forex.get_rate(base_currency, target_currency, amount)

    async def get_crypto_price(
        self,
        symbol: str = "BTC",
        vs_currency: str = "USD",
    ) -> ApiResponse[CryptoPrice]:
        """Fetch real-time cryptocurrency price, 24h change, and volume."""
        return await self.crypto.get_price(symbol, vs_currency)

    async def get_news_headlines(
        self,
        category: str = "general",
        limit: int = 5,
    ) -> ApiResponse[NewsFeed]:
        """Fetch latest news headlines for a category or topic."""
        return await self.news.get_headlines(category, limit)

    async def get_network_info(self, ip_address: Optional[str] = None) -> ApiResponse[NetworkInfo]:
        """Fetch public IP address, ISP, and geographic network location."""
        return await self.network.get_network_info(ip_address)

    async def get_public_holidays(
        self,
        country: str = "US",
        year: Optional[int] = None,
    ) -> ApiResponse[HolidayList]:
        """Fetch official public and national holidays for a country."""
        return await self.holidays.get_holidays(country, year)

    async def close(self) -> None:
        """Close underlying HTTP client connections."""
        await self.client.close()


# Global singleton instance
_GLOBAL_SERVICE: Optional[ApiToolsService] = None


def get_api_tools_service() -> ApiToolsService:
    """Retrieve or initialize the global ApiToolsService instance."""
    global _GLOBAL_SERVICE
    if _GLOBAL_SERVICE is None:
        _GLOBAL_SERVICE = ApiToolsService()
    return _GLOBAL_SERVICE
