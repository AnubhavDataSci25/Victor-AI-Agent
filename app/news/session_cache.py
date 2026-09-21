"""
Ephemeral session cache for Victor's Current Affairs module.

STRICT ZERO-STORAGE GUARANTEE:
All news stories are stored strictly in-memory within this ephemeral cache
for the duration of the current interaction to support follow-up requests
(e.g., "Open the second one", "Open the sports story").
NO articles, URLs, or summaries are ever written to Victor's permanent
MemoryManager, SQLite database (config/memory.db), files, or long-term disk.
"""

from __future__ import annotations

import logging
import time
from typing import List, Optional

from app.news.models import NewsBriefing, NewsStory

logger = logging.getLogger(__name__)


class NewsSessionCache:
    """In-memory, ephemeral cache holding the latest news briefing."""

    DEFAULT_TTL_SECONDS = 600  # 10 minutes

    def __init__(self, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self.ttl_seconds = ttl_seconds
        self._current_briefing: Optional[NewsBriefing] = None
        self._last_updated: float = 0.0

    def store_briefing(self, briefing: NewsBriefing) -> None:
        """Stores a fresh briefing in memory, replacing previous ephemeral data."""
        self._current_briefing = briefing
        self._last_updated = time.time()
        logger.debug(
            f"[NewsCache] Cached {len(briefing.stories)} ephemeral stories for "
            f"category '{briefing.category_requested}'."
        )

    def is_expired(self) -> bool:
        """Returns True if the cached briefing has expired or does not exist."""
        if not self._current_briefing:
            return True
        return (time.time() - self._last_updated) > self.ttl_seconds

    def get_briefing(self) -> Optional[NewsBriefing]:
        """Returns active briefing if not expired, else None."""
        if self.is_expired():
            return None
        return self._current_briefing

    def get_stories(self) -> List[NewsStory]:
        """Returns active cached stories if not expired."""
        briefing = self.get_briefing()
        return briefing.stories if briefing else []

    def get_by_index(self, index: int) -> Optional[NewsStory]:
        """
        Retrieves a story by 1-based index (e.g. 1, 2, 3).
        Matches user prompts like 'Open the second story'.
        """
        for story in self.get_stories():
            if story.index == index:
                return story
        return None

    def get_by_category(self, category_name: str) -> Optional[NewsStory]:
        """
        Retrieves a story by category name (e.g. 'sports', 'finance').
        Matches user prompts like 'Open the Sports one'.
        """
        if not category_name:
            return None
        target = category_name.strip().lower()
        for story in self.get_stories():
            if story.category.lower() == target or target in story.category.lower():
                return story
        return None

    def find_story(
        self,
        story_index: Optional[int] = None,
        category: Optional[str] = None,
        query: Optional[str] = None,
    ) -> Optional[NewsStory]:
        """
        Unified finder supporting index, category, or keyword query matching.
        """
        if self.is_expired():
            return None

        # 1. Direct index lookup
        if story_index is not None and story_index > 0:
            found = self.get_by_index(story_index)
            if found:
                return found

        # 2. Category lookup
        if category:
            found = self.get_by_category(category)
            if found:
                return found

        # 3. Fuzzy headline/query matching
        if query:
            q = query.strip().lower()
            for story in self.get_stories():
                if q in story.title.lower() or q in story.summary.lower():
                    return story

        # 4. Fallback: if only 1 story exists in cache, return it
        stories = self.get_stories()
        if len(stories) == 1:
            return stories[0]

        return None

    def clear(self) -> None:
        """Explicitly purges all cached news stories from memory."""
        self._current_briefing = None
        self._last_updated = 0.0
        logger.debug("[NewsCache] Ephemeral news cache cleared.")


# Module singleton
_session_cache: Optional[NewsSessionCache] = None


def get_session_cache() -> NewsSessionCache:
    """Returns the shared in-memory singleton cache."""
    global _session_cache
    if _session_cache is None:
        _session_cache = NewsSessionCache()
    return _session_cache
