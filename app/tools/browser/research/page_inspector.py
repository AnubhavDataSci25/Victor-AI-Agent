"""
Page inspector for Browser Research Agent.
Fast multi-source inspection with HTTP fallback to Playwright, JSON-LD extraction, and in-memory caching.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse
from typing import Any, Dict, Optional
import httpx

from app.tools.browser.playwright_driver import PlaywrightBrowserDriver
from app.tools.browser.research.models import CandidateProduct, PriceDetail
from app.tools.browser.research.price_extractor import PriceExtractor

logger = logging.getLogger(__name__)


class PageInspector:
    """Inspects web pages to extract verified product specifications, pricing, and stock status."""

    def __init__(self, driver: Optional[PlaywrightBrowserDriver] = None) -> None:
        self.driver = driver or PlaywrightBrowserDriver()
        self._page_cache: Dict[str, CandidateProduct] = {}
        self._http_client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            timeout = httpx.Timeout(6.0, connect=3.0)
            self._http_client = httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True)
        return self._http_client

    def is_safe_url(self, url: str) -> bool:
        """Ensure URL is http/https and does not target internal or unsafe addresses."""
        try:
            parsed = urllib.parse.urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return False
            hostname = (parsed.hostname or "").lower()
            if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
                return False
            if hostname.startswith(("192.168.", "10.", "172.16.", "169.254.")):
                return False
            return True
        except Exception:
            return False

    def identify_retailer(self, url: str) -> str:
        """Map URL domain to recognized retailer brand."""
        try:
            parsed = urllib.parse.urlparse(url)
            host = (parsed.hostname or "").lower()
            if "amazon.in" in host:
                return "Amazon India"
            elif "amazon." in host:
                return "Amazon"
            elif "flipkart.com" in host:
                return "Flipkart"
            elif "croma.com" in host:
                return "Croma"
            elif "reliancedigital.in" in host:
                return "Reliance Digital"
            elif "vijaysales.com" in host:
                return "Vijay Sales"
            elif "tatacliq.com" in host:
                return "Tata CLiQ"
            elif "asus.com" in host:
                return "ASUS Store"
            elif "apple.com" in host:
                return "Apple Store"
            elif "dell.com" in host:
                return "Dell Store"
            elif "lenovo.com" in host:
                return "Lenovo Store"
            elif "hp.com" in host:
                return "HP Store"
            # Fallback to domain root
            parts = host.replace("www.", "").split(".")
            return parts[0].capitalize() if parts else "Web Retailer"
        except Exception:
            return "Web Retailer"

    async def inspect_url(self, url: str, snippet_title: str = "", snippet_text: str = "") -> Optional[CandidateProduct]:
        """
        Inspect a candidate URL to extract verified product details.
        Uses in-memory cache, fast HTTP JSON-LD parsing, or Playwright DOM inspection.
        """
        if not self.is_safe_url(url):
            return None

        # 1. Check in-memory cache
        if url in self._page_cache:
            return self._page_cache[url]

        retailer = self.identify_retailer(url)
        candidate: Optional[CandidateProduct] = None

        # 2. Fast HTTP fetch & JSON-LD / Meta extraction
        try:
            client = await self.get_http_client()
            resp = await client.get(url)
            if resp.status_code == 200:
                candidate = self._parse_html(resp.text, url, retailer, snippet_title)
        except Exception as e:
            logger.debug(f"[PageInspector] Fast HTTP inspect failed for {url} ({e}); trying browser driver.")

        # 3. If HTTP was blocked, empty, or failed to yield product info, inspect via Playwright
        if not candidate or candidate.price.selling_price == 0.0:
            snippet_price = PriceExtractor.parse_price(snippet_text) if snippet_text else PriceDetail()
            is_driver_alive = bool(getattr(self.driver, "browser", None) and self.driver.browser.is_connected())
            # If search snippet already yielded a valid selling price and browser driver is not actively running,
            # use snippet candidate to avoid cold-launching heavy browser instance and timing out
            if snippet_price.selling_price > 0.0 and not is_driver_alive:
                candidate = CandidateProduct(
                    candidate_id=f"snippet_{abs(hash(url)) % 10000}",
                    product_name=snippet_title or "Unverified Product",
                    retailer=retailer,
                    source_url=url,
                    price=snippet_price,
                    verification_status="unverified_snippet",
                    confidence=0.5,
                    provenance=f"Extracted from search snippet: {snippet_text[:120]}...",
                )
            else:
                try:
                    page = await self.driver.get_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=6000)
                    body_text = await page.evaluate("document.body.innerText")
                    title = await page.title()
                    candidate = self._parse_text(body_text, url, retailer, title or snippet_title)
                except Exception as e:
                    logger.debug(f"[PageInspector] Playwright inspect failed for {url}: {e}")

        # 4. Fallback to search snippet if page was completely unreachable
        if not candidate:
            price = PriceExtractor.parse_price(snippet_text)
            candidate = CandidateProduct(
                candidate_id=f"snippet_{abs(hash(url)) % 10000}",
                product_name=snippet_title or "Unverified Product",
                retailer=retailer,
                source_url=url,
                price=price,
                verification_status="unverified_snippet",
                confidence=0.4,
                provenance=f"Extracted from search snippet: {snippet_text[:120]}...",
            )

        self._page_cache[url] = candidate
        return candidate

    def _parse_html(self, html: str, url: str, retailer: str, default_title: str) -> Optional[CandidateProduct]:
        """Extract structured product information from HTML using JSON-LD schema or OpenGraph tags."""
        # 1. JSON-LD parsing
        jsonld_matches = re.findall(r'<script[^>]*type=[\'"]application/ld\+json[\'"][^>]*>(.*?)</script>', html, re.DOTALL | re.IGNORECASE)
        for block in jsonld_matches:
            try:
                data = json.loads(block.strip())
                # Handle list of items or single item
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if isinstance(item, dict) and item.get("@type") in ("Product", "IndividualProduct"):
                        name = item.get("name", default_title)
                        sku = item.get("sku") or item.get("model")
                        offers = item.get("offers", {})
                        if isinstance(offers, list) and offers:
                            offers = offers[0]
                        price_val = 0.0
                        if isinstance(offers, dict):
                            raw_p = offers.get("price") or offers.get("lowPrice")
                            if raw_p:
                                try:
                                    price_val = float(str(raw_p).replace(",", ""))
                                except ValueError:
                                    pass
                            avail = str(offers.get("availability", "")).lower()
                            in_stock = "instock" in avail
                        else:
                            in_stock = True

                        if price_val > 0.0:
                            price_detail = PriceDetail(
                                selling_price=price_val,
                                effective_price=price_val,
                                unconditional_price=price_val,
                            )
                            specs = self._extract_specs(f"{name} {item.get('description', '')}")
                            return CandidateProduct(
                                candidate_id=f"cand_{abs(hash(url)) % 10000}",
                                product_name=name,
                                exact_model_or_sku=str(sku) if sku else None,
                                retailer=retailer,
                                source_url=url,
                                price=price_detail,
                                availability="in_stock" if in_stock else "out_of_stock",
                                specs=specs,
                                verification_status="verified_page",
                                confidence=0.95,
                                provenance=f"Verified via JSON-LD on {retailer}",
                            )
            except Exception:
                continue

        # 2. OpenGraph / Regex extraction
        title_match = re.search(r"<title>(.*?)</title>", html, re.IGNORECASE)
        title = title_match.group(1).strip() if title_match else default_title
        
        # Clean HTML tags to extract raw text
        clean_text = re.sub(r"<script.*?</script>", " ", html, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r"<style.*?</style>", " ", clean_text, flags=re.DOTALL | re.IGNORECASE)
        clean_text = re.sub(r"<[^>]+>", " ", clean_text)
        clean_text = " ".join(clean_text.split())

        return self._parse_text(clean_text, url, retailer, title)

    def _parse_text(self, text: str, url: str, retailer: str, title: str) -> CandidateProduct:
        """Parse raw text representation of product page."""
        price = PriceExtractor.parse_price(text)
        avail = PriceExtractor.check_availability(text)
        specs = self._extract_specs(f"{title} {text[:2000]}")

        # Check for model SKU in title or text
        sku_match = re.search(r"\b([A-Za-z]{2,5}[- ]?\d{4,5}[A-Za-z0-9]*)\b", title)
        sku = sku_match.group(1) if sku_match else None

        return CandidateProduct(
            candidate_id=f"cand_{abs(hash(url)) % 10000}",
            product_name=title[:120],
            exact_model_or_sku=sku,
            retailer=retailer,
            source_url=url,
            price=price,
            availability=avail,
            specs=specs,
            verification_status="verified_page" if price.selling_price > 0 else "unverified_snippet",
            confidence=0.85 if price.selling_price > 0 else 0.5,
            provenance=f"Inspected page text on {retailer}",
        )

    def _extract_specs(self, text: str) -> Dict[str, Any]:
        """Extract RAM, Storage, and CPU from page text."""
        specs: Dict[str, Any] = {}

        # RAM
        ram_m = re.search(r"\b(\d{1,2})\s*(?:GB|gb)\s*(?:RAM|DDR|LPDDR|Memory)?\b", text, re.IGNORECASE)
        if ram_m:
            try:
                specs["ram_gb"] = int(ram_m.group(1))
            except ValueError:
                pass

        # Storage
        tb_m = re.search(r"\b(\d{1,2})\s*(?:TB|tb)\s*(?:SSD|Storage|ROM)?\b", text, re.IGNORECASE)
        if tb_m:
            try:
                specs["storage_gb"] = int(tb_m.group(1)) * 1024
            except ValueError:
                pass
        else:
            gb_m = re.search(r"\b(128|256|512)\s*(?:GB|gb)\s*(?:SSD|Storage|ROM)?\b", text, re.IGNORECASE)
            if gb_m:
                try:
                    specs["storage_gb"] = int(gb_m.group(1))
                except ValueError:
                    pass

        # CPU
        for cpu_kw in ("Core Ultra 7", "Core Ultra 5", "i9", "i7", "i5", "i3", "Ryzen 9", "Ryzen 7", "Ryzen 5", "M3", "M2", "M1"):
            if re.search(rf"\b{re.escape(cpu_kw)}\b", text, re.IGNORECASE):
                specs["cpu"] = cpu_kw
                break

        return specs

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
