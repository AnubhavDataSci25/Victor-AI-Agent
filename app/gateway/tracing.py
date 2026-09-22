"""
Sanitized Execution Tracing for Victor's Central Tool Gateway.

Maintains an auditable milestone trace for every meaningful action:
REQUEST -> INTENT -> DECISION -> SECURITY CHECK -> TOOL -> RESULT -> VERIFICATION -> RESPONSE

Enforces strict zero-leak redaction:
- Never logs PINs, passwords, API keys, bearer tokens, cookies, biometric data, or base64 audio.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional
from app.gateway.models import ExecutionTrace, TraceStep

logger = logging.getLogger(__name__)

# Keys whose values must always be redacted
SENSITIVE_KEY_PATTERNS = re.compile(
    r"(pin|password|passwd|secret|api_?key|token|auth|credential|cookie|biometric|session_token)",
    re.I,
)

# Secret pattern regexes (e.g. Google keys, OpenAI/OpenRouter keys, Bearer tokens, JWTs, inline PINs)
SECRET_VALUE_PATTERNS = [
    re.compile(r"AIzaSy[A-Za-z0-9_\-]{33}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}", re.I),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]+"),
    re.compile(r"\b(pin[:\s=]+)(\d{4,8})\b", re.I),
]


def redact_sensitive(data: Any) -> Any:
    """Recursively redact secrets, credentials, and tokens from any dictionary, list, or string."""
    if hasattr(data, "model_dump") and callable(data.model_dump):
        data = data.model_dump()

    if isinstance(data, dict):
        redacted = {}
        for k, v in data.items():
            if SENSITIVE_KEY_PATTERNS.search(str(k)):
                redacted[k] = "[REDACTED]"
            elif str(k).lower() in ("data", "pcm") and isinstance(v, str) and len(v) > 100:
                redacted[k] = f"[BINARY_BLOB: {len(v)} chars]"
            else:
                redacted[k] = redact_sensitive(v)
        return redacted
    elif isinstance(data, (list, tuple, set)):
        return [redact_sensitive(item) for item in data]
    elif isinstance(data, str):
        val = data
        for pat in SECRET_VALUE_PATTERNS:
            if "pin" in pat.pattern:
                val = pat.sub(r"\g<1>[REDACTED_PIN]", val)
            else:
                val = pat.sub("[REDACTED_SECRET]", val)
        return val
    return data


class ExecutionTracer:
    """Manages and records sanitized execution traces."""

    def __init__(self, max_traces: int = 100) -> None:
        self._max_traces = max_traces
        self._traces: List[ExecutionTrace] = []

    def start_trace(self, tool_name: str) -> ExecutionTrace:
        """Initialize a new trace with the initial REQUEST_RECEIVED milestone."""
        trace = ExecutionTrace(tool_name=tool_name)
        trace.add_step("REQUEST_RECEIVED", status="ok", details={"tool": tool_name})
        return trace

    def record_step(
        self,
        trace: ExecutionTrace,
        phase: str,
        status: str = "ok",
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record a milestone step with sanitized details."""
        sanitized_details = redact_sensitive(details or {})
        trace.add_step(phase, status=status, details=sanitized_details)

    def complete_trace(
        self,
        trace: ExecutionTrace,
        success: bool,
        error: Optional[str] = None,
    ) -> None:
        """Finalize trace timing, record into ring buffer, and log audit event."""
        sanitized_error = redact_sensitive(error) if error else None
        trace.complete(success=success, error=sanitized_error)

        self._traces.append(trace)
        if len(self._traces) > self._max_traces:
            self._traces.pop(0)

        logger.info(
            f"[Trace:{trace.trace_id}] {trace.tool_name} | {trace.permission_level} | "
            f"{trace.risk_level.value} | {trace.duration_ms}ms | success={success}"
        )

    def get_traces(self, limit: int = 10) -> List[ExecutionTrace]:
        """Return the most recent traces."""
        return self._traces[-limit:]

    def format_trace_summary(self, trace: ExecutionTrace) -> str:
        """Format an execution trace as a readable multi-step diagram."""
        status_str = "SUCCESS" if trace.success else "FAILED"
        lines = [
            f"Trace ID: {trace.trace_id} | Tool: {trace.tool_name} | Status: {status_str} | Duration: {trace.duration_ms}ms"
        ]
        for step in trace.steps:
            status_badge = "[OK]" if step.status.lower() in ("ok", "success", "allowed") else f"[{step.status.upper()}]"
            detail_str = f" ({step.details})" if step.details else ""
            lines.append(f"  → {step.phase} {status_badge}{detail_str}")
        return "\n".join(lines)


# Global singleton instance
_GLOBAL_TRACER: Optional[ExecutionTracer] = None


def get_execution_tracer() -> ExecutionTracer:
    """Retrieve or initialize the global ExecutionTracer."""
    global _GLOBAL_TRACER
    if _GLOBAL_TRACER is None:
        _GLOBAL_TRACER = ExecutionTracer()
    return _GLOBAL_TRACER
