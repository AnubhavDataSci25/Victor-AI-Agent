"""
Victor Dashboard Navigation Tool.
Allows Gemini Live and VictorCore to navigate the dashboard via structured tool calls.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.tools.permissions import PermissionLevel
from app.navigation.controller import DashboardNavigationController, get_navigation_controller
from app.navigation.models import NavigationAction, NavigationIntent
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class DashboardNavigateTool(BaseTool):
    """
    Navigates Victor's desktop dashboard interface to any section, tab, or subpage.
    Supports voice and text commands like:
      - "Victor, open Memory."
      - "Victor, switch to Document RAG."
      - "Open Window Control."
      - "Go to System Information."
      - "Show me my Finance Dashboard."
      - "Open Email Manager."
      - "Switch back to Home."
      - "Go to the previous tab."
    """
    name = "dashboard_navigate"
    description = (
        "Navigates Victor's interactive desktop dashboard to any section, tab, or subpage. "
        "Allowed destinations: 'dashboard' (Home/Orb), 'finance', 'documents', 'memory', 'computer' (Window Control), "
        "'browser', 'applications', 'system' (System Monitor), 'screen' (Screen Analyzer), 'automations' (Email & Companion), "
        "'agents', 'tools', 'labs', 'settings', or '__BACK__' (previous tab/page). "
        "Allowed subtabs for finance: 'overview', 'transactions', 'categories', 'budgets', 'bills', 'analytics', 'subscriptions'. "
        "Allowed subtabs for documents: 'library', 'qa', 'excel', 'compare', 'notes'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "destination": {
                "type": "string",
                "description": (
                    "Target section to open: 'dashboard', 'finance', 'documents', 'memory', 'computer', "
                    "'browser', 'applications', 'system', 'screen', 'automations', 'agents', 'tools', 'labs', 'settings', or '__BACK__'."
                ),
                "enum": [
                    "dashboard", "finance", "documents", "memory", "computer",
                    "browser", "applications", "system", "screen", "automations",
                    "agents", "tools", "labs", "settings", "__BACK__"
                ],
            },
            "tab": {
                "type": "string",
                "description": "Optional subtab within the destination (e.g., 'transactions', 'bills', 'library', 'excel').",
            },
            "action": {
                "type": "string",
                "enum": ["open", "switch", "back", "home"],
                "description": "Navigation action to perform. Defaults to 'open'.",
            },
        },
        "required": ["destination"],
    }

    def __init__(self, controller: Optional[DashboardNavigationController] = None) -> None:
        self.controller = controller

    def _ctrl(self) -> DashboardNavigationController:
        return self.controller or get_navigation_controller()

    async def execute(self, args: dict[str, Any]) -> str:
        destination = args.get("destination", "dashboard")
        tab = args.get("tab")
        action_str = args.get("action", "open")

        action_enum = NavigationAction.OPEN
        if action_str == "back" or destination == "__BACK__":
            action_enum = NavigationAction.BACK
        elif action_str == "home" or destination == "dashboard":
            action_enum = NavigationAction.HOME

        intent = NavigationIntent(
            intent="dashboard_navigation",
            destination=destination,
            tab=tab,
            action=action_enum,
            source="tool",
            filters=args
        )

        result = await self._ctrl().execute_intent(intent)
        return result.spoken_feedback
