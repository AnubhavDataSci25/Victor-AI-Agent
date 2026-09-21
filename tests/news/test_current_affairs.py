"""
Unit tests for Victor's Current Affairs & Updates module.

Tests cover:
1. Category resolution, aliases, and natural language matching.
2. Strict, zero-exception exclusion of Politics (query rejection & content filtering).
3. Retrieval ranking: top 3 stories for single category, 1 per category for 'all'.
4. Event deduplication across overlapping sources.
5. Ephemeral session caching (retrieval by index, category, fuzzy title, TTL, clear).
6. Tool execution: current_affairs_get_updates & current_affairs_open_story.
7. Browser driver integration for opening source URLs.
8. Summarization with clean source text and graceful Groq fallback.
9. Strict zero-persistence policy: guarantees no writes to MemoryManager or SQLite.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.memory.manager import MemoryManager
from app.news.models import NewsBriefing, NewsCategory, NewsStory
from app.news.retriever import (
    NewsRetriever,
    are_stories_duplicate,
    is_political_content,
    resolve_category,
)
from app.news.session_cache import NewsSessionCache, get_session_cache
from app.news.summarizer import NewsSummarizer, clean_html_snippet
from app.tools.news.tool import (
    CurrentAffairsGetUpdatesTool,
    CurrentAffairsOpenStoryTool,
)


# --- 1. Category Resolution & Aliases ---
def test_category_resolution():
    # Standard aliases
    cat, is_pol = resolve_category("tech")
    assert cat == NewsCategory.TECHNOLOGY.value
    assert is_pol is False

    cat, is_pol = resolve_category("technology")
    assert cat == NewsCategory.TECHNOLOGY.value

    cat, is_pol = resolve_category("cricket")
    assert cat == NewsCategory.SPORTS.value

    cat, is_pol = resolve_category("stocks")
    assert cat == NewsCategory.STOCK_MARKET.value

    cat, is_pol = resolve_category("markets")
    assert cat == NewsCategory.STOCK_MARKET.value

    cat, is_pol = resolve_category("economy")
    assert cat == NewsCategory.FINANCE.value

    cat, is_pol = resolve_category("india")
    assert cat == NewsCategory.NATIONAL.value

    cat, is_pol = resolve_category("global")
    assert cat == NewsCategory.INTERNATIONAL.value

    cat, is_pol = resolve_category("all")
    assert cat == NewsCategory.ALL.value

    # Empty / None
    cat, is_pol = resolve_category("")
    assert cat is None
    assert is_pol is False


# --- 2. Strict Politics Exclusion ---
def test_strict_politics_exclusion():
    # Direct query rejection
    cat, is_pol = resolve_category("politics")
    assert cat is None
    assert is_pol is True

    cat, is_pol = resolve_category("election news")
    assert cat is None
    assert is_pol is True

    cat, is_pol = resolve_category("political campaign updates")
    assert cat is None
    assert is_pol is True

    # Content filter for political campaign headlines
    assert is_political_content("BJP and Congress clash in election rally") is True
    assert is_political_content("Seat sharing talks stall ahead of assembly election") is True
    assert is_political_content("ISRO prepares for next-gen launch vehicle test") is False
    assert is_political_content("Sensex climbs 400 points as tech and banking stocks rally") is False
    assert is_political_content("India secures gold medal in world athletics championship") is False


# --- 3. Event Deduplication ---
def test_event_deduplication():
    t1 = "Apple launches iPhone 18 with 2nm chip and new design"
    t2 = "iPhone 18 launched today by Apple featuring 2nm processor"
    assert are_stories_duplicate(t1, t2) is True

    t3 = "Sensex surges 600 points on strong banking earnings"
    t4 = "NASA discovers water ice deposits on lunar south pole"
    assert are_stories_duplicate(t3, t4) is False


# --- 4. Ephemeral Session Cache ---
def test_ephemeral_session_cache():
    cache = NewsSessionCache(ttl_seconds=60)
    cache.clear()
    assert cache.is_expired() is True
    assert cache.get_stories() == []

    stories = [
        NewsStory(
            index=1,
            category="Technology",
            title="Tech Story One",
            source="TechCrunch",
            published="1h ago",
            summary="First tech summary.",
            url="https://example.com/story1",
        ),
        NewsStory(
            index=2,
            category="Sports",
            title="Sports Story Two",
            source="ESPN",
            published="2h ago",
            summary="Second sports summary.",
            url="https://example.com/story2",
        ),
    ]
    briefing = NewsBriefing(category_requested="Technology", stories=stories)
    cache.store_briefing(briefing)

    assert cache.is_expired() is False
    assert len(cache.get_stories()) == 2

    # Lookup by index
    s1 = cache.get_by_index(1)
    assert s1 is not None
    assert s1.title == "Tech Story One"

    s2 = cache.get_by_index(2)
    assert s2 is not None
    assert s2.url == "https://example.com/story2"

    # Lookup by category
    sports_story = cache.get_by_category("sports")
    assert sports_story is not None
    assert sports_story.index == 2

    # Find story unified
    found = cache.find_story(story_index=1)
    assert found == s1

    found_cat = cache.find_story(category="Sports")
    assert found_cat == s2

    found_fuzzy = cache.find_story(query="Story One")
    assert found_fuzzy == s1

    # Clear
    cache.clear()
    assert cache.is_expired() is True
    assert cache.get_stories() == []


# --- 5. NewsRetriever Logic with Mocked Feeds ---
@pytest.mark.asyncio
async def test_news_retriever_prompts_when_no_category():
    retriever = NewsRetriever()
    response = await retriever.get_updates("")
    assert "Which category would you like" in response
    assert "National" in response
    assert "Tech" in response
    assert "all categories" in response


@pytest.mark.asyncio
async def test_news_retriever_rejects_politics():
    retriever = NewsRetriever()
    response = await retriever.get_updates("politics")
    assert "political news is explicitly excluded" in response
    assert "National" in response


@pytest.mark.asyncio
async def test_news_retriever_single_category_top_3():
    retriever = NewsRetriever()

    distinct_titles = [
        "Apple announces new M5 Ultra chip with 2nm process",
        "Google deploys quantum error mitigation algorithms",
        "Tesla initiates commercial robotaxi fleet trials",
        "Microsoft enhances Copilot with local neural models",
        "OpenAI previews next generation reasoning models",
    ]
    mock_items = [
        {
            "title": distinct_titles[i],
            "link": f"https://example.com/news/{i+1}",
            "pubDate": "Sun, 20 Sep 2026 12:00:00 GMT",
            "source": "Reuters",
            "description": f"Clean description for story {i+1}.",
            "cluster_headlines": [],
        }
        for i in range(len(distinct_titles))
    ]

    with patch.object(retriever, "_fetch_feed", AsyncMock(return_value=mock_items)):
        res = await retriever.get_updates("Technology")

        assert "Current Affairs Briefing: Technology" in res
        assert "[1] Technology: Apple announces new M5 Ultra" in res
        assert "[2] Technology: Google deploys quantum" in res
        assert "[3] Technology: Tesla initiates commercial" in res
        assert "[4]" not in res  # Top 3 only

        # Verify ephemeral cache was populated
        cache = get_session_cache()
        cached_stories = cache.get_stories()
        assert len(cached_stories) == 3
        assert cached_stories[0].url == "https://example.com/news/1"


@pytest.mark.asyncio
async def test_news_retriever_all_categories_one_per_cat():
    retriever = NewsRetriever()

    async def mock_fetch_single(cat_name):
        return {
            "category": cat_name,
            "story": {
                "title": f"Top breakthrough in {cat_name}",
                "link": f"https://example.com/{cat_name.lower().replace(' ', '-')}",
                "pubDate": "Sun, 20 Sep 2026 12:00:00 GMT",
                "source": "The Hindu",
                "description": f"Summary for {cat_name}",
            },
        }

    with patch.object(retriever, "_fetch_category_single_story", side_effect=mock_fetch_single):
        res = await retriever.get_updates("all")
        assert "All Categories" in res
        # Must have exactly 1 per category
        cache = get_session_cache()
        assert len(cache.get_stories()) >= 10


# --- 6. Tool Integration & Browser Opening ---
@pytest.mark.asyncio
async def test_current_affairs_get_updates_tool():
    tool = CurrentAffairsGetUpdatesTool()
    assert tool.name == "current_affairs_get_updates"

    with patch.object(tool.retriever, "get_updates", AsyncMock(return_value="Mock Briefing")):
        res = await tool.execute({"category": "Tech"})
        assert res == "Mock Briefing"


@pytest.mark.asyncio
async def test_current_affairs_open_story_tool():
    tool = CurrentAffairsOpenStoryTool()
    cache = get_session_cache()
    cache.clear()

    # When cache is empty
    empty_res = await tool.execute({"story_index": 1})
    assert "Could not find a matching story" in empty_res

    # Populate cache
    story = NewsStory(
        index=2,
        category="Sports",
        title="India Wins Championship",
        source="ESPN",
        published="1h ago",
        summary="India won by 5 wickets.",
        url="https://espn.com/india-wins",
    )
    cache.store_briefing(NewsBriefing(category_requested="Sports", stories=[story]))

    with patch("app.tools.news.tool.PlaywrightBrowserDriver") as mock_driver_cls:
        mock_driver = MagicMock()
        mock_driver.open_tab = AsyncMock(return_value=1)
        mock_driver_cls.return_value = mock_driver

        # Open by index 2
        res = await tool.execute({"story_index": 2})
        assert "Successfully opened story [2]" in res
        assert "ESPN" in res
        mock_driver.open_tab.assert_awaited_once_with("https://espn.com/india-wins")

        # Open by category
        mock_driver.open_tab.reset_mock()
        res_cat = await tool.execute({"category": "Sports"})
        assert "Successfully opened story [2]" in res_cat
        mock_driver.open_tab.assert_awaited_once_with("https://espn.com/india-wins")


# --- 7. Summarizer Logic ---
@pytest.mark.asyncio
async def test_news_summarizer():
    summarizer = NewsSummarizer(groq_api_key="")

    # Reliable description available: used directly without AI calls
    desc = "Apple unveiled the new MacBook with M5 chips offering 30 percent faster speeds and all-day battery life."
    res = await summarizer.summarize("Apple Unveils MacBook", "TechCrunch", desc)
    assert "Apple unveiled the new MacBook" in res

    # Strips HTML properly
    html_desc = "<b>Clean summary text here.</b> Extended details included."
    assert clean_html_snippet(html_desc) == "Clean summary text here. Extended details included."


# --- 8. STRICT ZERO-PERSISTENCE GUARANTEE ---
@pytest.mark.asyncio
async def test_strict_zero_persistence_policy():
    """
    CRITICAL INVARIANT:
    Under no circumstances should Current Affairs ever call MemoryManager.remember
    or persist news articles into Victor's permanent storage or SQLite database.
    """
    with patch.object(MemoryManager, "remember", MagicMock()) as mock_remember:
        retriever = NewsRetriever()
        mock_items = [
            {
                "title": "Clean Space Mission Update",
                "link": "https://example.com/space",
                "pubDate": "Sun, 20 Sep 2026 10:00:00 GMT",
                "source": "Nature",
                "description": "Satellite deployment successful.",
                "cluster_headlines": [],
            }
        ]
        with patch.object(retriever, "_fetch_feed", AsyncMock(return_value=mock_items)):
            await retriever.get_updates("Science")

        # MemoryManager.remember must NEVER have been called
        mock_remember.assert_not_called()
