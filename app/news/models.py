"""
Data models for Victor's Current Affairs & Updates module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import time
from typing import List, Optional


class NewsCategory(str, Enum):
    NATIONAL = "National"
    INTERNATIONAL = "International"
    TECHNOLOGY = "Technology"
    SPORTS = "Sports"
    STOCK_MARKET = "Stock Market"
    FINANCE = "Finance"
    EDUCATION = "Education"
    SCIENCE = "Science"
    BUSINESS = "Business"
    ENTERTAINMENT = "Entertainment"
    HEALTH = "Health"
    ALL = "all"


@dataclass
class NewsStory:
    """Represents an individual curated news story."""
    index: int
    category: str
    title: str
    source: str
    published: str
    summary: str
    url: str

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "category": self.category,
            "title": self.title,
            "source": self.source,
            "published": self.published,
            "summary": self.summary,
            "url": self.url,
        }

    def format_display(self) -> str:
        """Formats a compact, human-readable representation for Victor."""
        return (
            f"[{self.index}] {self.category}: {self.title}\n"
            f"    Source: {self.source} | Date: {self.published}\n"
            f"    Summary: {self.summary}\n"
            f"    URL: {self.url}"
        )


@dataclass
class NewsBriefing:
    """Represents a full briefing containing multiple curated stories."""
    category_requested: str
    stories: List[NewsStory] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def is_empty(self) -> bool:
        return len(self.stories) == 0

    def format_response(self) -> str:
        """Formats the briefing output returned to Gemini Live and Victor."""
        if not self.stories:
            return f"No current updates found for '{self.category_requested}'."

        header = f"[Current Affairs Briefing: {self.category_requested.title()} ({len(self.stories)} updates)]\n"
        story_blocks = [s.format_display() for s in self.stories]
        footer = (
            "\n\nTip: Say 'Open the second story' or 'Open the [Category] one' to view any article in the browser."
        )
        return header + "\n\n".join(story_blocks) + footer
