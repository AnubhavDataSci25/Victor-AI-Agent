"""
Weather and forecast provider using Open-Meteo's free, keyless API.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.api_tools.models import ApiResponse, WeatherInfo
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)

# WMO Weather interpretation codes (WW)
WMO_CODE_DESCRIPTIONS = {
    0: "Clear sky",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Depositing rime fog",
    51: "Light drizzle",
    53: "Moderate drizzle",
    55: "Dense drizzle",
    56: "Light freezing drizzle",
    57: "Dense freezing drizzle",
    61: "Slight rain",
    63: "Moderate rain",
    65: "Heavy rain",
    66: "Light freezing rain",
    67: "Heavy freezing rain",
    71: "Slight snow fall",
    73: "Moderate snow fall",
    75: "Heavy snow fall",
    77: "Snow grains",
    80: "Slight rain showers",
    81: "Moderate rain showers",
    82: "Violent rain showers",
    85: "Slight snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorm",
    96: "Thunderstorm with slight hail",
    99: "Thunderstorm with heavy hail",
}


class WeatherProvider(BaseApiProvider):
    name = "Open-Meteo"

    async def get_weather(self, location: str, units: str = "celsius") -> ApiResponse[WeatherInfo]:
        """Fetch current weather for a city or place name."""
        cleaned_location = location.strip()
        if not cleaned_location or len(cleaned_location) < 2:
            return ApiResponse(
                success=False,
                error="Invalid location provided. Please specify a valid city or region name.",
                source=self.name,
            )

        # Sanitize location string: alphanumeric and basic punctuation only
        cleaned_location = re.sub(r"[^\w\s,\.\-]", "", cleaned_location)

        cache_key = f"weather:{cleaned_location.lower()}:{units.lower()}"
        cached_data, age = await self.get_cached(cache_key)
        if cached_data is not None:
            summary = self._format_summary(cached_data, units)
            return ApiResponse(
                success=True,
                data=cached_data,
                source=self.name,
                cached=True,
                cache_age_seconds=age,
                summary=summary,
            )

        try:
            # 1. Geocode location to lat/lon
            geo_params = {
                "name": cleaned_location,
                "count": 1,
                "language": "en",
                "format": "json",
            }
            geo_resp = await self.client.get_json(self.config.weather_geo_url, params=geo_params)
            results = (geo_resp or {}).get("results")
            if not results:
                return ApiResponse(
                    success=False,
                    error=f"Location '{cleaned_location}' could not be resolved. Please verify the spelling.",
                    source=self.name,
                )

            top_geo = results[0]
            resolved_name = top_geo.get("name", cleaned_location)
            country = top_geo.get("country", "")
            lat = top_geo["latitude"]
            lon = top_geo["longitude"]

            # 2. Fetch current weather conditions
            forecast_params = {
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
            }
            forecast_resp = await self.client.get_json(self.config.weather_forecast_url, params=forecast_params)
            current = (forecast_resp or {}).get("current")
            if not current:
                return ApiResponse(
                    success=False,
                    error="Weather data currently unavailable from provider.",
                    source=self.name,
                )

            temp_c = float(current.get("temperature_2m", 0.0))
            apparent_c = float(current.get("apparent_temperature", 0.0))
            temp_f = round(temp_c * 9 / 5 + 32, 1)
            apparent_f = round(apparent_c * 9 / 5 + 32, 1)
            humidity = int(current.get("relative_humidity_2m", 0))
            precip = float(current.get("precipitation", 0.0))
            wind = float(current.get("wind_speed_10m", 0.0))
            wmo_code = int(current.get("weather_code", 0))
            condition = WMO_CODE_DESCRIPTIONS.get(wmo_code, "Clear")
            obs_time = current.get("time", "")

            weather_data = WeatherInfo(
                location=resolved_name,
                country=country,
                latitude=lat,
                longitude=lon,
                temperature_c=temp_c,
                temperature_f=temp_f,
                apparent_temperature_c=apparent_c,
                apparent_temperature_f=apparent_f,
                relative_humidity=humidity,
                precipitation_mm=precip,
                wind_speed_kmh=wind,
                weather_condition=condition,
                weather_code=wmo_code,
                observation_time=obs_time,
            )

            # Store in cache
            await self.set_cached(cache_key, weather_data, self.config.cache_ttl_weather)

            summary = self._format_summary(weather_data, units)
            return ApiResponse(
                success=True,
                data=weather_data,
                source=self.name,
                cached=False,
                summary=summary,
            )

        except Exception as exc:
            logger.error(f"Error fetching weather for {cleaned_location}: {exc}")
            return ApiResponse(
                success=False,
                error=f"Failed to fetch weather: {exc}",
                source=self.name,
            )

    def _format_summary(self, info: WeatherInfo, units: str) -> str:
        loc = f"{info.location}, {info.country}" if info.country else info.location
        if units.lower() in ("fahrenheit", "f"):
            temp = f"{info.temperature_f}°F (feels like {info.apparent_temperature_f}°F)"
        else:
            temp = f"{info.temperature_c}°C (feels like {info.apparent_temperature_c}°C)"

        precip_str = f", Precip: {info.precipitation_mm}mm" if info.precipitation_mm > 0 else ""
        return (
            f"Weather in {loc}: {info.weather_condition}, {temp}, "
            f"Humidity: {info.relative_humidity}%, Wind: {info.wind_speed_kmh} km/h{precip_str}."
        )
