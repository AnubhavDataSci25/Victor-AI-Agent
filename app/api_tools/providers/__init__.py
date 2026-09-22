"""
Public API providers for Victor.
"""

from app.api_tools.providers.base import BaseApiProvider
from app.api_tools.providers.crypto import CryptoProvider
from app.api_tools.providers.forex import ForexProvider
from app.api_tools.providers.holidays import HolidayProvider
from app.api_tools.providers.network import NetworkProvider
from app.api_tools.providers.news import NewsProvider
from app.api_tools.providers.stocks import StockProvider
from app.api_tools.providers.weather import WeatherProvider

__all__ = [
    "BaseApiProvider",
    "WeatherProvider",
    "StockProvider",
    "ForexProvider",
    "CryptoProvider",
    "NewsProvider",
    "NetworkProvider",
    "HolidayProvider",
]
