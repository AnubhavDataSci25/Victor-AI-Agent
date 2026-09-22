"""
Unit tests for all 7 Public API providers with mocked HTTP endpoints.
"""

from unittest.mock import AsyncMock, patch
import pytest

from app.api_tools.cache import ApiCache
from app.api_tools.client import ApiClient
from app.api_tools.config import ApiToolsConfig
from app.api_tools.providers.crypto import CryptoProvider
from app.api_tools.providers.forex import ForexProvider
from app.api_tools.providers.holidays import HolidayProvider
from app.api_tools.providers.network import NetworkProvider
from app.api_tools.providers.news import NewsProvider
from app.api_tools.providers.stocks import StockProvider
from app.api_tools.providers.weather import WeatherProvider


@pytest.fixture
def test_setup():
    config = ApiToolsConfig(timeout_seconds=2.0)
    client = ApiClient(config)
    cache = ApiCache()
    return config, client, cache


# --- 1. Weather Provider Tests ---
@pytest.mark.asyncio
async def test_weather_provider_success(test_setup):
    config, client, cache = test_setup
    provider = WeatherProvider(config, client, cache)

    mock_geo = {
        "results": [
            {"name": "London", "country": "United Kingdom", "latitude": 51.5085, "longitude": -0.1257}
        ]
    }
    mock_forecast = {
        "current": {
            "time": "2026-09-22T12:00",
            "temperature_2m": 21.5,
            "apparent_temperature": 21.0,
            "relative_humidity_2m": 60,
            "precipitation": 0.0,
            "wind_speed_10m": 12.0,
            "weather_code": 1,
        }
    }

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        mock_get_json.side_effect = [mock_geo, mock_forecast]

        resp = await provider.get_weather("London")
        assert resp.success is True
        assert resp.data is not None
        assert resp.data.location == "London"
        assert resp.data.temperature_c == 21.5
        assert resp.data.temperature_f == 70.7
        assert "Mainly clear" in resp.data.weather_condition
        assert "Weather in London, United Kingdom:" in resp.summary

        # Verify cached call
        cached_resp = await provider.get_weather("London")
        assert cached_resp.success is True
        assert cached_resp.cached is True


@pytest.mark.asyncio
async def test_weather_provider_invalid_location(test_setup):
    config, client, cache = test_setup
    provider = WeatherProvider(config, client, cache)

    resp = await provider.get_weather("")
    assert resp.success is False
    assert "Invalid location" in (resp.error or "")


# --- 2. Stock Provider Tests ---
@pytest.mark.asyncio
async def test_stock_provider_success(test_setup):
    config, client, cache = test_setup
    provider = StockProvider(config, client, cache)

    mock_yahoo = {
        "chart": {
            "result": [
                {
                    "meta": {
                        "currency": "USD",
                        "symbol": "AAPL",
                        "shortName": "Apple Inc.",
                        "regularMarketPrice": 225.50,
                        "chartPreviousClose": 220.00,
                        "regularMarketDayHigh": 226.00,
                        "regularMarketDayLow": 221.00,
                        "regularMarketVolume": 45000000,
                        "exchangeName": "NMS",
                    }
                }
            ],
            "error": None,
        }
    }

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        mock_get_json.return_value = mock_yahoo

        resp = await provider.get_quote("AAPL")
        assert resp.success is True
        assert resp.data is not None
        assert resp.data.ticker == "AAPL"
        assert resp.data.price == 225.50
        assert resp.data.change == 5.50
        assert resp.data.change_percent == 2.50
        assert "Apple Inc. (AAPL): 225.50 USD (+5.50 / +2.5%)" in resp.summary


@pytest.mark.asyncio
async def test_stock_provider_invalid_ticker(test_setup):
    config, client, cache = test_setup
    provider = StockProvider(config, client, cache)

    resp = await provider.get_quote("INVALID/TICKER??")
    assert resp.success is False
    assert "Invalid ticker" in (resp.error or "")


# --- 3. Forex Provider Tests ---
@pytest.mark.asyncio
async def test_forex_provider_success(test_setup):
    config, client, cache = test_setup
    provider = ForexProvider(config, client, cache)

    mock_fx = {
        "result": "success",
        "base_code": "USD",
        "time_last_update_utc": "Tue, 22 Sep 2026 00:00:00 +0000",
        "rates": {"INR": 95.50, "EUR": 0.88},
    }

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        mock_get_json.return_value = mock_fx

        resp = await provider.get_rate("USD", "INR", amount=10.0)
        assert resp.success is True
        assert resp.data is not None
        assert resp.data.base_currency == "USD"
        assert resp.data.target_currency == "INR"
        assert resp.data.rate == 95.50
        assert resp.data.converted_amount == 955.0
        assert "1 USD = 95.5000 INR" in resp.summary
        assert "10.00 USD = 955.00 INR" in resp.summary


@pytest.mark.asyncio
async def test_forex_provider_invalid_currency(test_setup):
    config, client, cache = test_setup
    provider = ForexProvider(config, client, cache)

    resp = await provider.get_rate("USDD", "INR")
    assert resp.success is False
    assert "Invalid currency" in (resp.error or "")


