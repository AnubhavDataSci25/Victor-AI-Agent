"""
Central Tool Gateway for Victor.

Acts as the single controlled choke-point for all tool executions across Victor:
1. Validates session state and 2FA authentication (PIN + Windows Hello).
2. Looks up tool in the existing ToolRegistry.
3. Classifies action risk (READ_ONLY, LOW_RISK, MODERATE_RISK, DESTRUCTIVE, EXTERNAL_SIDE_EFFECT).
4. Enforces Layer 2 authorization via the existing PermissionEngine.
5. Halts and requires explicit user confirmation for high-risk / destructive actions.
6. Deterministically executes the tool asynchronously.
7. Dispatches raw results to ResultVerifier.
8. Emits structured, redacted audit traces.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional
from google.genai import types

from app.gateway.models import ExecutionTrace, GatewayRequest, GatewayResult, RiskLevel
from app.logging import get_logger, log_tool_call
from app.tools.base import BaseTool, Tool
from app.tools.permissions import PermissionDecision, PermissionEngine, PermissionLevel
from app.tools.registry import ToolRegistry
from app.tools.tool_setup import build_tool_registry

logger = get_logger("gateway.tool_gateway")

# Privileged tools that perform destructive modifications
DESTRUCTIVE_TOOL_NAMES = {
    "delete_file",
    "coding_delete_file",
    "file_explorer_delete",
    "phone_unpair",
    "memory_forget",
    "reminder_delete",
}

# Tools that produce real-world external side-effects
EXTERNAL_SIDE_EFFECT_TOOLS = {
    "phone_initiate_call",
    "phone_answer_call",
    "phone_reject_call",
    "google_calendar_create_event",
    "google_meet_create",
    "coding_execute_task",
    "coding_run_command",
    "file_explorer_move",
    "file_explorer_rename",
    "computer_submit_form",
}


class ToolGateway:
    """Central gateway orchestrating security, permissions, execution, and verification."""

    def __init__(
        self,
        registry: Optional[ToolRegistry] = None,
        permission_engine: Optional[PermissionEngine] = None,
        verifier: Optional[Any] = None,
        tracer: Optional[Any] = None,
    ) -> None:
        self.registry = registry or build_tool_registry()
        self.permission_engine = permission_engine or PermissionEngine()
        if verifier is None:
            from app.verification.verifier import ResultVerifier
            self.verifier = ResultVerifier()
        else:
            self.verifier = verifier

        if tracer is None:
            from app.gateway.tracing import get_execution_tracer
            self.tracer = get_execution_tracer()
        else:
            self.tracer = tracer

    def classify_risk(self, tool_name: str, args: Dict[str, Any]) -> RiskLevel:
        """Deterministically determine the risk level of an invocation."""
        name_lower = tool_name.lower()

        if name_lower in DESTRUCTIVE_TOOL_NAMES or any(k in name_lower for k in ("delete", "remove", "unlink")):
            return RiskLevel.DESTRUCTIVE

        if name_lower in EXTERNAL_SIDE_EFFECT_TOOLS or any(k in name_lower for k in ("move", "rename", "call", "schedule")):
            return RiskLevel.EXTERNAL_SIDE_EFFECT

        if any(k in name_lower for k in ("create", "write", "adjust", "open_url", "launch")):
            return RiskLevel.LOW_RISK

        return RiskLevel.READ_ONLY

    def _record_step(
        self,
        trace: ExecutionTrace,
        phase: str,
        status: str = "ok",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record an execution milestone through the tracer with sanitization."""
        if hasattr(self, "tracer") and hasattr(self.tracer, "record_step"):
            self.tracer.record_step(trace, phase, status=status, details=details)
        else:
            trace.add_step(phase, status=status, details=details)

    async def execute(
        self,
        request: GatewayRequest,
        session_manager: Optional[Any] = None,
    ) -> GatewayResult:
        """
        Execute a tool request through the complete gateway pipeline.
        Enforces: Auth -> Discovery -> Risk -> Permission -> Execution -> Verification -> Trace.
        """
        start_time = time.monotonic()
        trace = ExecutionTrace(tool_name=request.tool_name)
        self._record_step(trace, "REQUEST_RECEIVED", details={"tool": request.tool_name})

        # 1. Authentication & Session State Check
        if session_manager is not None:
            if hasattr(session_manager, "is_authenticated") and not session_manager.is_authenticated():
                err_msg = "Access Denied: Victor session is not authenticated with biometric verification."
                self._record_step(trace, "AUTH_CHECK", status="failed", details={"error": "unauthenticated"})
                trace.complete(success=False, error=err_msg)
                self._record_trace(trace)
                return GatewayResult(
                    tool_name=request.tool_name,
                    success=False,
                    error=err_msg,
                    permission_level="BLOCKED",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                    trace_id=trace.trace_id,
                )

            # Session state must be actively operational
            state_val = getattr(getattr(session_manager, "state", None), "value", None)
            if state_val and str(state_val).upper() not in ("ACTIVE", "EXECUTING", "SPEAKING"):
                err_msg = "Access Denied: Victor session is locked or inactive."
                self._record_step(trace, "SESSION_STATE_CHECK", status="failed", details={"state": state_val})
                trace.complete(success=False, error=err_msg)
                self._record_trace(trace)
                return GatewayResult(
                    tool_name=request.tool_name,
                    success=False,
                    error=err_msg,
                    permission_level="BLOCKED",
                    duration_ms=(time.monotonic() - start_time) * 1000,
                    trace_id=trace.trace_id,
                )

        self._record_step(trace, "AUTH_CHECK", status="ok")

        # 2. Tool Lookup in Registry
        tool = self.registry.get_tool(request.tool_name)
        if tool is None:
            err_msg = f"Tool '{request.tool_name}' is not registered."
            self._record_step(trace, "TOOL_LOOKUP", status="failed", details={"error": "not_found"})
            trace.complete(success=False, error=err_msg)
            self._record_trace(trace)
            return GatewayResult(
                tool_name=request.tool_name,
                success=False,
                error=err_msg,
                permission_level="UNKNOWN",
                duration_ms=(time.monotonic() - start_time) * 1000,
                trace_id=trace.trace_id,
            )

        self._record_step(trace, "TOOL_LOOKUP", status="ok")

        # 3. Risk & Permission Evaluation
        risk_level = self.classify_risk(request.tool_name, request.arguments)
        trace.risk_level = risk_level

        # Extract permission level
        if isinstance(tool, Tool):
            try:
                validated_args = tool.parse_arguments(request.arguments)
                perm_level = tool.classify(validated_args)
            except Exception as e:
                err_msg = f"Argument validation error: {e}"
                trace.complete(success=False, error=err_msg)
                self._record_trace(trace)
                return GatewayResult(
                    tool_name=request.tool_name,
                    success=False,
                    error=err_msg,
                    risk_level=risk_level,
                    duration_ms=(time.monotonic() - start_time) * 1000,
                    trace_id=trace.trace_id,
                )
        elif isinstance(tool, BaseTool):
            perm_level = getattr(tool, "permission_level", PermissionLevel.SAFE)
            validated_args = None
        else:
            perm_level = PermissionLevel.SAFE
            validated_args = None

        trace.permission_level = perm_level.value

        # Check explicit confirmation for high-risk / destructive actions
        is_confirmed = (
            request.is_confirmed
            or bool(request.arguments.get("confirmed", False))
            or bool(request.arguments.get("user_confirmed", False))
        )

        if perm_level == PermissionLevel.BLOCKED:
            perm_decision = PermissionDecision.DENIED
        elif is_confirmed:
            perm_decision = PermissionDecision.ALLOWED
        elif risk_level == RiskLevel.DESTRUCTIVE:
            perm_decision = PermissionDecision.REQUIRES_CONFIRMATION
        elif isinstance(tool, Tool):
            perm_decision = self.permission_engine.decide(perm_level, confirmed=is_confirmed)
        else:
            # BaseTool handles its own specialized verbal confirmations in execute()
            perm_decision = PermissionDecision.ALLOWED

        self._record_step(
            trace,
            "PERMISSION_CHECK",
            status=perm_decision.value,
            details={"level": perm_level.value, "risk": risk_level.value, "confirmed": is_confirmed},
        )

        if perm_decision == PermissionDecision.REQUIRES_CONFIRMATION:
            prompt = (
                f"Sir, '{request.tool_name}' is a destructive or high-impact operation. "
                "Please confirm if you would like me to proceed with this action."
            )
            trace.complete(success=False, error="confirmation_required")
            self._record_trace(trace)
            return GatewayResult(
                tool_name=request.tool_name,
                success=False,
                error="Confirmation required",
                permission_level=perm_level.value,
                risk_level=risk_level,
                requires_confirmation=True,
                confirmation_prompt=prompt,
                duration_ms=(time.monotonic() - start_time) * 1000,
                trace_id=trace.trace_id,
            )

        if perm_decision == PermissionDecision.DENIED:
            reason = self.permission_engine.explain(perm_level, perm_decision)
            err_msg = f"Permission Denied: {reason}"
            trace.complete(success=False, error=err_msg)
            self._record_trace(trace)
            return GatewayResult(
                tool_name=request.tool_name,
                success=False,
                error=err_msg,
                permission_level=perm_level.value,
                risk_level=risk_level,
                duration_ms=(time.monotonic() - start_time) * 1000,
                trace_id=trace.trace_id,
            )

        # 4. Tool Execution
        self._record_step(trace, "TOOL_EXECUTION_STARTED")
        try:
            if isinstance(tool, BaseTool):
                raw_result = await tool.execute(request.arguments)
            elif isinstance(tool, Tool):
                tool_res = tool.run(validated_args)
                tool_res = tool.verify(validated_args, tool_res)
                raw_result = tool_res.message
            else:
                raw_result = await self.registry.execute(request.tool_name, request.arguments)

            self._record_step(trace, "TOOL_EXECUTION_COMPLETED", status="ok")
        except Exception as exc:
            duration_ms = (time.monotonic() - start_time) * 1000
            err_msg = f"Tool execution failed: {exc}"
            logger.error(f"[Gateway] {request.tool_name} error: {exc}")
            self._record_step(trace, "TOOL_EXECUTION_COMPLETED", status="failed", details={"error": str(exc)})
            trace.complete(success=False, error=err_msg)
            self._record_trace(trace)
            log_tool_call(
                tool=request.tool_name,
                arguments=request.arguments,
                permission_level=perm_level.value,
                success=False,
                duration_ms=duration_ms,
                error=str(exc),
            )
            return GatewayResult(
                tool_name=request.tool_name,
                success=False,
                error=err_msg,
                permission_level=perm_level.value,
                risk_level=risk_level,
                duration_ms=duration_ms,
                trace_id=trace.trace_id,
            )

        # 5. Result Verification Hook
        verification_res = await self.verifier.verify(request.tool_name, request.arguments, raw_result)
        self._record_step(
            trace,
            "RESULT_VERIFICATION",
            status=verification_res.status.value,
            details={"details": verification_res.details, "verified": verification_res.verified},
        )

        duration_ms = (time.monotonic() - start_time) * 1000
        trace.complete(success=verification_res.verified)
        self._record_trace(trace)

        log_tool_call(
            tool=request.tool_name,
            arguments=request.arguments,
            permission_level=perm_level.value,
            success=verification_res.verified,
            duration_ms=duration_ms,
        )

        return GatewayResult(
            tool_name=request.tool_name,
            success=verification_res.verified,
            result=raw_result,
            permission_level=perm_level.value,
            risk_level=risk_level,
            verified=verification_res.verified,
            verification_details=verification_res.details,
            duration_ms=duration_ms,
            trace_id=trace.trace_id,
        )

    async def execute_function_call(
        self,
        function_call: Any,
        session_manager: Optional[Any] = None,
    ) -> types.FunctionResponse:
        """Adapter for Gemini Live function calls."""
        tool_name = function_call.name
        args = function_call.args if hasattr(function_call, "args") and function_call.args else {}
        call_id = getattr(function_call, "id", None)

        request = GatewayRequest(
            tool_name=tool_name,
            arguments=args if isinstance(args, dict) else {},
            call_id=call_id,
        )

        gateway_res = await self.execute(request, session_manager=session_manager)

        # Handle privileged lifecycle action 'lock_victor'
        if gateway_res.success and tool_name == "lock_victor" and session_manager is not None:
            logger.info("[Tool Gateway] Privileged lifecycle action: 'lock_victor' invoked.")
            asyncio.create_task(self._delayed_lock(session_manager))

        if gateway_res.success:
            return types.FunctionResponse(
                name=tool_name,
                id=call_id,
                response={"result": gateway_res.result, "status": "success", "trace_id": gateway_res.trace_id},
            )

        if gateway_res.requires_confirmation:
            return types.FunctionResponse(
                name=tool_name,
                id=call_id,
                response={
                    "result": gateway_res.confirmation_prompt,
                    "status": "requires_confirmation",
                    "confirmation_prompt": gateway_res.confirmation_prompt,
                    "risk_level": gateway_res.risk_level.value,
                },
            )

        return types.FunctionResponse(
            name=tool_name,
            id=call_id,
            response={
                "result": gateway_res.error or "Execution failed",
                "error": gateway_res.error or "Execution failed",
                "status": "failed",
            },
        )

    async def _delayed_lock(self, session_manager: Any) -> None:
        """Allows response to flush through WebSocket before locking down."""
        await asyncio.sleep(0.5)
        await session_manager.lock()

    def _record_trace(self, trace: ExecutionTrace) -> None:
        """Store trace into tracer ring buffer."""
        if hasattr(self, "tracer") and hasattr(self.tracer, "complete_trace"):
            self.tracer.complete_trace(trace, success=trace.success, error=trace.error)

    def get_recent_traces(self, limit: int = 10) -> list[ExecutionTrace]:
        """Retrieve the most recent execution traces."""
        if hasattr(self, "tracer") and hasattr(self.tracer, "get_traces"):
            return self.tracer.get_traces(limit=limit)
        return []


# Global singleton instance
_GLOBAL_GATEWAY: Optional[ToolGateway] = None


def get_tool_gateway() -> ToolGateway:
    """Retrieve or initialize the global ToolGateway instance."""
    global _GLOBAL_GATEWAY
    if _GLOBAL_GATEWAY is None:
        _GLOBAL_GATEWAY = ToolGateway()
    return _GLOBAL_GATEWAY
