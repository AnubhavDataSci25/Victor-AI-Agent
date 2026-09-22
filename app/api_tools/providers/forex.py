"""
Currency exchange rates and conversion provider using Open Exchange Rates / Frankfurter public APIs.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.api_tools.models import ApiResponse, ForexRate
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)


class ForexProvider(BaseApiProvider):
    name = "ExchangeRate-API"

    async def get_rate(
        self,
        base_currency: str = "USD",
        target_currency: str = "INR",
        amount: float = 1.0,
    ) -> ApiResponse[ForexRate]:
        """Fetch real-time foreign exchange rate and calculate currency conversion."""
        base = base_currency.strip().upper()
        target = target_currency.strip().upper()

        if not re.match(r"^[A-Z]{3}$", base) or not re.match(r"^[A-Z]{3}$", target):
            return ApiResponse(
                success=False,
                error=f"Invalid currency code(s): '{base_currency}' or '{target_currency}'. Please use 3-letter ISO codes like USD, EUR, INR, GBP, JPY.",
                source=self.name,
            )

        if amount <= 0:
            return ApiResponse(
                success=False,
                error="Conversion amount must be a positive number greater than 0.",
                source=self.name,
            )

        cache_key = f"forex:{base}:{target}"
        cached_data, age = await self.get_cached(cache_key)
        if cached_data is not None:
            # Recompute converted amount with the requested amount
            cached_rate: ForexRate = cached_data
            converted = round(amount * cached_rate.rate, 4)
            data_copy = cached_rate.model_copy(update={"amount": amount, "converted_amount": converted})
            summary = self._format_summary(data_copy)
            return ApiResponse(
                success=True,
                data=data_copy,
                source=self.name,
                cached=True,
                cache_age_seconds=age,
                summary=summary,
            )

        try:
            # 1. Primary: open.er-api.com
            rate_val: Optional[float] = None
            last_updated = ""

            try:
                url = f"{self.config.forex_open_api_url}/{base}"
                resp = await self.client.get_json(url)
                if resp and resp.get("result") == "success":
                    rates = resp.get("rates", {})
                    if target in rates:
                        rate_val = float(rates[target])
                        last_updated = resp.get("time_last_update_utc", "")
            except Exception as e:
                logger.warning(f"Primary FX provider failed for {base}->{target}: {e}")

            # 2. Fallback: Frankfurter API
            if rate_val is None:
                try:
                    fallback_url = f"{self.config.forex_frankfurter_url}?from={base}&to={target}"
                    resp = await self.client.get_json(fallback_url)
                    if resp and "rates" in resp and target in resp["rates"]:
                        rate_val = float(resp["rates"][target])
                        last_updated = resp.get("date", "")
                        self.name = "Frankfurter API"
                except Exception as e:
                    logger.warning(f"Fallback FX provider failed for {base}->{target}: {e}")

            if rate_val is None:
                return ApiResponse(
                    success=False,
                    error=f"Exchange rate for {base} to {target} is currently unavailable or unsupported.",
                    source=self.name,
                )

            converted_amount = round(amount * rate_val, 4)
            forex_data = ForexRate(
                base_currency=base,
                target_currency=target,
                rate=round(rate_val, 6),
                amount=amount,
                converted_amount=converted_amount,
                last_updated_utc=last_updated,
            )

            # Cache the rate (with unit rate)
            await self.set_cached(cache_key, forex_data, self.config.cache_ttl_forex)

            summary = self._format_summary(forex_data)
            return ApiResponse(
                success=True,
                data=forex_data,
                source=self.name,
                cached=False,
                summary=summary,
            )

        except Exception as exc:
            logger.error(f"Error fetching forex rate {base}->{target}: {exc}")
            return ApiResponse(
                success=False,
                error=f"Failed to fetch exchange rate: {exc}",
                source=self.name,
            )

    def _format_summary(self, forex: ForexRate) -> str:
        base_rate_str = f"1 {forex.base_currency} = {forex.rate:,.4f} {forex.target_currency}"
        if forex.amount != 1.0:
            conv_str = f" | {forex.amount:,.2f} {forex.base_currency} = {forex.converted_amount:,.2f} {forex.target_currency}"
        else:
            conv_str = ""
        update_str = f" (Updated: {forex.last_updated_utc})" if forex.last_updated_utc else ""
        return f"Exchange Rate: {base_rate_str}{conv_str}{update_str}."
