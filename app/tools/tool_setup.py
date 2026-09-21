"""
Victor 2.0 tool registration.

Assembles the ToolRegistry with all v2 BaseTool instances. This
replaces the role of factory.py (which imports v1-only classes) for
the Gemini Live API path.
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)


def build_tool_registry(allowed_roots: list[Path] | None = None) -> ToolRegistry:
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
            SystemAdjustBrightnessTool,
            SystemAdjustVolumeTool,
            SystemGetBatteryTool,
            SystemGetBluetoothTool,
            SystemGetBrightnessTool,
            SystemGetInfoTool,
            SystemGetNetworkTool,
            SystemGetNotificationsTool,
            SystemGetPerformanceTool,
            SystemGetTimeTool,
            SystemGetVolumeTool,
            SystemLockVictorTool,
            SystemLockWindowsTool,
            SystemOpenNotificationPanelTool,
            SystemOpenSettingsTool,
        )
        registry.register(SystemGetTimeTool())
        registry.register(SystemGetInfoTool())
        registry.register(SystemGetBatteryTool())
        registry.register(SystemGetNetworkTool())
        registry.register(SystemGetBluetoothTool())
        registry.register(SystemGetBrightnessTool())
        registry.register(SystemAdjustBrightnessTool())
        registry.register(SystemGetVolumeTool())
        registry.register(SystemAdjustVolumeTool())
        registry.register(SystemGetPerformanceTool())
        registry.register(SystemGetNotificationsTool())
        registry.register(SystemOpenNotificationPanelTool())
        registry.register(SystemOpenSettingsTool())
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

    # --- Google Services Tools ---
    try:
        from app.tools.google.tool import (
            GoogleCalendarCreateEventTool,
            GoogleCalendarOpenTool,
            GoogleKeepCreateNoteTool,
            GoogleKeepOpenTool,
            GoogleKeepSearchNotesTool,
            GoogleMeetCreateTool,
            GoogleMeetJoinTool,
        )
        registry.register(GoogleKeepCreateNoteTool())
        registry.register(GoogleKeepSearchNotesTool())
        registry.register(GoogleKeepOpenTool())
        registry.register(GoogleCalendarCreateEventTool())
        registry.register(GoogleCalendarOpenTool())
        registry.register(GoogleMeetCreateTool())
        registry.register(GoogleMeetJoinTool())
        logger.info("Registered Google services tools.")
    except Exception as e:
        logger.warning(f"Google services tools unavailable: {e}")

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

    # --- File Explorer & Search Tools ---
    try:
        from app.config import VictorConfig
        from app.tools.filesystem.file_explorer import (
            FileExplorerDeleteTool,
            FileExplorerMoveTool,
            FileExplorerOpenTool,
            FileExplorerRenameTool,
            FileExplorerSearchTool,
        )
        from app.tools.filesystem.path_validation import resolve_allowed_roots

        if allowed_roots is None:
            fs_config = VictorConfig().filesystem
            roots = resolve_allowed_roots(fs_config.allowed_roots)
        else:
            roots = allowed_roots

        registry.register(FileExplorerSearchTool(roots))
        registry.register(FileExplorerOpenTool(roots))
        registry.register(FileExplorerRenameTool(roots))
        registry.register(FileExplorerMoveTool(roots))
        registry.register(FileExplorerDeleteTool(roots))
        logger.info("Registered file explorer & search tools.")
    except Exception as e:
        logger.warning(f"File explorer tools unavailable: {e}")

    # --- Current Affairs & Updates Tools ---
    try:
        from app.tools.news.tool import (
            CurrentAffairsGetUpdatesTool,
            CurrentAffairsOpenStoryTool,
        )
        registry.register(CurrentAffairsGetUpdatesTool())
        registry.register(CurrentAffairsOpenStoryTool())
        logger.info("Registered current affairs & updates tools.")
    except Exception as e:
        logger.warning(f"Current affairs tools unavailable: {e}")

    # --- Phone Companion Automation Tools ---
    try:
        from app.phone.tools import (
            PhoneAnswerCallTool,
            PhoneGetStatusTool,
            PhoneInitiateCallTool,
            PhoneLaunchYouTubeTool,
            PhoneRejectCallTool,
            PhoneResolveContactTool,
            PhoneUnpairTool,
        )
        registry.register(PhoneGetStatusTool())
        registry.register(PhoneResolveContactTool())
        registry.register(PhoneInitiateCallTool())
        registry.register(PhoneAnswerCallTool())
        registry.register(PhoneRejectCallTool())
        registry.register(PhoneLaunchYouTubeTool())
        registry.register(PhoneUnpairTool())
        logger.info("Registered phone companion automation tools.")
    except Exception as e:
        logger.warning(f"Phone tools unavailable: {e}")

    tool_count = len(registry.list_tools())
    logger.info(f"Tool registry built with {tool_count} tools.")
    return registry


