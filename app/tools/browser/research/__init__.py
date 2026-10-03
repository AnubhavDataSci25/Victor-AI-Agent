"""
Browser Research Agent package for Victor AI Assistant.
"""

from app.tools.browser.research.models import (
    CandidateProduct,
    PriceDetail,
    ProductConstraints,
    ResearchResult,
    ResearchState,
    ResearchTraceStep,
)
from app.tools.browser.research.research_agent import BrowserResearchAgent
from app.tools.browser.research.tool import BrowserResearchTool

__all__ = [
    "BrowserResearchAgent",
    "BrowserResearchTool",
    "ProductConstraints",
    "PriceDetail",
    "CandidateProduct",
    "ResearchResult",
    "ResearchState",
    "ResearchTraceStep",
]
