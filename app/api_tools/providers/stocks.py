"""
Stock market quotes provider using Yahoo Finance v8 public chart API.
"""

from __future__ import annotations

import logging
import re
from typing import Optional

from app.api_tools.models import ApiResponse, StockQuote
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)


class StockProvider(BaseApiProvider):
    name = "Yahoo Finance"

    async def get_quote(self, ticker: str) -> ApiResponse[StockQuote]:
        """Fetch real-time stock quote and daily metrics for a ticker symbol."""
        cleaned_ticker = ticker.strip().upper()
        if not cleaned_ticker or not re.match(r"^[A-Z0-9\.\-\^]{1,15}$", cleaned_ticker):
            return ApiResponse(
                success=False,
                error=f"Invalid ticker symbol '{ticker}'. Use standard symbols like AAPL, MSFT, TSLA, or RELIANCE.NS.",
                source=self.name,
            )

        cache_key = f"stock:{cleaned_ticker}"
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

        try:
            url = f"{self.config.stocks_yahoo_chart_url}/{cleaned_ticker}"
            params = {"interval": "1d", "range": "1d"}
            resp_data = await self.client.get_json(url, params=params)

            chart = (resp_data or {}).get("chart", {})
            error_info = chart.get("error")
            if error_info:
                desc = error_info.get("description", "Ticker not found")
                return ApiResponse(
                    success=False,
                    error=f"Stock quote error for '{cleaned_ticker}': {desc}",
                    source=self.name,
                )

            results = chart.get("result")
            if not results or not isinstance(results, list):
                return ApiResponse(
                    success=False,
                    error=f"No data returned for ticker '{cleaned_ticker}'.",
                    source=self.name,
                )

            meta = results[0].get("meta", {})
            price = meta.get("regularMarketPrice")
            if price is None:
                return ApiResponse(
                    success=False,
                    error=f"Current price for '{cleaned_ticker}' is unavailable.",
                    source=self.name,
                )

            currency = meta.get("currency", "USD")
            prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
            day_high = meta.get("regularMarketDayHigh")
            day_low = meta.get("regularMarketDayLow")
            volume = meta.get("regularMarketVolume")
            exchange = meta.get("exchangeName", "")
            company_name = meta.get("shortName") or meta.get("longName") or cleaned_ticker
            market_state = meta.get("marketState", "REGULAR")

            change = round(price - prev_close, 2) if prev_close else None
            change_pct = round((change / prev_close) * 100, 2) if prev_close and prev_close > 0 and change is not None else None

            quote_data = StockQuote(
                ticker=cleaned_ticker,
                company_name=company_name,
                currency=currency,
                price=float(price),
                previous_close=float(prev_close) if prev_close else None,
                change=change,
                change_percent=change_pct,
                day_high=float(day_high) if day_high else None,
                day_low=float(day_low) if day_low else None,
                volume=int(volume) if volume else None,
                exchange=exchange,
                market_state=market_state,
            )

            # Cache the quote
            await self.set_cached(cache_key, quote_data, self.config.cache_ttl_stocks)

            summary = self._format_summary(quote_data)
            return ApiResponse(
                success=True,
                data=quote_data,
                source=self.name,
                cached=False,
                summary=summary,
            )

        except Exception as exc:
            logger.error(f"Error fetching stock quote for {cleaned_ticker}: {exc}")
            return ApiResponse(
                success=False,
                error=f"Failed to fetch stock quote: {exc}",
                source=self.name,
            )

    def _format_summary(self, quote: StockQuote) -> str:
        name_str = f"{quote.company_name} ({quote.ticker})" if quote.company_name != quote.ticker else quote.ticker
        price_str = f"{quote.price:,.2f} {quote.currency}"

        change_str = ""
        if quote.change is not None and quote.change_percent is not None:
            sign = "+" if quote.change >= 0 else ""
            change_str = f" ({sign}{quote.change:,.2f} / {sign}{quote.change_percent}%)"

        metrics = []
        if quote.day_high and quote.day_low:
            metrics.append(f"Day Range: {quote.day_low:,.2f} - {quote.day_high:,.2f}")
        if quote.volume:
            metrics.append(f"Vol: {quote.volume:,}")

        metrics_str = f" [{', '.join(metrics)}]" if metrics else ""
        return f"{name_str}: {price_str}{change_str}{metrics_str}."
