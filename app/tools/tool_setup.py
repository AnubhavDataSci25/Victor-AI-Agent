"""
Victor 2.0 tool registration.

Assembles the ToolRegistry with all v2 BaseTool instances. This
replaces the role of factory.py (which imports v1-only classes) for
the Gemini Live API path.
"""

from __future__ import annotations

import logging

from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def build_tool_registry() -> ToolRegistry:
    """Create and populate a ToolRegistry with all Victor 2.0 tools."""
    registry = ToolRegistry()

    # --- Browser Tools ---
    try:
        from app.tools.browser.tool import (
            BrowserClickElementTool,
            BrowserCloseTabTool,
            BrowserCloseTool,
            BrowserOpenTabTool,
            BrowserOpenUrlTool,
            BrowserSearchWebTool,
        )
        registry.register(BrowserSearchWebTool())
        registry.register(BrowserOpenUrlTool())
        registry.register(BrowserClickElementTool())
        registry.register(BrowserOpenTabTool())
        registry.register(BrowserCloseTabTool())
        registry.register(BrowserCloseTool())
        logger.info("Registered browser tools.")
    except Exception as e:
        logger.warning(f"Browser tools unavailable: {e}")

    # --- Computer / OS Automation Tools ---
    try:
        from app.tools.computer.tool import (
            ComputerClickTool,
            ComputerCloseApplicationTool,
            ComputerOpenApplicationTool,
            ComputerPressKeyTool,
            ComputerScrollTool,
            ComputerSubmitFormTool,
            ComputerTakeScreenshotTool,
            ComputerTypeTextTool,
        )
        registry.register(ComputerOpenApplicationTool())
        registry.register(ComputerCloseApplicationTool())
        registry.register(ComputerTakeScreenshotTool())
        registry.register(ComputerClickTool())
        registry.register(ComputerTypeTextTool())
        registry.register(ComputerPressKeyTool())
        registry.register(ComputerScrollTool())
        registry.register(ComputerSubmitFormTool())
        logger.info("Registered computer tools.")
    except Exception as e:
        logger.warning(f"Computer tools unavailable: {e}")

    # --- Screen Understanding Tools ---
    try:
        from app.tools.screen.tool import ScreenUnderstandTool
        registry.register(ScreenUnderstandTool())
        logger.info("Registered screen understanding tools.")
    except Exception as e:
        logger.warning(f"Screen understanding tools unavailable: {e}")

    # --- Memory Tools ---
    try:
        from app.tools.memory.tool import (
            MemoryForgetTool,
            MemoryRecallTool,
            MemoryRememberTool,
        )
        registry.register(MemoryRememberTool())
        registry.register(MemoryRecallTool())
        registry.register(MemoryForgetTool())
        logger.info("Registered memory tools.")
    except Exception as e:
        logger.warning(f"Memory tools unavailable: {e}")

    # --- System Tools ---
    try:
        from app.tools.system.tool import (
            SystemGetInfoTool,
            SystemGetTimeTool,
            SystemLockVictorTool,
            SystemLockWindowsTool,
            SystemVolumeTool,
        )
        registry.register(SystemGetTimeTool())
        registry.register(SystemGetInfoTool())
        registry.register(SystemVolumeTool())
        registry.register(SystemLockWindowsTool())
        registry.register(SystemLockVictorTool())
        logger.info("Registered system tools.")
    except Exception as e:
        logger.warning(f"System tools unavailable: {e}")

    # --- Music Tools ---
    try:
        from app.tools.music.tool import (
            MusicNextTrackTool,
            MusicPauseTool,
            MusicPlayTool,
            MusicPreviousTrackTool,
            MusicResumeTool,
            MusicStopTool,
        )
        registry.register(MusicPlayTool())
        registry.register(MusicPauseTool())
        registry.register(MusicResumeTool())
        registry.register(MusicStopTool())
        registry.register(MusicNextTrackTool())
        registry.register(MusicPreviousTrackTool())
        logger.info("Registered music tools.")
    except Exception as e:
        logger.warning(f"Music tools unavailable: {e}")

    # --- Email Tools ---
    try:
        from app.tools.email.tool import (
            EmailGetUnreadSummaryTool,
            EmailSearchMessagesTool,
        )
        registry.register(EmailGetUnreadSummaryTool())
        registry.register(EmailSearchMessagesTool())
        logger.info("Registered email tools.")
    except Exception as e:
        logger.warning(f"Email tools unavailable: {e}")

    # --- Web App Tools ---
    try:
        from app.tools.web_apps.tool import (
            WebAppOpenChatGPTTool,
            WebAppOpenGeminiTool,
            WebAppWikipediaTool,
            WebAppYouTubeTool,
        )
        registry.register(WebAppYouTubeTool())
        registry.register(WebAppWikipediaTool())
        registry.register(WebAppOpenChatGPTTool())
        registry.register(WebAppOpenGeminiTool())
        logger.info("Registered web app tools.")
    except Exception as e:
        logger.warning(f"Web app tools unavailable: {e}")

    # --- Coding Computer Control Tools ---
    try:
        from app.tools.coding.tool import (
            CloseVSCodeTool,
            CodingCloseVSCodeTool,
            CodingDeleteFileTool,
            CodingExecuteTaskTool,
            CodingGetWorkspaceStatusTool,
            CodingResolveWorkspaceTool,
            CodingRunCommandTool,
            DeleteFileTool,
        )
        registry.register(CodingResolveWorkspaceTool())
        registry.register(CodingExecuteTaskTool())
        registry.register(CodingRunCommandTool())
        registry.register(CodingGetWorkspaceStatusTool())
        registry.register(CodingDeleteFileTool())
        registry.register(DeleteFileTool())
        registry.register(CodingCloseVSCodeTool())
        registry.register(CloseVSCodeTool())
        logger.info("Registered coding computer control tools.")
    except Exception as e:
        logger.warning(f"Coding tools unavailable: {e}")

    # --- Multi-Agent Project Planning Tools ---
    try:
        from app.tools.multi_agent.tool import (
            MultiAgentDownloadArtifactTool,
            MultiAgentGetStatusTool,
            MultiAgentReviewTool,
            MultiAgentStartProjectTool,
        )
        registry.register(MultiAgentStartProjectTool())
        registry.register(MultiAgentReviewTool())
        registry.register(MultiAgentGetStatusTool())
        registry.register(MultiAgentDownloadArtifactTool())
        logger.info("Registered multi-agent planning tools.")
    except Exception as e:
        logger.warning(f"Multi-agent tools unavailable: {e}")

    tool_count = len(registry.list_tools())
    logger.info(f"Tool registry built with {tool_count} tools.")
    return registry


