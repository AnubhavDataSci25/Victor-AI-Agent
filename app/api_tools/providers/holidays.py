"""
Public and national holidays provider using Nager.Date API with gazetted fallbacks.
"""

from __future__ import annotations

from datetime import datetime
import logging
import re
from typing import Dict, List, Optional

from app.api_tools.models import ApiResponse, HolidayItem, HolidayList
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)

# Common country name to ISO 3166-1 alpha-2 code mapping
COUNTRY_NAME_TO_CODE: Dict[str, str] = {
    "UNITED STATES": "US",
    "USA": "US",
    "US": "US",
    "AMERICA": "US",
    "UNITED KINGDOM": "GB",
    "UK": "GB",
    "BRITAIN": "GB",
    "ENGLAND": "GB",
    "INDIA": "IN",
    "IN": "IN",
    "BHARAT": "IN",
    "CANADA": "CA",
    "AUSTRALIA": "AU",
    "GERMANY": "DE",
    "FRANCE": "FR",
    "JAPAN": "JP",
    "CHINA": "CN",
    "BRAZIL": "BR",
    "MEXICO": "MX",
    "SINGAPORE": "SG",
    "NEW ZEALAND": "NZ",
    "SOUTH AFRICA": "ZA",
    "ITALY": "IT",
    "SPAIN": "ES",
    "NETHERLANDS": "NL",
    "SWITZERLAND": "CH",
    "RUSSIA": "RU",
    "SWEDEN": "SE",
    "NORWAY": "NO",
}

# Standard Indian Gazetted National Holidays calendar
INDIAN_NATIONAL_HOLIDAYS = [
    ("01-26", "Republic Day", "Gantantra Diwas"),
    ("03-25", "Holi", "Holi"),
    ("04-11", "Eid-ul-Fitr", "Eid-ul-Fitr"),
    ("04-14", "Dr. B.R. Ambedkar Jayanti", "Ambedkar Jayanti"),
    ("05-23", "Buddha Purnima", "Buddha Purnima"),
    ("06-17", "Bakrid / Eid-ul-Adha", "Eid-ul-Adha"),
    ("07-17", "Muharram", "Muharram"),
    ("08-15", "Independence Day", "Swatantrata Diwas"),
    ("10-02", "Mahatma Gandhi Jayanti", "Gandhi Jayanti"),
    ("10-12", "Dussehra / Vijayadashami", "Dussehra"),
    ("10-31", "Diwali / Deepavali", "Diwali"),
    ("11-15", "Guru Nanak Jayanti", "Guru Nanak Gurpurab"),
    ("12-25", "Christmas", "Bada Din"),
]


class HolidayProvider(BaseApiProvider):
    name = "Nager.Date Public Holidays"

    async def get_holidays(
        self,
        country: str = "US",
        year: Optional[int] = None,
    ) -> ApiResponse[HolidayList]:
        """Fetch official public and national holidays for a given country and year."""
        country_clean = country.strip().upper()
        country_code = COUNTRY_NAME_TO_CODE.get(country_clean, country_clean)

        if not re.match(r"^[A-Z]{2}$", country_code):
            return ApiResponse(
                success=False,
                error=f"Invalid country code or name: '{country}'. Use 2-letter ISO codes (e.g. US, GB, CA, AU, IN) or standard country names.",
                source=self.name,
            )

        target_year = year or datetime.now().year

        cache_key = f"holidays:{country_code}:{target_year}"
        cached_data, age = await self.get_cached(cache_key)
        if cached_data is not None:
            summary = self._format_summary(cached_data)
            return ApiResponse(
                success=True,
                data=cached_data,
                source=self.name,
                cached=True,
                cache_age_seconds=age,
                summary=summary,
            )

        # Special handling for India (IN) — standard gazetted national holiday schedule
        if country_code == "IN":
            holidays = [
                HolidayItem(
                    date=f"{target_year}-{date_part}",
                    name=name,
                    local_name=local_name,
                    country_code="IN",
                    is_global=True,
                    types=["National", "Gazetted Public Holiday"],
                )
                for date_part, name, local_name in INDIAN_NATIONAL_HOLIDAYS
            ]
            holiday_list = HolidayList(country_code="IN", year=target_year, holidays=holidays)
            await self.set_cached(cache_key, holiday_list, self.config.cache_ttl_holidays)
            return ApiResponse(
                success=True,
                data=holiday_list,
                source="Gazetted National Calendar",
                cached=False,
                summary=self._format_summary(holiday_list),
            )

        # Query Nager.Date API
        try:
            url = f"{self.config.holidays_nager_url}/PublicHolidays/{target_year}/{country_code}"
            resp = await self.client.get_json(url)

            if not resp or not isinstance(resp, list):
                return ApiResponse(
                    success=False,
                    error=f"No public holidays found for country code '{country_code}' in {target_year}.",
                    source=self.name,
                )

            holidays: List[HolidayItem] = []
            for item in resp:
                holidays.append(
                    HolidayItem(
                        date=item.get("date", ""),
                        name=item.get("name", ""),
                        local_name=item.get("localName", ""),
                        country_code=item.get("countryCode", country_code),
                        is_global=item.get("global", True),
                        types=item.get("types", ["Public"]),
                    )
                )

            holiday_list = HolidayList(country_code=country_code, year=target_year, holidays=holidays)
            await self.set_cached(cache_key, holiday_list, self.config.cache_ttl_holidays)

            summary = self._format_summary(holiday_list)
            return ApiResponse(
                success=True,
                data=holiday_list,
                source=self.name,
                cached=False,
                summary=summary,
            )

        except Exception as exc:
            logger.error(f"Error fetching holidays for {country_code}: {exc}")
            return ApiResponse(
                success=False,
                error=f"Failed to fetch public holidays: {exc}",
                source=self.name,
            )

    def _format_summary(self, holiday_list: HolidayList) -> str:
        count = len(holiday_list.holidays)
        lines = [f"Public Holidays for {holiday_list.country_code} ({holiday_list.year}) — {count} total:"]

        # Sort and list up to 8 holidays
        sorted_holidays = sorted(holiday_list.holidays, key=lambda x: x.date)
        for h in sorted_holidays[:8]:
            local = f" ({h.local_name})" if h.local_name and h.local_name != h.name else ""
            lines.append(f"• {h.date}: {h.name}{local}")

        if count > 8:
            lines.append(f"... and {count - 8} more.")

        return "\n".join(lines)
