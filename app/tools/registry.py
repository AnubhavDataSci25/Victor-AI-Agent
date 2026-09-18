"""
Tool registry — unified for Victor 2.0.

Supports both v1 Tool (sync, Pydantic) and v2 BaseTool (async, dict)
tool types. This is the single choke point every tool call passes
through:

    ToolCallRequest
        -> lookup tool
        -> validate arguments (v1) or pass dict (v2)
        -> permission decision
        -> execute
        -> verify (v1 only)
        -> structured result
        -> audit log

No other path to tool execution exists in Victor.
"""

from __future__ import annotations

import time
from typing import Any, Union

from app.logging import get_logger, log_tool_call
from app.tools.base import BaseTool, Tool, ToolValidationError
from app.tools.models import ToolCallRequest, ToolResult
from app.tools.permissions import PermissionDecision, PermissionEngine

logger = get_logger("tools.registry")

# Union type for both tool flavors
AnyTool = Union[Tool, BaseTool]


class ToolRegistry:
    def __init__(self, permission_engine: PermissionEngine | None = None) -> None:
        self._tools: dict[str, AnyTool] = {}
        self._permission_engine = permission_engine or PermissionEngine()

    def register(self, tool: AnyTool) -> None:
        if tool.name in self._tools:
            raise ValueError(f"Tool {tool.name!r} is already registered")
        self._tools[tool.name] = tool

    def get(self, name: str) -> AnyTool | None:
        return self._tools.get(name)

    # Alias used by LiveToolDispatcher
    def get_tool(self, name: str) -> AnyTool | None:
        return self.get(name)

    def get_all_tools(self) -> dict[str, AnyTool]:
        """Return the full tool dictionary (used by schemas.py)."""
        return dict(self._tools)

    def list_tools(self) -> list[dict[str, str]]:
        result = []
        for tool in self._tools.values():
            entry: dict[str, str] = {
                "name": tool.name,
                "description": tool.description,
            }
            if isinstance(tool, Tool):
                entry["permission_level"] = tool.permission_level.value
            result.append(entry)
        return result

    def iter_tools(self) -> list[AnyTool]:
        """Full Tool objects, e.g. for building LLM function-calling
        schemas from each tool's args_model. list_tools() stays as the
        lightweight summary view used elsewhere."""
        return list(self._tools.values())

    async def execute(self, tool_name: str, args: dict[str, Any]) -> str:
        """Execute a tool by name (async). Used by LiveToolDispatcher.

        For BaseTool: calls async execute(args).
        For Tool: wraps sync run(validated_args) into a string result.
        Returns a string result suitable for Gemini FunctionResponse.
        """
        tool = self.get(tool_name)
        if tool is None:
            return f"Error: Unknown tool '{tool_name}'"

        start = time.monotonic()

        try:
            if isinstance(tool, BaseTool):
                result_str = await tool.execute(args)
                duration_ms = (time.monotonic() - start) * 1000
                log_tool_call(
                    tool=tool_name,
                    arguments=args,
                    permission_level="AUTO",
                    success=True,
                    duration_ms=duration_ms,
                )
                return result_str
            else:
                # v1 Tool: validate, run, verify
                validated_args = tool.parse_arguments(args)
                result = tool.run(validated_args)
                result = tool.verify(validated_args, result)
                duration_ms = (time.monotonic() - start) * 1000
                log_tool_call(
                    tool=tool_name,
                    arguments=args,
                    permission_level=tool.permission_level.value,
                    success=result.success,
                    duration_ms=duration_ms,
                    error=result.error,
                )
                return result.message
        except Exception as exc:
            duration_ms = (time.monotonic() - start) * 1000
            log_tool_call(
                tool=tool_name,
                arguments=args,
                permission_level="UNKNOWN",
                success=False,
                duration_ms=duration_ms,
                error=str(exc),
            )
            return f"Error executing {tool_name}: {exc}"

    # --- v1 synchronous dispatch (kept for backward compat) ----

    def dispatch(
        self, request: ToolCallRequest, confirmed: bool = False
    ) -> ToolResult:
        """
        Execute a tool call request end to end (v1 sync path).
        Always returns a ToolResult — never raises.
        """
        start = time.monotonic()
        tool = self.get(request.tool)

        if tool is None:
            result = ToolResult(
                success=False,
                tool=request.tool,
                message=f"Unknown tool: {request.tool}",
                error="unknown_tool",
            )
            self._log(request, "UNKNOWN", result, start)
            return result

        if not isinstance(tool, Tool):
            result = ToolResult(
                success=False,
                tool=request.tool,
                message=f"Tool {request.tool} is async-only (BaseTool); use execute() instead.",
                error="wrong_dispatch_method",
            )
            self._log(request, "N/A", result, start)
            return result

        try:
            args = tool.parse_arguments(request.arguments)
        except ToolValidationError as exc:
            result = ToolResult(
                success=False,
                tool=tool.name,
                message=f"Invalid arguments for {tool.name}: {exc}",
                error="invalid_arguments",
            )
            self._log(request, tool.permission_level.value, result, start)
            return result

        decision = self._permission_engine.decide(tool.classify(args), confirmed)
        effective_level = tool.classify(args)
        if decision is not PermissionDecision.ALLOWED:
            reason = self._permission_engine.explain(effective_level, decision)
            result = ToolResult(
                success=False,
                tool=tool.name,
                message=reason,
                error="permission_denied",
            )
            self._log(request, effective_level.value, result, start)
            return result

        try:
            result = tool.run(args)
        except Exception as exc:  # noqa: BLE001 - deliberate safety net
            logger.exception("tool_execution_raised", extra={"payload": {"tool": tool.name}})
            result = ToolResult(
                success=False,
                tool=tool.name,
                message=f"{tool.name} failed unexpectedly: {exc}",
                error="unhandled_exception",
            )
            self._log(request, effective_level.value, result, start)
            return result

        try:
            result = tool.verify(args, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("tool_verification_raised", extra={"payload": {"tool": tool.name}})
            result = ToolResult(
                success=False,
                tool=tool.name,
                message=f"{tool.name} could not be verified: {exc}",
                error="verification_failed",
            )

        self._log(request, effective_level.value, result, start)
        return result

    def _log(
        self,
        request: ToolCallRequest,
        permission_level: str,
        result: ToolResult,
        start: float,
    ) -> None:
        duration_ms = (time.monotonic() - start) * 1000
        log_tool_call(
            tool=request.tool,
            arguments=request.arguments,
            permission_level=permission_level,
            success=result.success,
            duration_ms=duration_ms,
            error=result.error,
        )