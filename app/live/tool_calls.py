"""
Live Tool Dispatcher — routes Gemini Live API function calls through Victor's Central Tool Gateway.
"""

import logging
from google.genai import types

from app.gateway.tool_gateway import get_tool_gateway

logger = logging.getLogger(__name__)


class LiveToolDispatcher:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.gateway = get_tool_gateway()
        # Keep registry attribute for backward-compatibility
        self.registry = self.gateway.registry

    async def handle_function_call(self, function_call) -> types.FunctionResponse:
        tool_name = function_call.name
        logger.info(f"[Live Dispatcher] Forwarding '{tool_name}' to Central Tool Gateway")

        # Notify UI of executing state
        if hasattr(self.session_manager, "websocket_send_callback"):
            try:
                await self.session_manager.websocket_send_callback({
                    "type": "tool_state",
                    "tool": tool_name,
                    "state": "EXECUTING",
                })
            except Exception as e:
                logger.debug(f"UI notification error: {e}")

        # Execute through Central Tool Gateway
        return await self.gateway.execute_function_call(
            function_call,
            session_manager=self.session_manager,
        )