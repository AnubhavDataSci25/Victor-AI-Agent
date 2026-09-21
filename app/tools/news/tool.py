"""
Victor 2.0 Current Affairs & Updates Tools.

Provides:
- current_affairs_get_updates: Fetches fresh categorized news (top 3 for a category, 1 for all).
- current_affairs_open_story: Opens a selected story from the ephemeral briefing in the browser.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.news.retriever import NewsRetriever
from app.news.session_cache import get_session_cache
from app.tools.base import BaseTool
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver
from app.tools.permissions import PermissionLevel

logger = logging.getLogger(__name__)


class CurrentAffairsGetUpdatesTool(BaseTool):
    name = "current_affairs_get_updates"
    description = (
        "Retrieves fresh, real-time current affairs and updates for a specific category "
        "(National, International, Technology, Sports, Stock Market, Finance, Education, "
        "Science, Business, Entertainment, Health) or all categories. "
        "Politics is strictly excluded. "
        "Returns the top 3 important stories for a category, or 1 per category if 'all' is requested. "
        "Keeps stories strictly in temporary in-memory session context for follow-up navigation."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": (
                    "The news category requested by the user, e.g., 'Technology', 'Sports', "
                    "'National', 'International', 'Stock Market', 'Finance', 'Education', "
                    "'Science', 'Business', 'Entertainment', 'Health', or 'all'. "
                    "Politics is strictly excluded. If omitted, Victor will ask the user for their preference."
                ),
            }
        },
    }

    def __init__(self, retriever: Optional[NewsRetriever] = None) -> None:
        self.retriever = retriever or NewsRetriever()

    async def execute(self, args: dict) -> str:
        category = args.get("category", "")
        return await self.retriever.get_updates(category)


class CurrentAffairsOpenStoryTool(BaseTool):
    name = "current_affairs_open_story"
    description = (
        "Opens a specific news story from the most recent current affairs briefing in the browser "
        "using its exact source URL. Use this when the user says 'Open the second story', "
        "'Open the sports one', 'Open this news in browser', or refers to an article by index or topic."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "story_index": {
                "type": "integer",
                "description": "The 1-based index of the story from the current briefing (e.g., 1, 2, 3).",
            },
            "category": {
                "type": "string",
                "description": "The category name of the story to open (e.g., 'Sports', 'Finance', 'Tech').",
            },
            "query": {
                "type": "string",
                "description": "A keyword or phrase from the story headline (e.g., 'iPhone', 'Sensex').",
            },
        },
    }

    def __init__(self) -> None:
        self.session_cache = get_session_cache()

    async def execute(self, args: dict) -> str:
        story_index = args.get("story_index")
        category = args.get("category")
        query = args.get("query")

        story = self.session_cache.find_story(
            story_index=story_index,
            category=category,
            query=query,
        )

        if not story:
            return (
                "Could not find a matching story from the recent news briefing. "
                "Please ask for fresh updates first, e.g. 'Give me some Tech news'."
            )

        # Open in Victor's browser driver
        try:
            driver = PlaywrightBrowserDriver()
            await driver.open_tab(story.url)
            return (
                f"Successfully opened story [{story.index}] '{story.title}' ({story.source}) in the browser."
            )
        except Exception as e:
            logger.error(f"[CurrentAffairs] Error opening story URL '{story.url}': {e}")
            return f"Found story '{story.title}', but encountered an error opening the browser: {str(e)}"
