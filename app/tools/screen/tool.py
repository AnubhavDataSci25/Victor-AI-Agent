"""
Screen Understanding Tool for Victor 2.0.

Provides vision AI screen comprehension to the Gemini Live agent.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.tools.base import BaseTool
from app.tools.screen.analyzer import ScreenAnalyzer

logger = logging.getLogger(__name__)


class ScreenUnderstandTool(BaseTool):
    name = "screen_understand"
    description = (
        "Captures and analyzes the user's current screen using vision AI to understand visible text, "
        "UI elements, forms, buttons, errors, active applications, and overall context. "
        "Use this tool when the user asks: 'What is on my screen?', 'Summarize this page', 'What error am I getting?', "
        "'Is there a form here?', or when you need to locate buttons or fields to interact with."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "The specific question or instruction regarding the screen "
                    "(e.g. 'What is on my screen?', 'Summarize this page', 'What error am I getting?', 'Is there a form here?')."
                )
            },
            "focus": {
                "type": "string",
                "enum": ["general", "summary", "error", "form", "ui_elements"],
                "default": "general",
                "description": "Optional focus area for the screen analysis."
            }
        }
    }

    def __init__(self, analyzer: Optional[ScreenAnalyzer] = None):
        self.analyzer = analyzer or ScreenAnalyzer()

    async def execute(self, args: dict) -> str:
        query = args.get("query")
        focus = args.get("focus")

        logger.info(f"ScreenUnderstandTool invoked with query='{query}', focus='{focus}'")
        analysis = await self.analyzer.analyze_screen(query=query, focus=focus)

        if not analysis.get("success", False):
            error_msg = analysis.get("error", "Unknown screen analysis error")
            logger.error(f"Screen understanding failed: {error_msg}")
            return f"Screen understanding was unable to analyze the screen. Reason: {error_msg}"

        return analysis.get("formatted_text", "Screen analyzed successfully.")
