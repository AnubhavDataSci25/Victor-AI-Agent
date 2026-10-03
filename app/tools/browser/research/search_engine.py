"""
Search execution provider for Browser Research Agent.
Executes multi-query discovery searches via fast HTTP and Playwright fallback.
"""

from __future__ import annotations

import logging
import re
import urllib.parse
from typing import List, Optional
import httpx
from pydantic import BaseModel

from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)


class SearchHit(BaseModel):
    """A single search result discovery hit."""
    title: str
    url: str
    snippet: str
    engine: str = "duckduckgo"


class ResearchSearchEngine:
    """Executes search queries to discover candidate product and review pages."""

    def __init__(self, driver: Optional[PlaywrightBrowserDriver] = None) -> None:
        self.driver = driver or PlaywrightBrowserDriver()
        self._http_client: Optional[httpx.AsyncClient] = None

    async def get_http_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            }
            timeout = httpx.Timeout(6.0, connect=3.0)
            self._http_client = httpx.AsyncClient(headers=headers, timeout=timeout, follow_redirects=True)
        return self._http_client

    async def search(self, query: str, limit: int = 5) -> List[SearchHit]:
        """Search across discovery engines, returning structured search hits."""
        hits: List[SearchHit] = []

        # 1. Fast HTTP search via DuckDuckGo HTML
        try:
            client = await self.get_http_client()
            url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
            resp = await client.post(
                "https://html.duckduckgo.com/html/",
                data={"q": query, "b": ""},
                timeout=5.0,
            )
            if resp.status_code == 200:
                hits = self._parse_ddg_html(resp.text)
        except Exception as e:
            logger.debug(f"[ResearchSearchEngine] Fast HTTP search failed for '{query}' ({e}); trying Playwright.")

        # 2. Fallback to Playwright browser search if HTTP failed or returned no results
        if not hits:
            try:
                page = await self.driver.get_page()
                url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(query)}"
                await page.goto(url, wait_until="domcontentloaded", timeout=8000)

                # Extract titles, links, and snippets
                results_data = await page.evaluate("""
                    () => {
                        const items = [];
                        const nodes = document.querySelectorAll('.result');
                        nodes.forEach(n => {
                            const titleEl = n.querySelector('.result__title a');
                            const snipEl = n.querySelector('.result__snippet');
                            if (titleEl) {
                                items.push({
                                    title: titleEl.innerText.trim(),
                                    url: titleEl.href,
                                    snippet: snipEl ? snipEl.innerText.trim() : ''
                                });
                            }
                        });
                        return items;
                    }
                """)
                for item in results_data:
                    clean_url = self._unwrap_ddg_url(item.get("url", ""))
                    if clean_url:
                        hits.append(SearchHit(
                            title=item.get("title", ""),
                            url=clean_url,
                            snippet=item.get("snippet", ""),
                            engine="duckduckgo_playwright",
                        ))
            except Exception as e:
                logger.error(f"[ResearchSearchEngine] Playwright search failed for '{query}': {e}")

        # Deduplicate hits by URL
        unique_hits: List[SearchHit] = []
        seen_urls = set()
        for h in hits:
            if h.url and h.url not in seen_urls:
                seen_urls.add(h.url)
                unique_hits.append(h)
                if len(unique_hits) >= limit:
                    break

        return unique_hits

    def _parse_ddg_html(self, html: str) -> List[SearchHit]:
        """Extract search results from DuckDuckGo HTML."""
        hits: List[SearchHit] = []
        # Pattern for result blocks
        # <a class="result__snippet" ... href="...">...</a> or <a class="result__url" ...>
        title_matches = re.finditer(
            r'<a[^>]+class=[\'"][^\'"]*result__snippet[^\'"]*[\'"][^>]+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        for m in title_matches:
            raw_url = m.group(1)
            raw_snip = re.sub(r"<[^>]+>", "", m.group(2)).strip()
            clean_url = self._unwrap_ddg_url(raw_url)
            if clean_url:
                hits.append(SearchHit(
                    title=raw_snip[:80],
                    url=clean_url,
                    snippet=raw_snip,
                    engine="duckduckgo_html",
                ))

        # Also parse result__title links
        link_matches = re.finditer(
            r'<a[^>]+class=[\'"][^\'"]*result__url[^\'"]*[\'"][^>]+href=[\'"]([^\'"]+)[\'"][^>]*>(.*?)</a>',
            html,
            re.DOTALL | re.IGNORECASE,
        )
        for lm in link_matches:
            raw_url = lm.group(1)
            raw_text = re.sub(r"<[^>]+>", "", lm.group(2)).strip()
            clean_url = self._unwrap_ddg_url(raw_url)
            if clean_url and not any(h.url == clean_url for h in hits):
                hits.append(SearchHit(
                    title=raw_text,
                    url=clean_url,
                    snippet=raw_text,
                    engine="duckduckgo_html",
                ))

        return hits

    def _unwrap_ddg_url(self, url: str) -> str:
        """Unwrap DuckDuckGo redirection wrapper (e.g. //duckduckgo.com/l/?uddg=...)."""
        if "uddg=" in url:
            try:
                parsed = urllib.parse.urlparse(url)
                params = urllib.parse.parse_qs(parsed.query)
                if "uddg" in params:
                    return urllib.parse.unquote(params["uddg"][0])
            except Exception:
                pass
        if url.startswith("//"):
            url = f"https:{url}"
        return url

    async def close(self) -> None:
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
