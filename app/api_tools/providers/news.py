"""
News headlines provider using Google News RSS and Hacker News public APIs.
"""

from __future__ import annotations

import html
import logging
import re
from typing import Dict, List, Optional
import xml.etree.ElementTree as ET

from app.api_tools.models import ApiResponse, NewsFeed, NewsItem
from app.api_tools.providers.base import BaseApiProvider

logger = logging.getLogger(__name__)

# Category mapping to Google News RSS feeds
CATEGORY_RSS_URLS: Dict[str, str] = {
    "general": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "world": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    "business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
    "technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    "tech": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    "science": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
    "sports": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-US&gl=US&ceid=US:en",
    "entertainment": "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-US&gl=US&ceid=US:en",
    "health": "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en",
}


def clean_headline(raw_title: str) -> tuple[str, str]:
    """Extract clean title and publication source from RSS title (e.g. 'Headline - Source')."""
    decoded = html.unescape(raw_title.strip())
    if " - " in decoded:
        parts = decoded.rsplit(" - ", 1)
        title = parts[0].strip()
        source = parts[1].strip()
        return title, source
    return decoded, ""


class NewsProvider(BaseApiProvider):
    name = "Public News Feed"

    async def get_headlines(
        self,
        category: str = "general",
        limit: int = 5,
    ) -> ApiResponse[NewsFeed]:
        """Fetch latest news headlines for a category."""
        cat_clean = category.strip().lower()
        limit = max(1, min(limit, 10))

        cache_key = f"news:{cat_clean}:{limit}"
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

        # 1. Tech category special: Hacker News top stories
        if cat_clean in ("hackernews", "hn"):
            return await self._get_hackernews(limit, cache_key)

        # 2. General / Categorized RSS
        rss_url = CATEGORY_RSS_URLS.get(cat_clean, CATEGORY_RSS_URLS["general"])
        try:
            xml_text = await self.client.get_text(rss_url)
            root = ET.fromstring(xml_text)
            channel = root.find("channel")
            if channel is None:
                return ApiResponse(
                    success=False,
                    error="Unable to parse news feed from provider.",
                    source=self.name,
                )

            items: List[NewsItem] = []
            for item_elem in channel.findall("item"):
                title_elem = item_elem.find("title")
                link_elem = item_elem.find("link")
                pub_elem = item_elem.find("pubDate")
                desc_elem = item_elem.find("description")

                if title_elem is None or not title_elem.text:
                    continue

                raw_title = title_elem.text
                clean_title, source = clean_headline(raw_title)
                link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
                pub_date = pub_elem.text.strip() if pub_elem is not None and pub_elem.text else ""

                snippet = ""
                if desc_elem is not None and desc_elem.text:
                    clean_desc = re.sub(r"<[^>]+>", "", desc_elem.text)
                    snippet = html.unescape(clean_desc).strip()[:150]

                items.append(
                    NewsItem(
                        title=clean_title,
                        source_name=source or "Google News",
                        url=link,
                        published_at=pub_date,
                        snippet=snippet,
                    )
                )

                if len(items) >= limit:
                    break

            if not items:
                return ApiResponse(
                    success=False,
                    error=f"No headlines found for category '{category}'.",
                    source=self.name,
                )

            feed = NewsFeed(category=cat_clean.capitalize(), items=items)
            await self.set_cached(cache_key, feed, self.config.cache_ttl_news)

            summary = self._format_summary(feed)
            return ApiResponse(
                success=True,
                data=feed,
                source="Google News RSS",
                cached=False,
                summary=summary,
            )

        except Exception as exc:
            logger.error(f"Error fetching news headlines for {cat_clean}: {exc}")
            # Try Hacker News as fallback for tech news
            if cat_clean in ("technology", "tech"):
                return await self._get_hackernews(limit, cache_key)

            return ApiResponse(
                success=False,
                error=f"Failed to fetch news headlines: {exc}",
                source=self.name,
            )

    async def _get_hackernews(self, limit: int, cache_key: str) -> ApiResponse[NewsFeed]:
        """Fetch top tech stories from Hacker News official Firebase REST API."""
        try:
            top_ids_url = f"{self.config.news_hackernews_url}/topstories.json"
            top_ids = await self.client.get_json(top_ids_url)
            if not top_ids or not isinstance(top_ids, list):
                return ApiResponse(
                    success=False,
                    error="Hacker News feed currently unavailable.",
                    source="Hacker News API",
                )

            items: List[NewsItem] = []
            for story_id in top_ids[:limit]:
                item_url = f"{self.config.news_hackernews_url}/item/{story_id}.json"
                story_data = await self.client.get_json(item_url)
                if story_data and "title" in story_data:
                    items.append(
                        NewsItem(
                            title=story_data.get("title", ""),
                            source_name="Hacker News",
                            url=story_data.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                            published_at="",
                            snippet=f"Score: {story_data.get('score', 0)} | By: {story_data.get('by', 'anonymous')}",
                        )
                    )

            feed = NewsFeed(category="Tech / Hacker News", items=items)
            await self.set_cached(cache_key, feed, self.config.cache_ttl_news)
            return ApiResponse(
                success=True,
                data=feed,
                source="Hacker News API",
                cached=False,
                summary=self._format_summary(feed),
            )
        except Exception as exc:
            return ApiResponse(
                success=False,
                error=f"Hacker News fetch error: {exc}",
                source="Hacker News API",
            )

    def _format_summary(self, feed: NewsFeed) -> str:
        lines = [f"Latest {feed.category} Headlines:"]
        for idx, item in enumerate(feed.items, 1):
            src = f" ({item.source_name})" if item.source_name else ""
            lines.append(f"{idx}. {item.title}{src}")
        return "\n".join(lines)
