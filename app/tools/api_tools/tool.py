"""
Victor 2.0 Free Public API Tools.

Provides lightweight, async BaseTool implementations for:
- api_get_weather: Real-time weather and forecast worldwide (Open-Meteo)
- api_get_stock_price: Stock quotes, daily change, high/low, volume (Yahoo Finance)
- api_get_forex_rate: Foreign exchange rates and currency conversion (ExchangeRate-API)
- api_get_crypto_price: Real-time cryptocurrency prices and 24h metrics (CoinGecko / Binance)
- api_get_news_headlines: Top breaking news headlines and tech stories (Google News RSS / Hacker News)
- api_get_public_ip_info: Public IP, ISP, and geographic network info (ip-api.com / ipify)
- api_get_public_holidays: Public and national holidays by country and year (Nager.Date / Gazetted calendar)
"""

from __future__ import annotations

import logging
from typing import Optional

from app.api_tools.service import ApiToolsService, get_api_tools_service
from app.tools.base import BaseTool
from app.tools.permissions import PermissionLevel

logger = logging.getLogger(__name__)


class ApiWeatherTool(BaseTool):
    name = "api_get_weather"
    description = (
        "Retrieves current real-time weather conditions, temperature, humidity, wind speed, "
        "and precipitation for any city or location worldwide using Open-Meteo."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "location": {
                "type": "string",
                "description": "City or place name, e.g. 'London', 'New York', 'Tokyo', 'Mumbai', 'San Francisco'.",
            },
            "units": {
                "type": "string",
                "enum": ["celsius", "fahrenheit"],
                "description": "Temperature units: 'celsius' (default) or 'fahrenheit'.",
            },
        },
        "required": ["location"],
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        location = args.get("location", "")
        units = args.get("units", "celsius")
        try:
            resp = await self.service.get_weather(location=location, units=units)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"WeatherTool execution error: {e}")
            return f"Weather retrieval failed: {e}"


class ApiStockPriceTool(BaseTool):
    name = "api_get_stock_price"
    description = (
        "Retrieves real-time stock price, daily price change, percentage change, day high/low, "
        "and trading volume for a stock ticker (e.g. AAPL, MSFT, TSLA, RELIANCE.NS) using Yahoo Finance."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "ticker": {
                "type": "string",
                "description": "The stock ticker symbol, e.g. 'AAPL', 'MSFT', 'GOOGL', 'NVDA', 'TSLA', 'AMZN', or 'RELIANCE.NS'.",
            }
        },
        "required": ["ticker"],
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        ticker = args.get("ticker", "")
        try:
            resp = await self.service.get_stock_price(ticker=ticker)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"StockPriceTool execution error: {e}")
            return f"Stock quote retrieval failed: {e}"


class ApiForexRateTool(BaseTool):
    name = "api_get_forex_rate"
    description = (
        "Retrieves current foreign exchange (FX) currency rates and performs currency conversions "
        "between major world currencies (USD, EUR, INR, GBP, JPY, CAD, etc.)."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "base_currency": {
                "type": "string",
                "description": "Base currency 3-letter ISO code (e.g. 'USD', 'EUR', 'GBP'). Default is 'USD'.",
            },
            "target_currency": {
                "type": "string",
                "description": "Target currency 3-letter ISO code to convert into (e.g. 'INR', 'EUR', 'GBP', 'JPY'). Default is 'INR'.",
            },
            "amount": {
                "type": "number",
                "description": "Optional amount of base currency to convert. Default is 1.0.",
            },
        },
        "required": ["base_currency", "target_currency"],
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        base = args.get("base_currency", "USD")
        target = args.get("target_currency", "INR")
        try:
            amount = float(args.get("amount", 1.0))
        except (ValueError, TypeError):
            amount = 1.0

        try:
            resp = await self.service.get_forex_rate(base_currency=base, target_currency=target, amount=amount)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"ForexRateTool execution error: {e}")
            return f"Exchange rate retrieval failed: {e}"


class ApiCryptoPriceTool(BaseTool):
    name = "api_get_crypto_price"
    description = (
        "Retrieves real-time cryptocurrency prices, 24-hour percentage change, day range, "
        "and trading volume for cryptocurrencies (e.g. BTC, ETH, SOL, DOGE, XRP, ADA)."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "symbol": {
                "type": "string",
                "description": "The cryptocurrency ticker symbol or name, e.g. 'BTC', 'ETH', 'SOL', 'DOGE', 'XRP', 'ADA'.",
            },
            "vs_currency": {
                "type": "string",
                "description": "Fiat or reference currency to display price in (e.g. 'USD', 'INR', 'EUR'). Default is 'USD'.",
            },
        },
        "required": ["symbol"],
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        symbol = args.get("symbol", "BTC")
        vs_currency = args.get("vs_currency", "USD")
        try:
            resp = await self.service.get_crypto_price(symbol=symbol, vs_currency=vs_currency)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"CryptoPriceTool execution error: {e}")
            return f"Cryptocurrency price retrieval failed: {e}"


class ApiNewsHeadlinesTool(BaseTool):
    name = "api_get_news_headlines"
    description = (
        "Retrieves latest breaking news headlines and top stories across categories "
        "(general, world, business, technology, science, sports, entertainment, health, or hackernews)."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "News category: 'general', 'world', 'business', 'technology', 'science', 'sports', 'entertainment', 'health', or 'hackernews'. Default is 'general'.",
            },
            "limit": {
                "type": "integer",
                "description": "Number of headlines to return (1 to 10). Default is 5.",
            },
        },
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        category = args.get("category", "general")
        try:
            limit = int(args.get("limit", 5))
        except (ValueError, TypeError):
            limit = 5

        try:
            resp = await self.service.get_news_headlines(category=category, limit=limit)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"NewsHeadlinesTool execution error: {e}")
            return f"News retrieval failed: {e}"


class ApiPublicIpInfoTool(BaseTool):
    name = "api_get_public_ip_info"
    description = (
        "Retrieves current public internet IP address, ISP, organization, timezone, "
        "and approximate geographic location."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "ip_address": {
                "type": "string",
                "description": "Optional public IP address to query. If omitted, returns this machine's external public IP info.",
            }
        },
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        ip_address = args.get("ip_address")
        try:
            resp = await self.service.get_network_info(ip_address=ip_address)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"PublicIpInfoTool execution error: {e}")
            return f"Public IP info retrieval failed: {e}"


class ApiPublicHolidaysTool(BaseTool):
    name = "api_get_public_holidays"
    description = (
        "Retrieves official public and national holidays for a given country (e.g. US, IN, GB, CA, AU, DE, FR) "
        "and calendar year."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "country": {
                "type": "string",
                "description": "Country code (e.g. 'US', 'IN', 'GB', 'CA', 'AU') or country name (e.g. 'India', 'United States', 'United Kingdom'). Default is 'US'.",
            },
            "year": {
                "type": "integer",
                "description": "Calendar year to query (e.g. 2026). Default is current calendar year.",
            },
        },
    }

    def __init__(self, service: Optional[ApiToolsService] = None) -> None:
        self.service = service or get_api_tools_service()

    async def execute(self, args: dict) -> str:
        country = args.get("country", "US")
        year_val = args.get("year")
        year: Optional[int] = None
        if year_val is not None:
            try:
                year = int(year_val)
            except (ValueError, TypeError):
                year = None

        try:
            resp = await self.service.get_public_holidays(country=country, year=year)
            return resp.formatted_summary()
        except Exception as e:
            logger.error(f"PublicHolidaysTool execution error: {e}")
            return f"Public holidays retrieval failed: {e}"
