"""
Live Tool Dispatcher — the gateway between Gemini Live API function
calls and Victor's tool registry.

Every function call from the model passes through here:
1. Session state check (must be ACTIVE/EXECUTING/SPEAKING)
2. Tool lookup via registry
3. Tool execution via registry.execute()
4. Special lifecycle intercepts (e.g. lock_victor)
5. Structured FunctionResponse back to Gemini
"""

import asyncio
import logging
from google.genai import types

from app.tools.tool_setup import build_tool_registry
from app.agent.state import VictorState

logger = logging.getLogger(__name__)

# Shared singleton registry — built once, reused across dispatchers
_registry = None


def _get_registry():
    global _registry
    if _registry is None:
        _registry = build_tool_registry()
    return _registry


class LiveToolDispatcher:
    def __init__(self, session_manager):
        self.session_manager = session_manager
        self.registry = _get_registry()

    async def handle_function_call(self, function_call) -> types.FunctionResponse:
        tool_name = function_call.name
        args = function_call.args if hasattr(function_call, "args") and function_call.args else {}
        call_id = getattr(function_call, "id", None)

        logger.info(f"[Tool Gateway] Gemini requested: '{tool_name}'")

        # 1. Security Check: Session must be fully authenticated with 2FA (PIN + Biometric) and active
        if hasattr(self.session_manager, "is_authenticated") and not self.session_manager.is_authenticated():
            return self._build_error(
                tool_name,
                call_id,
                "Access Denied: Victor session is not authenticated with biometric verification."
            )

        if self.session_manager.state not in (VictorState.ACTIVE, VictorState.EXECUTING, VictorState.SPEAKING):
            return self._build_error(tool_name, call_id, "Access Denied: Victor session is locked or inactive.")

        # 2. Lookup Tool
        tool = self.registry.get_tool(tool_name)
        if not tool:
            return self._build_error(tool_name, call_id, f"Tool '{tool_name}' is not registered.")

        # 3. Tool Execution
        try:
            await self.session_manager.websocket_send_callback({
                "type": "tool_state",
                "tool": tool_name,
                "state": "EXECUTING"
            })

            result = await self.registry.execute(tool_name, args)

            # --- Intercept Privileged Lock Command ---
            if tool_name == "lock_victor":
                logger.info("[Tool Gateway] Privileged lifecycle action: 'lock_victor' invoked by model.")
                asyncio.create_task(self._delayed_lock())

            return types.FunctionResponse(
                name=tool_name,
                id=call_id,
                response={"result": result, "status": "success"}
            )

        except Exception as e:
            logger.error(f"[Tool Gateway] Execution error in {tool_name}: {e}")
            return self._build_error(tool_name, call_id, f"Execution error: {str(e)}")

    async def _delayed_lock(self):
        """Allows the final FunctionResponse to traverse the socket before backend teardown."""
        await asyncio.sleep(0.5)
        await self.session_manager.lock()

    def _build_error(self, name: str, call_id: str, error_msg: str) -> types.FunctionResponse:
        logger.warning(f"[Tool Gateway] Rejecting {name}: {error_msg}")
        return types.FunctionResponse(
            name=name,
            id=call_id,
            response={"error": error_msg, "status": "failed"}
        )