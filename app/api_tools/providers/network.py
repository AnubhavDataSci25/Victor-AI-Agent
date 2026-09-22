"""
Public IP and network geolocation provider using ip-api.com and ipify.
"""

from __future__ import annotations

import ipaddress
import logging
from typing import Optional

from app.api_tools.models import ApiResponse, NetworkInfo
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)


class NetworkProvider(BaseApiProvider):
    name = "ip-api.com"

    async def get_network_info(self, ip_address: Optional[str] = None) -> ApiResponse[NetworkInfo]:
        """Fetch public IP address, ISP, and approximate geographic network location."""
        target_ip = ip_address.strip() if ip_address else ""

        if target_ip:
            try:
                ip_obj = ipaddress.ip_address(target_ip)
                if ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_reserved:
                    return ApiResponse(
                        success=False,
                        error=f"Address '{target_ip}' is a private/local network IP. Public geolocation only applies to public internet IP addresses.",
                        source=self.name,
                    )
            except ValueError:
                return ApiResponse(
                    success=False,
                    error=f"Invalid IP address format: '{target_ip}'.",
                    source=self.name,
                )

        cache_key = f"network:{target_ip or 'self'}"
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
            # 1. Primary: ip-api.com
            url = f"{self.config.network_ip_api_url}/{target_ip}" if target_ip else f"{self.config.network_ip_api_url}/"
            resp = await self.client.get_json(url)

            if resp and resp.get("status") == "success":
                net_info = NetworkInfo(
                    public_ip=resp.get("query", ""),
                    city=resp.get("city", ""),
                    region=resp.get("regionName", ""),
                    country=resp.get("country", ""),
                    country_code=resp.get("countryCode", ""),
                    postal_code=resp.get("zip", ""),
                    latitude=resp.get("lat"),
                    longitude=resp.get("lon"),
                    timezone=resp.get("timezone", ""),
                    isp=resp.get("isp", ""),
                    organization=resp.get("org", ""),
                )
                await self.set_cached(cache_key, net_info, self.config.cache_ttl_network)
                return ApiResponse(
                    success=True,
                    data=net_info,
                    source=self.name,
                    cached=False,
                    summary=self._format_summary(net_info),
                )

        except Exception as e:
            logger.warning(f"ip-api.com lookup failed: {e}")

        # 2. Fallback: ipify
        try:
            resp_ipify = await self.client.get_json(f"{self.config.network_ipify_url}?format=json")
            if resp_ipify and "ip" in resp_ipify:
                net_info = NetworkInfo(
                    public_ip=resp_ipify["ip"],
                )
                await self.set_cached(cache_key, net_info, self.config.cache_ttl_network)
                return ApiResponse(
                    success=True,
                    data=net_info,
                    source="ipify",
                    cached=False,
                    summary=f"Public IP Address: {net_info.public_ip}",
                )
        except Exception as e:
            logger.warning(f"ipify fallback failed: {e}")

        return ApiResponse(
            success=False,
            error="Could not retrieve public IP or network information.",
            source=self.name,
        )

    def _format_summary(self, info: NetworkInfo) -> str:
        loc_parts = [p for p in [info.city, info.region, info.country] if p]
        location_str = f"Location: {', '.join(loc_parts)}" if loc_parts else ""
        isp_str = f"ISP: {info.isp}" if info.isp else ""
        tz_str = f"Timezone: {info.timezone}" if info.timezone else ""

        details = [p for p in [location_str, isp_str, tz_str] if p]
        details_str = f" ({', '.join(details)})" if details else ""
        return f"Public IP: {info.public_ip}{details_str}."
