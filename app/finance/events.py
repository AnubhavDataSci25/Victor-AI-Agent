"""
Victor Personal Finance — Real-Time Event Synchronization.

Registers active UI WebSocket channels and broadcasts financial mutation events
(transactions added/edited/deleted, bills paid/scheduled, budgets updated) so the
dashboard updates instantly without full page reloads.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Set

logger = logging.getLogger(__name__)

# Set of async websocket callback functions (ws_send)
_ACTIVE_UI_LISTENERS: Set[Callable[[Dict[str, Any]], Any]] = set()
_MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_finance_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Stores a reference to the main asyncio event loop for cross-thread broadcasts."""
    global _MAIN_EVENT_LOOP
    _MAIN_EVENT_LOOP = loop


def register_ui_listener(callback: Callable[[Dict[str, Any]], Any]) -> None:
    """Registers an active WebSocket client sender callback."""
    _ACTIVE_UI_LISTENERS.add(callback)


def unregister_ui_listener(callback: Callable[[Dict[str, Any]], Any]) -> None:
    """Removes a disconnected WebSocket client sender callback."""
    _ACTIVE_UI_LISTENERS.discard(callback)


async def broadcast_finance_event(event_type: str, data: Dict[str, Any]) -> None:
    """
    Broadcasts a finance event to all active connected browser UI sessions.
    Event payload: {"type": "finance_update", "action": event_type, "data": data}
    """
    if not _ACTIVE_UI_LISTENERS:
        return

    payload = {
        "type": "finance_update",
        "action": event_type,
        "data": data,
    }

    dead_listeners = set()
    for cb in list(_ACTIVE_UI_LISTENERS):
        try:
            res = cb(payload)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.debug(f"[FinanceEvents] Listener failed, removing: {e}")
            dead_listeners.add(cb)

    _ACTIVE_UI_LISTENERS.difference_update(dead_listeners)


def emit_finance_event_sync(event_type: str, data: Dict[str, Any]) -> None:
    """Synchronous helper that schedules the broadcast task on the running or main event loop."""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = _MAIN_EVENT_LOOP

    if loop and loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(broadcast_finance_event(event_type, data), loop)
        except Exception:
            pass
    elif loop:
        try:
            loop.create_task(broadcast_finance_event(event_type, data))
        except Exception:
            pass


async def broadcast_dashboard_navigation(tab: str, filters: Dict[str, Any] | None = None) -> None:
    """
    Instructs the active Victor UI dashboard to navigate to a specific finance tab
    and apply contextual filters.
    """
    if not _ACTIVE_UI_LISTENERS:
        return

    payload = {
        "type": "dashboard_navigate",
        "section": "finance",
        "tab": tab,
        "filters": filters or {},
    }

    for cb in list(_ACTIVE_UI_LISTENERS):
        try:
            res = cb(payload)
            if asyncio.iscoroutine(res):
                await res
        except Exception:
            pass
