"""
Lightweight news retrieval pipeline for Victor's Current Affairs module.

Key Capabilities:
- Category resolution and natural language aliasing across 11 domains.
- Strict, zero-exception exclusion of Politics (query rejection & content filtering).
- Real-time RSS ingestion with sub-second execution (0 API keys required).
- Event deduplication across overlapping sources.
- Credible source prioritization.
- Dynamic ranking: 3 stories for single category, 1 story per category for 'all'.
- Ephemeral session caching with strict non-persistence.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import email.utils
import html
import logging
import re
from typing import Dict, List, Optional, Set, Tuple
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from app.news.models import NewsBriefing, NewsCategory, NewsStory
from app.news.session_cache import get_session_cache
from app.news.summarizer import NewsSummarizer

logger = logging.getLogger(__name__)

# Credible sources list for weighting/prioritization
CREDIBLE_SOURCES = {
    "reuters", "associated press", "ap news", "bbc", "the hindu", "the indian express",
    "economic times", "livemint", "ndtv", "business standard", "techcrunch", "wired",
    "the verge", "arstechnica", "nature", "science", "espn", "espncricinfo", "bloomberg",
    "cnbc", "financial times", "forbes", "hindustan times", "times of india", "gsmarena"
}

# Strict political keywords to discard from national/general updates
POLITICAL_KEYWORDS = {
    "bjp", "congress", "aap", "trinamool", "bsp", "sp party", "election rally", "poll rally",
    "lok sabha", "rajya sabha", "vote bank", "party worker", "party workers", "election campaign",
    "by-poll", "electoral", "seat sharing", "seat-sharing", "cabinet reshuffle", "mla", "mp party",
    "manifesto", "poll strategist", "voter turnout", "election commission notices", "assembly election"
}

# Category feed mappings (Google News RSS - Indian & Global editions)
CATEGORY_FEEDS: Dict[str, str] = {
    NewsCategory.NATIONAL.value: "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.INTERNATIONAL.value: "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.TECHNOLOGY.value: "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.SPORTS.value: "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.STOCK_MARKET.value: "https://news.google.com/rss/search?q=stock+market+india+sensex+nifty+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.FINANCE.value: "https://news.google.com/rss/search?q=finance+economy+banking+rbi+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.EDUCATION.value: "https://news.google.com/rss/search?q=education+universities+exams+research+when:2d&hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.SCIENCE.value: "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.BUSINESS.value: "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.ENTERTAINMENT.value: "https://news.google.com/rss/headlines/section/topic/ENTERTAINMENT?hl=en-IN&gl=IN&ceid=IN:en",
    NewsCategory.HEALTH.value: "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-IN&gl=IN&ceid=IN:en",
}

# Aliases for category identification
CATEGORY_ALIASES: Dict[str, str] = {
    "tech": NewsCategory.TECHNOLOGY.value,
    "technology": NewsCategory.TECHNOLOGY.value,
    "gadgets": NewsCategory.TECHNOLOGY.value,
    "ai": NewsCategory.TECHNOLOGY.value,
    "software": NewsCategory.TECHNOLOGY.value,
    "sports": NewsCategory.SPORTS.value,
    "sport": NewsCategory.SPORTS.value,
    "cricket": NewsCategory.SPORTS.value,
    "football": NewsCategory.SPORTS.value,
    "stock": NewsCategory.STOCK_MARKET.value,
    "stocks": NewsCategory.STOCK_MARKET.value,
    "stock market": NewsCategory.STOCK_MARKET.value,
    "market": NewsCategory.STOCK_MARKET.value,
    "markets": NewsCategory.STOCK_MARKET.value,
    "share market": NewsCategory.STOCK_MARKET.value,
    "finance": NewsCategory.FINANCE.value,
    "financial": NewsCategory.FINANCE.value,
    "economy": NewsCategory.FINANCE.value,
    "banking": NewsCategory.FINANCE.value,
    "education": NewsCategory.EDUCATION.value,
    "study": NewsCategory.EDUCATION.value,
    "academic": NewsCategory.EDUCATION.value,
    "exams": NewsCategory.EDUCATION.value,
    "science": NewsCategory.SCIENCE.value,
    "space": NewsCategory.SCIENCE.value,
    "astronomy": NewsCategory.SCIENCE.value,
    "business": NewsCategory.BUSINESS.value,
    "startups": NewsCategory.BUSINESS.value,
    "corporate": NewsCategory.BUSINESS.value,
    "biz": NewsCategory.BUSINESS.value,
    "entertainment": NewsCategory.ENTERTAINMENT.value,
    "movies": NewsCategory.ENTERTAINMENT.value,
    "cinema": NewsCategory.ENTERTAINMENT.value,
    "health": NewsCategory.HEALTH.value,
    "medical": NewsCategory.HEALTH.value,
    "wellness": NewsCategory.HEALTH.value,
    "national": NewsCategory.NATIONAL.value,
    "india": NewsCategory.NATIONAL.value,
    "country": NewsCategory.NATIONAL.value,
    "international": NewsCategory.INTERNATIONAL.value,
    "world": NewsCategory.INTERNATIONAL.value,
    "global": NewsCategory.INTERNATIONAL.value,
    "all": NewsCategory.ALL.value,
    "all categories": NewsCategory.ALL.value,
    "every category": NewsCategory.ALL.value,
    "everything": NewsCategory.ALL.value,
    "briefing": NewsCategory.ALL.value,
}

STOPWORDS = {
    "a", "an", "the", "in", "on", "at", "for", "to", "of", "and", "is", "are", "was",
    "were", "with", "by", "as", "from", "that", "this", "it", "new", "has", "have"
}


def resolve_category(category_input: Optional[str]) -> Tuple[Optional[str], bool]:
    """
    Resolves natural language category strings to normalized NewsCategory values.
    Returns (resolved_category, is_politics_rejected).
    """
    if not category_input or not category_input.strip():
        return None, False

    cleaned = category_input.strip().lower()

    # Strict check: Politics must be explicitly excluded
    if any(p in cleaned for p in ["politic", "election", "campaign", "poll"]):
        return None, True

    # Exact or alias match
    if cleaned in CATEGORY_ALIASES:
        return CATEGORY_ALIASES[cleaned], False

    # Partial substring match
    for alias, cat in CATEGORY_ALIASES.items():
        if alias in cleaned:
            return cat, False

    return None, False


def parse_rfc822_date(date_str: str) -> str:
    """Formats RFC 822 date strings into concise, user-friendly timestamps."""
    if not date_str:
        return "Recent"
    try:
        dt = email.utils.parsedate_to_datetime(date_str)
        now = datetime.now(dt.tzinfo)
        diff_hours = (now - dt).total_seconds() / 3600.0

        if 0 <= diff_hours < 1:
            mins = max(1, int(diff_hours * 60))
            return f"{mins}m ago"
        elif 1 <= diff_hours < 24:
            return f"{int(diff_hours)}h ago"
        elif 24 <= diff_hours < 48:
            return "Yesterday"
        else:
            return dt.strftime("%b %d, %Y")
    except Exception:
        return date_str[:16]


def is_political_content(title: str, summary: str = "") -> bool:
    """Detects partisan political campaigns and election rallies."""
    text = f"{title} {summary}".lower()
    return any(re.search(rf"\b{re.escape(kw)}\b", text) for kw in POLITICAL_KEYWORDS)


def _stem_word(w: str) -> str:
    """Simple suffix normalizer for headline tokens."""
    if w.endswith("ing") and len(w) > 5:
        return w[:-3]
    if w.endswith("ed") and len(w) > 4:
        return w[:-2]
    if w.endswith("es") and len(w) > 4:
        return w[:-2]
    if w.endswith("s") and len(w) > 3 and not w.endswith("ss"):
        return w[:-1]
    return w


def tokenize_title(title: str) -> Set[str]:
    """Tokenizes headlines for event deduplication."""
    clean = re.sub(r"[^\w\s]", " ", title.lower())
    words = clean.split()
    return {_stem_word(w) for w in words if w not in STOPWORDS and len(w) >= 2}


def are_stories_duplicate(title1: str, title2: str) -> bool:
    """Computes Jaccard word-similarity to detect same-event duplication."""
    t1 = tokenize_title(title1)
    t2 = tokenize_title(title2)
    if not t1 or not t2:
        return False
    intersection = t1.intersection(t2)
    union = t1.union(t2)
    similarity = len(intersection) / len(union)
    return (len(intersection) >= 3 and similarity >= 0.40) or similarity >= 0.50


class NewsRetriever:
    """Core retrieval engine for Victor's Current Affairs module."""

    def __init__(self, summarizer: Optional[NewsSummarizer] = None) -> None:
        self.summarizer = summarizer or NewsSummarizer()
        self.session_cache = get_session_cache()

    async def get_updates(self, category_query: Optional[str] = None) -> str:
        """
        Main entrypoint for fetching current affairs updates.
        - Identifies category or rejects politics.
        - Fetches fresh RSS items.
        - Deduplicates and ranks top stories.
        - Populates ephemeral session cache.
        - Returns structured briefing string.
        """
        resolved_category, is_politics = resolve_category(category_query)

        # 1. Politics Exclusion check
        if is_politics:
            return (
                "Sir, political news is explicitly excluded from my updates. "
                "I can provide updates on National, International, Technology, Sports, "
                "Stock Market, Finance, Education, Science, Business, Entertainment, or Health. "
                "Which one would you prefer?"
            )

        # 2. No category specified: prompt user
        if not resolved_category:
            return (
                "Sure, Sir. Which category would you like - National, International, Tech, "
                "Sports, Stock Market, Finance, Education, Science, Business, Entertainment, "
                "Health, or all categories?"
            )

        # 3. Retrieve stories based on scope (all categories vs single category)
        if resolved_category == NewsCategory.ALL.value:
            briefing = await self._retrieve_all_categories()
        else:
            briefing = await self._retrieve_single_category(resolved_category)

        # 4. Store in ephemeral session cache (strictly in-memory, zero permanent storage)
        self.session_cache.store_briefing(briefing)

        return briefing.format_response()

    async def _retrieve_single_category(self, category_name: str) -> NewsBriefing:
        """Retrieves top 3 curated stories for a specific category."""
        feed_url = CATEGORY_FEEDS.get(category_name)
        if not feed_url:
            return NewsBriefing(category_requested=category_name)

        raw_items = await self._fetch_feed(feed_url)
        filtered_items = self._filter_and_deduplicate(raw_items, limit=3)

        stories = []
        for idx, item in enumerate(filtered_items, start=1):
            summary = await self.summarizer.summarize(
                headline=item["title"],
                source=item["source"],
                raw_snippet=item["description"],
                cluster_headlines=item.get("cluster_headlines", []),
            )
            stories.append(
                NewsStory(
                    index=idx,
                    category=category_name,
                    title=item["title"],
                    source=item["source"],
                    published=parse_rfc822_date(item["pubDate"]),
                    summary=summary,
                    url=item["link"],
                )
            )

        return NewsBriefing(category_requested=category_name, stories=stories)

    async def _retrieve_all_categories(self) -> NewsBriefing:
        """
        Retrieves 1 important story per configured category to minimize
        latency and compute consumption.
        """
        all_stories: List[NewsStory] = []
        global_idx = 1

        # Run concurrent fetches across categories with small timeout
        categories_to_fetch = [
            cat.value for cat in NewsCategory if cat != NewsCategory.ALL
        ]

        tasks = [
            self._fetch_category_single_story(cat_name)
            for cat_name in categories_to_fetch
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            if isinstance(res, dict) and res.get("story"):
                item = res["story"]
                cat_name = res["category"]
                summary = await self.summarizer.summarize(
                    headline=item["title"],
                    source=item["source"],
                    raw_snippet=item["description"],
                )
                all_stories.append(
                    NewsStory(
                        index=global_idx,
                        category=cat_name,
                        title=item["title"],
                        source=item["source"],
                        published=parse_rfc822_date(item["pubDate"]),
                        summary=summary,
                        url=item["link"],
                    )
                )
                global_idx += 1

        return NewsBriefing(category_requested="All Categories", stories=all_stories)

    async def _fetch_category_single_story(self, category_name: str) -> Optional[dict]:
        """Fetches 1 representative story for a category."""
        feed_url = CATEGORY_FEEDS.get(category_name)
        if not feed_url:
            return None
        try:
            items = await self._fetch_feed(feed_url)
            filtered = self._filter_and_deduplicate(items, limit=1)
            if filtered:
                return {"category": category_name, "story": filtered[0]}
        except Exception as e:
            logger.debug(f"[NewsRetriever] Failed single story fetch for {category_name}: {e}")
        return None

    async def _fetch_feed(self, url: str) -> List[dict]:
        """Fetches and parses an RSS feed asynchronously without blocking the loop."""
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self._sync_fetch_feed, url)

    def _sync_fetch_feed(self, url: str) -> List[dict]:
        """Synchronous HTTP fetch and XML parsing for RSS feeds."""
        items: List[dict] = []
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Victor/2.0"},
        )
        try:
            with urllib.request.urlopen(req, timeout=4.5) as resp:
                content = resp.read()
                root = ET.fromstring(content)
                for item_el in root.findall(".//item"):
                    raw_title = item_el.findtext("title", "")
                    link = item_el.findtext("link", "")
                    pub_date = item_el.findtext("pubDate", "")
                    description = item_el.findtext("description", "")
                    source_el = item_el.find("source")
                    source_text = source_el.text if source_el is not None else ""

                    # Split publisher from headline if present (e.g. 'Headline - SourceName')
                    headline = raw_title
                    if " - " in raw_title:
                        parts = raw_title.rsplit(" - ", 1)
                        headline = parts[0].strip()
                        if not source_text:
                            source_text = parts[1].strip()

                    # Extract cluster headlines from Google News description HTML
                    cluster_headlines = [headline]
                    if "<ol>" in description:
                        extra_titles = re.findall(r'<a\s+[^>]*>([^<]+)</a>', description)
                        for t in extra_titles:
                            clean_t = html.unescape(t).strip()
                            if clean_t and clean_t not in cluster_headlines:
                                cluster_headlines.append(clean_t)

                    items.append({
                        "title": html.unescape(headline),
                        "link": link,
                        "pubDate": pub_date,
                        "source": html.unescape(source_text),
                        "description": description,
                        "cluster_headlines": cluster_headlines,
                    })
        except Exception as e:
            logger.warning(f"[NewsRetriever] Feed fetch error for {url}: {e}")
        return items

    def _filter_and_deduplicate(self, items: List[dict], limit: int = 3) -> List[dict]:
        """
        Applies:
        1. Political news filter (strictly discards political items).
        2. Credible source ranking.
        3. Event deduplication.
        """
        # Step 1: Filter out political content
        non_political = [
            item for item in items
            if not is_political_content(item["title"], item.get("description", ""))
        ]

        # Step 2: Sort prioritizing credible news sources
        def source_weight(it: dict) -> int:
            src = it.get("source", "").lower()
            return 2 if any(cs in src for cs in CREDIBLE_SOURCES) else 1

        scored = sorted(non_political, key=source_weight, reverse=True)

        # Step 3: Event deduplication
        deduped: List[dict] = []
        for item in scored:
            title = item["title"]
            is_dup = False
            for existing in deduped:
                if are_stories_duplicate(title, existing["title"]):
                    is_dup = True
                    break
            if not is_dup:
                deduped.append(item)
            if len(deduped) >= limit:
                break

        return deduped
