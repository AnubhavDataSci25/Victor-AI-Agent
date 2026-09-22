"""
Data models and response structures for Victor's Free Public API Tools module.

Provides a normalized ApiResponse[T] envelope alongside strongly-typed
domain models for Weather, Stocks, Forex, Crypto, News, Network, and Holidays.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Generic, List, Optional, TypeVar
from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """Unified response envelope returned by all Public API providers."""
    success: bool = True
    data: Optional[T] = None
    error: Optional[str] = None
    source: str = "Victor Public API"
    timestamp_utc: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    )
    cached: bool = False
    cache_age_seconds: Optional[int] = None
    summary: str = ""

    def formatted_summary(self) -> str:
        """Return a user-friendly concise summary with metadata."""
        if not self.success:
            return f"Error ({self.source}): {self.error or 'Operation failed'}"

        cache_badge = f" [Cached {self.cache_age_seconds}s ago]" if self.cached and self.cache_age_seconds else " [Live]"
        attribution = f"\nSource: {self.source}{cache_badge} | {self.timestamp_utc}"
        return f"{self.summary}{attribution}"


class WeatherInfo(BaseModel):
    """Normalized weather report."""
    location: str
    country: str = ""
    latitude: float
    longitude: float
    temperature_c: float
    temperature_f: float
    apparent_temperature_c: float
    apparent_temperature_f: float
    relative_humidity: int
    precipitation_mm: float
    wind_speed_kmh: float
    weather_condition: str
    weather_code: int
    observation_time: str


class StockQuote(BaseModel):
    """Normalized real-time stock quote."""
    ticker: str
    company_name: str = ""
    currency: str = "USD"
    price: float
    previous_close: Optional[float] = None
    change: Optional[float] = None
    change_percent: Optional[float] = None
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    volume: Optional[int] = None
    exchange: str = ""
    market_state: str = "REGULAR"


class ForexRate(BaseModel):
    """Normalized foreign exchange rate / currency conversion."""
    base_currency: str
    target_currency: str
    rate: float
    amount: float = 1.0
    converted_amount: float
    last_updated_utc: str = ""


class CryptoPrice(BaseModel):
    """Normalized cryptocurrency price and 24h market stats."""
    symbol: str
    name: str
    price_usd: float
    price_inr: Optional[float] = None
    price_target: Optional[float] = None
    target_currency: str = "USD"
    change_24h_percent: Optional[float] = None
    high_24h: Optional[float] = None
    low_24h: Optional[float] = None
    volume_24h: Optional[float] = None
    last_updated_utc: str = ""


class NewsItem(BaseModel):
    """Normalized headline item."""
    title: str
    source_name: str = ""
    url: str = ""
    published_at: str = ""
    snippet: str = ""


class NewsFeed(BaseModel):
    """Collection of news headlines."""
    category: str
    items: List[NewsItem] = Field(default_factory=list)


class NetworkInfo(BaseModel):
    """Normalized public network and IP geolocation information."""
    public_ip: str
    city: str = ""
    region: str = ""
    country: str = ""
    country_code: str = ""
    postal_code: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    timezone: str = ""
    isp: str = ""
    organization: str = ""


class HolidayItem(BaseModel):
    """Public / National Holiday entry."""
    date: str
    name: str
    local_name: str = ""
    country_code: str
    is_global: bool = True
    types: List[str] = Field(default_factory=list)


class HolidayList(BaseModel):
    """Collection of holidays for a country/year."""
    country_code: str
    year: int
    holidays: List[HolidayItem] = Field(default_factory=list)
