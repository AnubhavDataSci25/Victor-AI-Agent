"""
Victor Current Affairs & Updates Module.
Provides fresh, real-time news with zero persistent storage.
"""

from app.news.models import NewsBriefing, NewsCategory, NewsStory
from app.news.retriever import NewsRetriever
from app.news.session_cache import NewsSessionCache, get_session_cache
from app.news.summarizer import NewsSummarizer

__all__ = [
    "NewsCategory",
    "NewsStory",
    "NewsBriefing",
    "NewsRetriever",
    "NewsSessionCache",
    "get_session_cache",
    "NewsSummarizer",
]
