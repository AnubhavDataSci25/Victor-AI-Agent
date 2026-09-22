"""
Configuration models and defaults for Victor's Free Public API Tools.

Centralizes API endpoints, request timeouts, rate limits, and cache TTLs.
All optional API keys are strictly read from environment variables.
"""

from __future__ import annotations

import os
from pydantic import BaseModel, Field


class ApiToolsConfig(BaseModel):
    """Configuration for Free Public API Tools."""
    # General HTTP Client settings
    timeout_seconds: float = 8.0
    user_agent: str = "Victor-Agent/2.0 (+https://github.com/VictorAIAgent)"
    max_retries: int = 2

    # In-memory Cache TTLs (seconds)
    cache_ttl_weather: int = 600       # 10 minutes
    cache_ttl_stocks: int = 60         # 1 minute
    cache_ttl_forex: int = 300         # 5 minutes
    cache_ttl_crypto: int = 30         # 30 seconds
    cache_ttl_news: int = 300          # 5 minutes
    cache_ttl_network: int = 1800      # 30 minutes
    cache_ttl_holidays: int = 86400    # 24 hours

    # Public Endpoints
    weather_geo_url: str = "https://geocoding-api.open-meteo.com/v1/search"
    weather_forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    stocks_yahoo_chart_url: str = "https://query1.finance.yahoo.com/v8/finance/chart"
    forex_open_api_url: str = "https://open.er-api.com/v6/latest"
    forex_frankfurter_url: str = "https://api.frankfurter.dev/v1/latest"
    crypto_coingecko_url: str = "https://api.coingecko.com/api/v3/simple/price"
    crypto_binance_url: str = "https://api.binance.com/api/v3/ticker/24hr"
    news_google_rss_url: str = "https://news.google.com/rss"
    news_hackernews_url: str = "https://hacker-news.firebaseio.com/v0"
    network_ip_api_url: str = "http://ip-api.com/json"
    network_ipify_url: str = "https://api.ipify.org"
    holidays_nager_url: str = "https://date.nager.at/api/v3"

    # Optional provider keys (only used if provided by user; free providers work with empty strings)
    news_api_key: str = Field(default_factory=lambda: os.getenv("NEWS_API_KEY", ""))
    finnhub_api_key: str = Field(default_factory=lambda: os.getenv("FINNHUB_API_KEY", ""))
    alpha_vantage_key: str = Field(default_factory=lambda: os.getenv("ALPHA_VANTAGE_API_KEY", ""))