# --- 4. Crypto Provider Tests ---
@pytest.mark.asyncio
async def test_crypto_provider_coingecko_success(test_setup):
    config, client, cache = test_setup
    provider = CryptoProvider(config, client, cache)

    mock_cg = {
        "bitcoin": {
            "usd": 85000.0,
            "inr": 8100000.0,
            "usd_24h_change": 2.15,
            "usd_24h_vol": 25000000000.0,
        }
    }

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        mock_get_json.return_value = mock_cg

        resp = await provider.get_price("BTC", "USD")
        assert resp.success is True
        assert resp.data is not None
        assert resp.data.symbol == "BTC"
        assert resp.data.price_usd == 85000.0
        assert resp.data.change_24h_percent == 2.15
        assert "Bitcoin (BTC): $85,000.00 USD (+2.15%)" in resp.summary


@pytest.mark.asyncio
async def test_crypto_provider_binance_fallback(test_setup):
    config, client, cache = test_setup
    provider = CryptoProvider(config, client, cache)

    mock_binance = {
        "symbol": "BTCUSDT",
        "lastPrice": "85200.00",
        "priceChangePercent": "1.85",
        "highPrice": "86000.00",
        "lowPrice": "84000.00",
        "volume": "12000.0",
    }

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        # CoinGecko fails, Binance succeeds
        mock_get_json.side_effect = [Exception("CoinGecko rate limit"), mock_binance]

        resp = await provider.get_price("BTC", "USD")
        assert resp.success is True
        assert resp.data is not None
        assert resp.data.price_usd == 85200.0
        assert resp.data.change_24h_percent == 1.85


# --- 5. News Provider Tests ---
@pytest.mark.asyncio
async def test_news_provider_rss_success(test_setup):
    config, client, cache = test_setup
    provider = NewsProvider(config, client, cache)

    mock_rss = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
      <channel>
        <title>Google News</title>
        <item>
          <title>AI Breakthrough in Science - Nature</title>
          <link>https://news.google.com/articles/123</link>
          <pubDate>Tue, 22 Sep 2026 10:00:00 GMT</pubDate>
          <description>&lt;p&gt;Researchers demonstrate new model capabilities.&lt;/p&gt;</description>
        </item>
      </channel>
    </rss>
    """

    with patch.object(client, "get_text", new_callable=AsyncMock) as mock_get_text:
        mock_get_text.return_value = mock_rss

        resp = await provider.get_headlines("technology", limit=1)
        assert resp.success is True
        assert resp.data is not None
        assert len(resp.data.items) == 1
        assert resp.data.items[0].title == "AI Breakthrough in Science"
        assert resp.data.items[0].source_name == "Nature"
        assert "1. AI Breakthrough in Science (Nature)" in resp.summary


# --- 6. Network Provider Tests ---
@pytest.mark.asyncio
async def test_network_provider_success(test_setup):
    config, client, cache = test_setup
    provider = NetworkProvider(config, client, cache)

    mock_ip_data = {
        "status": "success",
        "query": "198.51.100.1",
        "city": "Seattle",
        "regionName": "Washington",
        "country": "United States",
        "countryCode": "US",
        "zip": "98101",
        "lat": 47.6062,
        "lon": -122.3321,
        "timezone": "America/Los_Angeles",
        "isp": "Cloud Provider Inc.",
        "org": "Cloud Org",
    }

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        mock_get_json.return_value = mock_ip_data

        resp = await provider.get_network_info()
        assert resp.success is True
        assert resp.data is not None
        assert resp.data.public_ip == "198.51.100.1"
        assert resp.data.city == "Seattle"
        assert resp.data.country == "United States"
        assert "Public IP: 198.51.100.1" in resp.summary


@pytest.mark.asyncio
async def test_network_provider_blocks_private_ip(test_setup):
    config, client, cache = test_setup
    provider = NetworkProvider(config, client, cache)

    # Private RFC1918 address must be rejected
    resp = await provider.get_network_info("192.168.1.1")
    assert resp.success is False
    assert "private/local network IP" in (resp.error or "")


# --- 7. Holiday Provider Tests ---
@pytest.mark.asyncio
async def test_holiday_provider_nager_success(test_setup):
    config, client, cache = test_setup
    provider = HolidayProvider(config, client, cache)

    mock_holidays = [
        {"date": "2026-01-01", "name": "New Year's Day", "localName": "New Year's Day", "countryCode": "US", "global": True, "types": ["Public"]},
        {"date": "2026-07-04", "name": "Independence Day", "localName": "Independence Day", "countryCode": "US", "global": True, "types": ["Public"]},
    ]

    with patch.object(client, "get_json", new_callable=AsyncMock) as mock_get_json:
        mock_get_json.return_value = mock_holidays

        resp = await provider.get_holidays("US", year=2026)
        assert resp.success is True
        assert resp.data is not None
        assert len(resp.data.holidays) == 2
        assert "Public Holidays for US (2026)" in resp.summary
        assert "New Year's Day" in resp.summary


@pytest.mark.asyncio
async def test_holiday_provider_india_gazetted_fallback(test_setup):
    config, client, cache = test_setup
    provider = HolidayProvider(config, client, cache)

    # India uses standard gazetted calendar fallback
    resp = await provider.get_holidays("India", year=2026)
    assert resp.success is True
    assert resp.data is not None
    assert resp.data.country_code == "IN"
    names = [h.name for h in resp.data.holidays]
    assert "Republic Day" in names
    assert "Independence Day" in names
    assert "Mahatma Gandhi Jayanti" in names
