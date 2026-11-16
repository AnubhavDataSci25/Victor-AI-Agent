"""
Victor Dashboard Navigation — Centralized Navigation Controller.

Translates validated navigation intents into frontend navigation events,
manages active navigation state and history stack, and produces concise natural speech.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from app.navigation.models import NavigationAction, NavigationIntent, NavigationResult
from app.navigation.registry import NavigationRegistry, get_navigation_registry

logger = logging.getLogger(__name__)

# Active UI WebSocket callbacks (same pattern as finance and RAG)
_ACTIVE_UI_LISTENERS: Set[Callable[[Dict[str, Any]], Any]] = set()


def register_navigation_ui_listener(callback: Callable[[Dict[str, Any]], Any]) -> None:
    """Registers an active WebSocket client sender callback for navigation."""
    _ACTIVE_UI_LISTENERS.add(callback)


def unregister_navigation_ui_listener(callback: Callable[[Dict[str, Any]], Any]) -> None:
    """Removes a disconnected WebSocket client sender callback."""
    _ACTIVE_UI_LISTENERS.discard(callback)


class DashboardNavigationController:
    """
    Centralized controller for Victor's desktop dashboard navigation.
    Coordinates state, history stack, validation, WebSocket broadcasts, and spoken responses.
    """

    def __init__(self, registry: Optional[NavigationRegistry] = None) -> None:
        self.registry = registry or get_navigation_registry()
        self.current_destination: str = "dashboard"
        self.current_tab: Optional[str] = None
        self.previous_destination: Optional[str] = None
        self.previous_tab: Optional[str] = None
        self._history_stack: List[Tuple[str, Optional[str]]] = [("dashboard", None)]

    def register_listener(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        register_navigation_ui_listener(callback)

    def unregister_listener(self, callback: Callable[[Dict[str, Any]], Any]) -> None:
        unregister_navigation_ui_listener(callback)

    async def navigate(self, destination: str, tab: Optional[str] = None, source: str = "voice") -> NavigationResult:
        intent = NavigationIntent(
            intent="dashboard_navigation",
            destination=destination,
            tab=tab,
            action=NavigationAction.OPEN,
            source=source,
        )
        return await self.execute_intent(intent)

    async def navigate_back(self, source: str = "voice") -> NavigationResult:
        intent = NavigationIntent(
            intent="dashboard_navigation",
            destination="__BACK__",
            action=NavigationAction.BACK,
            source=source,
        )
        return await self.execute_intent(intent)

    def get_state(self) -> Dict[str, Any]:
        """Returns current navigation state."""
        return {
            "current_destination": self.current_destination,
            "current_tab": self.current_tab,
            "previous_destination": self.previous_destination,
            "previous_tab": self.previous_tab,
            "history_depth": len(self._history_stack),
        }

    async def execute_intent(self, intent: NavigationIntent) -> NavigationResult:
        """
        Executes a validated navigation intent.
        Handles 'open', 'switch', 'home', and 'back' navigation actions.
        """
        dest_raw = intent.destination.strip()
        action = intent.action
        tab = intent.tab

        # Handle 'back' / 'previous' action
        if action == NavigationAction.BACK or dest_raw == "__BACK__":
            return await self._navigate_back(intent.source)

        # Handle 'home' action
        if action == NavigationAction.HOME or dest_raw in ("dashboard", "home"):
            return await self._navigate_to(
                destination_id="dashboard",
                tab=None,
                source=intent.source,
                filters=intent.filters
            )

        # Validate destination exists in registry
        dest_meta = self.registry.get_destination(dest_raw)
        if not dest_meta:
            logger.warning(f"[Navigation Controller] Unknown destination '{dest_raw}' requested.")
            return NavigationResult(
                success=False,
                destination=dest_raw,
                tab=tab,
                action="open",
                previous_destination=self.current_destination,
                spoken_feedback="Sir, I couldn't find that section in the dashboard.",
                error=f"Destination '{dest_raw}' not registered."
            )

        # Validate subtab if specified
        if tab and tab not in dest_meta.subtabs:
            # Check if tab was provided as human title
            normalized_tab = None
            for tid, tname in dest_meta.subtabs.items():
                if tid.lower() == tab.lower() or tname.lower() == tab.lower():
                    normalized_tab = tid
                    break
            tab = normalized_tab

        return await self._navigate_to(
            destination_id=dest_meta.id,
            tab=tab,
            source=intent.source,
            filters=intent.filters
        )

    async def _navigate_to(
        self,
        destination_id: str,
        tab: Optional[str],
        source: str = "voice",
        filters: Optional[Dict[str, Any]] = None
    ) -> NavigationResult:
        """Navigates to a specific destination and optional subtab."""
        dest_meta = self.registry.get_destination(destination_id)
        dest_title = dest_meta.title if dest_meta else destination_id.capitalize()

        # Check if already active
        if self.current_destination == destination_id and self.current_tab == tab:
            logger.info(f"[Navigation Controller] '{destination_id}' (tab={tab}) is already active.")
            tab_title = dest_meta.subtabs.get(tab, tab) if (dest_meta and tab) else None
            active_name = f"{dest_title} - {tab_title}" if tab_title else dest_title
            return NavigationResult(
                success=True,
                destination=destination_id,
                tab=tab,
                action="open",
                previous_destination=self.previous_destination,
                spoken_feedback=f"Sir, {active_name} is already open on your screen.",
                is_already_active=True
            )

        # Update history stack (avoid consecutive duplicates)
        prev_dest = self.current_destination
        prev_tab = self.current_tab
        self.previous_destination = prev_dest
        self.previous_tab = prev_tab

        if not self._history_stack or self._history_stack[-1] != (destination_id, tab):
            self._history_stack.append((destination_id, tab))
            # Keep history stack reasonable
            if len(self._history_stack) > 30:
                self._history_stack.pop(0)

        self.current_destination = destination_id
        self.current_tab = tab

        # Broadcast WebSocket event to active frontends
        await self._broadcast_navigation(destination_id, tab, filters or {})

        # Build natural spoken confirmation
        spoken_msg = self._generate_spoken_feedback(destination_id, dest_title, tab, dest_meta)

        logger.info(f"[Navigation Controller] Successfully navigated to '{destination_id}' (tab={tab}).")
        return NavigationResult(
            success=True,
            destination=destination_id,
            tab=tab,
            action="open",
            previous_destination=prev_dest,
            spoken_feedback=spoken_msg,
            is_already_active=False
        )

    async def _navigate_back(self, source: str = "voice") -> NavigationResult:
        """Pops navigation history and navigates back to the previous screen."""
        if len(self._history_stack) > 1:
            # Pop current
            self._history_stack.pop()
            # Peek target
            target_dest, target_tab = self._history_stack[-1]
        else:
            target_dest, target_tab = "dashboard", None

        prev_dest = self.current_destination
        self.previous_destination = prev_dest
        self.previous_tab = self.current_tab
        self.current_destination = target_dest
        self.current_tab = target_tab

        # Broadcast WebSocket event
        await self._broadcast_navigation(target_dest, target_tab, {"action": "back"})

        dest_meta = self.registry.get_destination(target_dest)
        dest_title = dest_meta.title if dest_meta else target_dest.capitalize()

        if target_dest == "dashboard":
            spoken_msg = "Returning to the Command Center, Sir."
        elif target_tab and dest_meta and target_tab in dest_meta.subtabs:
            spoken_msg = f"Navigating back to {dest_title}, {dest_meta.subtabs[target_tab]}."
        else:
            spoken_msg = f"Navigating back to {dest_title}."

        logger.info(f"[Navigation Controller] Navigated back to '{target_dest}' (tab={target_tab}).")
        return NavigationResult(
            success=True,
            destination=target_dest,
            tab=target_tab,
            action="back",
            previous_destination=prev_dest,
            spoken_feedback=spoken_msg
        )

    def _generate_spoken_feedback(
        self,
        dest_id: str,
        dest_title: str,
        tab: Optional[str],
        dest_meta: Optional[NavigationDestination]
    ) -> str:
        """Generates natural, concise voice feedback matching user expectations."""
        if dest_id == "dashboard":
            return "Returning to the Command Center, Sir."

        tab_title = dest_meta.subtabs.get(tab) if (dest_meta and tab) else None

        if tab_title:
            return f"Opening {dest_title}, {tab_title} section."

        custom_phrasings = {
            "memory": "Certainly, Sir. Opening Memory.",
            "documents": "Opening Document Intelligence.",
            "computer": "Opening Computer Control.",
            "system": "Opening System Monitor.",
            "finance": "Opening Finance Dashboard.",
            "automations": "Opening Automations & Companion.",
            "browser": "Opening Web & Browser.",
            "applications": "Opening Applications.",
            "screen": "Opening Screen Intelligence.",
            "agents": "Opening Multi-Agent Workflows.",
            "tools": "Opening Tools Catalog.",
            "labs": "Opening Victor Labs.",
            "settings": "Opening Settings & Security.",
        }
        return custom_phrasings.get(dest_id, f"Opening {dest_title}, Sir.")

    async def _broadcast_navigation(
        self,
        destination_id: str,
        tab: Optional[str],
        filters: Dict[str, Any]
    ) -> None:
        """Pushes navigation instruction to all active connected browser UI sessions."""
        if not _ACTIVE_UI_LISTENERS:
            return

        payload = {
            "type": "dashboard_navigate",
            "destination": destination_id,
            "section": destination_id,
            "tab": tab,
            "filters": filters,
        }

        dead = set()
        for cb in list(_ACTIVE_UI_LISTENERS):
            try:
                res = cb(payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                dead.add(cb)
        _ACTIVE_UI_LISTENERS.difference_update(dead)


# Global singleton instance
_GLOBAL_CONTROLLER: Optional[DashboardNavigationController] = None


def get_navigation_controller() -> DashboardNavigationController:
    """Returns the singleton DashboardNavigationController."""
    global _GLOBAL_CONTROLLER
    if _GLOBAL_CONTROLLER is None:
        _GLOBAL_CONTROLLER = DashboardNavigationController()
    return _GLOBAL_CONTROLLER
