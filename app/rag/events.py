"""
Victor Document Intelligence & RAG — Real-Time UI Event Synchronization.

Registers active UI WebSocket channels and broadcasts document events
(documents uploaded/indexed, voice summaries generated, dashboard navigation)
so the Document RAG dashboard updates instantly and displays summaries in real time.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

# Active WebSocket UI sender callbacks (ws_send)
_ACTIVE_UI_LISTENERS: Set[Callable[[Dict[str, Any]], Any]] = set()
_MAIN_EVENT_LOOP: Optional[asyncio.AbstractEventLoop] = None


def set_rag_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Stores a reference to the main asyncio event loop for thread-safe event broadcasts."""
    global _MAIN_EVENT_LOOP
    _MAIN_EVENT_LOOP = loop


def register_ui_listener(callback: Callable[[Dict[str, Any]], Any]) -> None:
    """Registers an active WebSocket client sender callback."""
    _ACTIVE_UI_LISTENERS.add(callback)


def unregister_ui_listener(callback: Callable[[Dict[str, Any]], Any]) -> None:
    """Removes a disconnected WebSocket client sender callback."""
    _ACTIVE_UI_LISTENERS.discard(callback)


async def broadcast_rag_event(action: str, data: Dict[str, Any]) -> None:
    """
    Broadcasts a document event to all active connected browser UI sessions.
    Payload: {"type": "document_update", "action": action, "data": data}
    """
    if not _ACTIVE_UI_LISTENERS:
        return

    payload = {
        "type": "document_update",
        "action": action,
        "data": data,
    }

    dead_listeners = set()
    for cb in list(_ACTIVE_UI_LISTENERS):
        try:
            res = cb(payload)
            if asyncio.iscoroutine(res):
                await res
        except Exception as e:
            logger.debug("[RAGEvents] Listener failed, removing: %s", e)
            dead_listeners.add(cb)

    _ACTIVE_UI_LISTENERS.difference_update(dead_listeners)


def emit_rag_event_sync(action: str, data: Dict[str, Any]) -> None:
    """Synchronous helper that schedules the broadcast task on the running or main event loop."""
    loop = None
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = _MAIN_EVENT_LOOP

    if loop and loop.is_running():
        try:
            asyncio.run_coroutine_threadsafe(broadcast_rag_event(action, data), loop)
        except Exception:
            pass
    elif loop:
        try:
            loop.create_task(broadcast_rag_event(action, data))
        except Exception:
            pass


async def broadcast_document_summary(
    document_id: str,
    file_name: str,
    summary: str,
    summary_type: str = "comprehensive",
    auto_navigate: bool = True,
) -> None:
    """
    Broadcasts a generated summary to the UI, updates the Study & Notes view,
    and optionally navigates the user's dashboard directly to the Document RAG tab.
    """
    payload = {
        "document_id": document_id,
        "file_name": file_name,
        "summary": summary,
        "summary_type": summary_type,
    }
    await broadcast_rag_event("voice_summary", payload)

    if auto_navigate and _ACTIVE_UI_LISTENERS:
        nav_payload = {
            "type": "dashboard_navigate",
            "section": "documents",
            "tab": "study",
            "document_id": document_id,
            "summary": summary,
        }
        dead_listeners = set()
        for cb in list(_ACTIVE_UI_LISTENERS):
            try:
                res = cb(nav_payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception:
                dead_listeners.add(cb)
        _ACTIVE_UI_LISTENERS.difference_update(dead_listeners)
