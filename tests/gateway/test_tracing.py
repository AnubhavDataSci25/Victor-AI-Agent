"""
Unit tests for Victor Execution Tracing and Zero-Leak Redaction.
"""

import pytest
from app.gateway.models import ExecutionTrace
from app.gateway.tracing import ExecutionTracer, redact_sensitive
from app.gateway.tool_gateway import ToolGateway
from app.gateway.models import GatewayRequest
from app.tools.registry import ToolRegistry


def test_redact_sensitive_dictionary_keys():
    """Confirms sensitive key names in dictionaries are completely redacted."""
    payload = {
        "user_pin": "1234",
        "password": "supersecretpassword",
        "api_key": "dummy-key-123",
        "auth_token": "token-xyz",
        "nested": {
            "session_token": "sess-999",
            "biometric_hash": "bio-hash-abc",
            "safe_param": "visible_value",
        },
        "query": "what is the weather today?",
    }

    sanitized = redact_sensitive(payload)

    assert sanitized["user_pin"] == "[REDACTED]"
    assert sanitized["password"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["nested"]["session_token"] == "[REDACTED]"
    assert sanitized["nested"]["biometric_hash"] == "[REDACTED]"
    assert sanitized["nested"]["safe_param"] == "visible_value"
    assert sanitized["query"] == "what is the weather today?"


def test_redact_secret_patterns_in_strings():
    """Confirms API key patterns and Bearer tokens in raw strings are masked."""
    google_key = "AIzaSy" + "A" * 33
    openai_key = "sk-" + "B" * 25
    bearer_token = "Bearer " + "C" * 25
    jwt_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.doNotLeakThisSignature"
    pin_text = "The user entered PIN: 4321 into the prompt."

    text = f"Using {google_key} and {openai_key} with auth {bearer_token} and jwt {jwt_token}. {pin_text}"

    sanitized = redact_sensitive(text)

    assert google_key not in sanitized
    assert openai_key not in sanitized
    assert bearer_token not in sanitized
    assert jwt_token not in sanitized
    assert "4321" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized
    assert "[REDACTED_PIN]" in sanitized


def test_redact_large_binary_blobs():
    """Confirms base64 audio and data payloads are truncated into size indicators."""
    long_audio = "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQAAAAA" * 10
    payload = {
        "pcm": long_audio,
        "data": long_audio,
        "filename": "audio.wav",
    }

    sanitized = redact_sensitive(payload)

    assert "[BINARY_BLOB:" in sanitized["pcm"]
    assert "[BINARY_BLOB:" in sanitized["data"]
    assert sanitized["filename"] == "audio.wav"


def test_execution_tracer_lifecycle_and_ring_buffer():
    """Confirms trace creation, recording, completion, and eviction in ring buffer."""
    tracer = ExecutionTracer(max_traces=3)

    trace1 = tracer.start_trace("tool_1")
    tracer.record_step(trace1, "STEP_A", details={"password": "leak"})
    tracer.complete_trace(trace1, success=True)

    assert trace1.steps[1].details["password"] == "[REDACTED]"
    assert trace1.duration_ms >= 0

    trace2 = tracer.start_trace("tool_2")
    tracer.complete_trace(trace2, success=True)

    trace3 = tracer.start_trace("tool_3")
    tracer.complete_trace(trace3, success=True)

    traces = tracer.get_traces()
    assert len(traces) == 3
    assert [t.tool_name for t in traces] == ["tool_1", "tool_2", "tool_3"]

    # Exceed buffer capacity
    trace4 = tracer.start_trace("tool_4")
    tracer.complete_trace(trace4, success=True)

    traces = tracer.get_traces()
    assert len(traces) == 3
    # tool_1 should be evicted
    assert [t.tool_name for t in traces] == ["tool_2", "tool_3", "tool_4"]


def test_trace_summary_formatting():
    """Confirms readable summary representation of execution trace."""
    tracer = ExecutionTracer()
    trace = tracer.start_trace("system_info")
    tracer.record_step(trace, "AUTH_CHECK", status="ok")
    tracer.record_step(trace, "RESULT_VERIFICATION", status="ok", details={"verified": True})
    tracer.complete_trace(trace, success=True)

    summary = tracer.format_trace_summary(trace)
    assert "Tool: system_info" in summary
    assert "SUCCESS" in summary
    assert "→ REQUEST_RECEIVED [OK]" in summary
    assert "→ AUTH_CHECK [OK]" in summary
    assert "→ RESULT_VERIFICATION [OK]" in summary


@pytest.mark.asyncio
async def test_tool_gateway_records_sanitized_trace(monkeypatch):
    """Confirms ToolGateway records sanitized trace through the complete pipeline."""
    from app.tools.base import BaseTool
    from app.tools.permissions import PermissionLevel

    class EchoTool(BaseTool):
        name = "echo_tool"
        description = "Echoes input"
        parameters = {"type": "object", "properties": {"text": {"type": "string"}, "password": {"type": "string"}}}
        permission_level = PermissionLevel.SAFE

        async def execute(self, args: dict) -> str:
            return f"Echo: {args.get('text')}"

    registry = ToolRegistry()
    registry.register(EchoTool())

    tracer = ExecutionTracer(max_traces=10)
    gateway = ToolGateway(registry=registry, tracer=tracer)

    req = GatewayRequest(
        tool_name="echo_tool",
        arguments={"text": "hello", "password": "supersecretpassword123"},
    )

    result = await gateway.execute(req)
    assert result.success is True

    traces = tracer.get_traces()
    assert len(traces) == 1
    t = traces[0]
    assert t.tool_name == "echo_tool"
    assert t.success is True

    phases = [s.phase for s in t.steps]
    assert "REQUEST_RECEIVED" in phases
    assert "AUTH_CHECK" in phases
    assert "TOOL_LOOKUP" in phases
    assert "PERMISSION_CHECK" in phases
    assert "TOOL_EXECUTION_STARTED" in phases
    assert "TOOL_EXECUTION_COMPLETED" in phases
    assert "RESULT_VERIFICATION" in phases
