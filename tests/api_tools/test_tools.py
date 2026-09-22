"""
Unit tests for Victor's 7 BaseTool public API classes.
"""

from unittest.mock import AsyncMock, patch
import pytest

from app.api_tools.models import (
    ApiResponse,
    CryptoPrice,
    ForexRate,
    HolidayItem,
    HolidayList,
    NetworkInfo,
    NewsFeed,
    NewsItem,
    StockQuote,
    WeatherInfo,
)
from app.api_tools.service import ApiToolsService
from app.tools.api_tools.tool import (
    ApiCryptoPriceTool,
    ApiForexRateTool,
    ApiNewsHeadlinesTool,
    ApiPublicHolidaysTool,
    ApiPublicIpInfoTool,
    ApiStockPriceTool,
    ApiWeatherTool,
)
from app.tools.permissions import PermissionLevel


@pytest.fixture
def mock_service():
    return AsyncMock(spec=ApiToolsService)


@pytest.mark.asyncio
async def test_weather_tool(mock_service):
    tool = ApiWeatherTool(service=mock_service)
    assert tool.name == "api_get_weather"
    assert tool.permission_level == PermissionLevel.SAFE
    assert "location" in tool.parameters["properties"]

    mock_service.get_weather.return_value = ApiResponse(
        success=True,
        summary="Weather in Tokyo: Clear sky, 18°C.",
        source="Open-Meteo",
    )

    res = await tool.execute({"location": "Tokyo", "units": "celsius"})
    assert "Weather in Tokyo: Clear sky, 18°C." in res
    assert "Source: Open-Meteo" in res


@pytest.mark.asyncio
async def test_stock_tool(mock_service):
    tool = ApiStockPriceTool(service=mock_service)
    assert tool.name == "api_get_stock_price"
    assert tool.permission_level == PermissionLevel.SAFE

    mock_service.get_stock_price.return_value = ApiResponse(
        success=True,
        summary="Microsoft Corporation (MSFT): 450.00 USD (+5.00 / +1.12%).",
        source="Yahoo Finance",
    )

    res = await tool.execute({"ticker": "MSFT"})
    assert "Microsoft Corporation (MSFT): 450.00 USD" in res
    assert "Source: Yahoo Finance" in res


@pytest.mark.asyncio
async def test_forex_tool(mock_service):
    tool = ApiForexRateTool(service=mock_service)
    assert tool.name == "api_get_forex_rate"
    assert tool.permission_level == PermissionLevel.SAFE

    mock_service.get_forex_rate.return_value = ApiResponse(
        success=True,
        summary="Exchange Rate: 1 USD = 95.8000 INR | 100.00 USD = 9,580.00 INR.",
        source="ExchangeRate-API",
    )

    res = await tool.execute({"base_currency": "USD", "target_currency": "INR", "amount": 100})
    assert "1 USD = 95.8000 INR" in res
    assert "Source: ExchangeRate-API" in res


@pytest.mark.asyncio
async def test_crypto_tool(mock_service):
    tool = ApiCryptoPriceTool(service=mock_service)
    assert tool.name == "api_get_crypto_price"
    assert tool.permission_level == PermissionLevel.SAFE

    mock_service.get_crypto_price.return_value = ApiResponse(
        success=True,
        summary="Bitcoin (BTC): $86,000.00 USD (+1.25%).",
        source="CoinGecko",
    )

    res = await tool.execute({"symbol": "BTC", "vs_currency": "USD"})
    assert "Bitcoin (BTC): $86,000.00 USD" in res
    assert "Source: CoinGecko" in res


@pytest.mark.asyncio
async def test_news_tool(mock_service):
    tool = ApiNewsHeadlinesTool(service=mock_service)
    assert tool.name == "api_get_news_headlines"
    assert tool.permission_level == PermissionLevel.SAFE

    mock_service.get_news_headlines.return_value = ApiResponse(
        success=True,
        summary="Latest Technology Headlines:\n1. Quantum Leap in Computing (TechCrunch)",
        source="Google News RSS",
    )

    res = await tool.execute({"category": "technology", "limit": 3})
    assert "Quantum Leap in Computing" in res


@pytest.mark.asyncio
async def test_network_tool(mock_service):
    tool = ApiPublicIpInfoTool(service=mock_service)
    assert tool.name == "api_get_public_ip_info"
    assert tool.permission_level == PermissionLevel.SAFE

    mock_service.get_network_info.return_value = ApiResponse(
        success=True,
        summary="Public IP: 203.0.113.195 (Location: San Jose, California, United States, ISP: Public ISP Inc.)",
        source="ip-api.com",
    )

    res = await tool.execute({})
    assert "Public IP: 203.0.113.195" in res


@pytest.mark.asyncio
async def test_holidays_tool(mock_service):
    tool = ApiPublicHolidaysTool(service=mock_service)
    assert tool.name == "api_get_public_holidays"
    assert tool.permission_level == PermissionLevel.SAFE

    mock_service.get_public_holidays.return_value = ApiResponse(
        success=True,
        summary="Public Holidays for US (2026) — 11 total:\n• 2026-01-01: New Year's Day",
        source="Nager.Date",
    )

    res = await tool.execute({"country": "US", "year": 2026})
    assert "New Year's Day" in res
