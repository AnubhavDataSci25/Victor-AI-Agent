"""
Cryptocurrency price and market metrics provider using CoinGecko and Binance public APIs.
"""

from __future__ import annotations

import logging
import re
from typing import Dict, Optional

from app.api_tools.models import ApiResponse, CryptoPrice
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)

# Common cryptocurrency symbol to CoinGecko ID mapping
CRYPTO_SYMBOL_MAP: Dict[str, tuple[str, str]] = {
    "BTC": ("bitcoin", "Bitcoin"),
    "BITCOIN": ("bitcoin", "Bitcoin"),
    "ETH": ("ethereum", "Ethereum"),
    "ETHEREUM": ("ethereum", "Ethereum"),
    "SOL": ("solana", "Solana"),
    "SOLANA": ("solana", "Solana"),
    "BNB": ("binancecoin", "BNB"),
    "XRP": ("ripple", "XRP"),
    "DOGE": ("dogecoin", "Dogecoin"),
    "DOGECOIN": ("dogecoin", "Dogecoin"),
    "ADA": ("cardano", "Cardano"),
    "CARDANO": ("cardano", "Cardano"),
    "AVAX": ("avalanche-2", "Avalanche"),
    "DOT": ("polkadot", "Polkadot"),
    "MATIC": ("matic-network", "Polygon"),
    "POL": ("polygon-ecosystem-token", "Polygon"),
    "SHIB": ("shiba-inu", "Shiba Inu"),
    "LTC": ("litecoin", "Litecoin"),
    "LINK": ("chainlink", "Chainlink"),
    "TRX": ("tron", "TRON"),
    "NEAR": ("near", "NEAR Protocol"),
    "USDT": ("tether", "Tether"),
    "USDC": ("usd-coin", "USD Coin"),
}


class CryptoProvider(BaseApiProvider):
    name = "CoinGecko / Binance"

    async def get_price(
        self,
        symbol: str = "BTC",
        vs_currency: str = "USD",
    ) -> ApiResponse[CryptoPrice]:
        """Fetch real-time crypto price, 24h percentage change, and volume."""
        sym_clean = symbol.strip().upper()
        sym_clean = re.sub(r"[^A-Z0-9]", "", sym_clean)
        vs_clean = vs_currency.strip().upper()

        if not sym_clean:
            return ApiResponse(
                success=False,
                error="Invalid crypto symbol. Try symbols like BTC, ETH, SOL, or DOGE.",
                source=self.name,
            )

        cache_key = f"crypto:{sym_clean}:{vs_clean}"
        cached_data, age = await self.get_cached(cache_key)
        if cached_data is not None:
            summary = self._format_summary(cached_data, vs_clean)
            return ApiResponse(
                success=True,
                data=cached_data,
                source=self.name,
                cached=True,
                cache_age_seconds=age,
                summary=summary,
            )

        coin_id, coin_name = CRYPTO_SYMBOL_MAP.get(sym_clean, (sym_clean.lower(), sym_clean))

        # 1. Try CoinGecko simple price
        try:
            target_lower = vs_clean.lower()
            currencies = list(set([target_lower, "usd", "inr"]))
            currencies_str = ",".join(currencies)
            params = {
                "ids": coin_id,
                "vs_currencies": currencies_str,
                "include_24hr_change": "true",
                "include_24hr_vol": "true",
            }
            resp = await self.client.get_json(self.config.crypto_coingecko_url, params=params)

            if resp and coin_id in resp and "usd" in resp[coin_id]:
                data = resp[coin_id]
                price_usd = float(data.get("usd", 0.0))
                price_inr = float(data.get("inr", 0.0)) if "inr" in data else None
                price_target = float(data.get(target_lower, price_usd))
                change_24h = data.get(f"{target_lower}_24h_change") or data.get("usd_24h_change")
                volume_24h = data.get(f"{target_lower}_24h_vol") or data.get("usd_24h_vol")

                crypto_data = CryptoPrice(
                    symbol=sym_clean,
                    name=coin_name,
                    price_usd=price_usd,
                    price_inr=price_inr,
                    price_target=price_target,
                    target_currency=vs_clean,
                    change_24h_percent=round(float(change_24h), 2) if change_24h is not None else None,
                    volume_24h=round(float(volume_24h), 2) if volume_24h is not None else None,
                )

                await self.set_cached(cache_key, crypto_data, self.config.cache_ttl_crypto)
                return ApiResponse(
                    success=True,
                    data=crypto_data,
                    source="CoinGecko",
                    cached=False,
                    summary=self._format_summary(crypto_data, vs_clean),
                )
        except Exception as e:
            logger.warning(f"CoinGecko price fetch failed for {sym_clean}: {e}")

        # 2. Fallback to Binance 24hr ticker API (e.g. BTCUSDT)
        try:
            binance_symbol = f"{sym_clean}USDT"
            params = {"symbol": binance_symbol}
            resp = await self.client.get_json(self.config.crypto_binance_url, params=params)

            if resp and "lastPrice" in resp:
                price_usd = float(resp["lastPrice"])
                change_pct = float(resp.get("priceChangePercent", 0.0))
                high_24h = float(resp.get("highPrice", 0.0))
                low_24h = float(resp.get("lowPrice", 0.0))
                vol_24h = float(resp.get("volume", 0.0))

                crypto_data = CryptoPrice(
                    symbol=sym_clean,
                    name=coin_name,
                    price_usd=price_usd,
                    price_target=price_usd,
                    target_currency="USD",
                    change_24h_percent=round(change_pct, 2),
                    high_24h=high_24h,
                    low_24h=low_24h,
                    volume_24h=vol_24h,
                )

                await self.set_cached(cache_key, crypto_data, self.config.cache_ttl_crypto)
                return ApiResponse(
                    success=True,
                    data=crypto_data,
                    source="Binance",
                    cached=False,
                    summary=self._format_summary(crypto_data, "USD"),
                )
        except Exception as e:
            logger.warning(f"Binance fallback failed for {sym_clean}: {e}")

        return ApiResponse(
            success=False,
            error=f"Could not retrieve cryptocurrency price for '{symbol}'. Please verify the symbol.",
            source=self.name,
        )

    def _format_summary(self, crypto: CryptoPrice, vs_curr: str) -> str:
        sign = "+" if (crypto.change_24h_percent or 0) >= 0 else ""
        chg_str = f" ({sign}{crypto.change_24h_percent}%)" if crypto.change_24h_percent is not None else ""

        if vs_curr.upper() == "INR" and crypto.price_inr:
            price_display = f"₹{crypto.price_inr:,.2f} INR (${crypto.price_usd:,.2f} USD)"
        else:
            price_display = f"${crypto.price_usd:,.2f} USD"

        range_str = f" [24h Range: ${crypto.low_24h:,.2f} - ${crypto.high_24h:,.2f}]" if crypto.high_24h and crypto.low_24h else ""
        return f"{crypto.name} ({crypto.symbol}): {price_display}{chg_str}{range_str}."
