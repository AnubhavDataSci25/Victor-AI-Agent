import logging
from app.tools.base import BaseTool
from app.tools.web_apps.youtube_provider import YouTubeVideoProvider
from app.tools.web_apps.wikipedia_provider import WikipediaProvider
from app.tools.web_apps.ai_provider import AIWebProvider

logger = logging.getLogger(__name__)

class WebAppYouTubeTool(BaseTool):
    name = "webapp_youtube_play"
    description = "Searches for and plays a video on standard YouTube."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The video to search for and play."}
        },
        "required": ["query"]
    }

    async def execute(self, args: dict) -> str:
        return await YouTubeVideoProvider.play_video(args.get("query", ""))

class WebAppWikipediaTool(BaseTool):
    name = "webapp_wikipedia_search"
    description = "Searches Wikipedia for a topic and returns the article summary."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The topic to look up on Wikipedia."}
        },
        "required": ["query"]
    }

    async def execute(self, args: dict) -> str:
        return await WikipediaProvider.search_and_read(args.get("query", ""))

class WebAppOpenChatGPTTool(BaseTool):
    name = "webapp_open_chatgpt"
    description = "Opens the ChatGPT website in the browser."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await AIWebProvider.open_chatgpt()

class WebAppOpenGeminiTool(BaseTool):
    name = "webapp_open_gemini"
    description = "Opens the Gemini website in the browser."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await AIWebProvider.open_gemini()

class WebAppOpenClaudeTool(BaseTool):
    name = "webapp_open_claude"
    description = "Opens the Claude AI website (https://claude.ai) in the browser."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return await AIWebProvider.open_claude()