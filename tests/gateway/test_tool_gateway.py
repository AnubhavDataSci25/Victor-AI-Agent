"""
Unit tests for Victor's Central Tool Gateway (Phase 1).
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock
from google.genai import types
import pytest

from app.agent.state import VictorState
from app.gateway.models import GatewayRequest, RiskLevel
from app.gateway.tool_gateway import ToolGateway
from app.tools.base import BaseTool
from app.tools.permissions import PermissionEngine, PermissionLevel
from app.tools.registry import ToolRegistry


class DummySafeTool(BaseTool):
    name = "dummy_safe_tool"
    description = "A dummy safe tool"
    parameters = {"type": "object", "properties": {}}
    permission_level = PermissionLevel.SAFE

    async def execute(self, args: dict) -> str:
        return "Safe output"


class DummyDeleteTool(BaseTool):
    name = "dummy_delete_file"
    description = "A dummy delete tool"
    parameters = {"type": "object", "properties": {"path": {"type": "string"}}}
    permission_level = PermissionLevel.HIGH

    async def execute(self, args: dict) -> str:
        return f"Deleted {args.get('path')}"


@pytest.fixture
def mock_session():
    session = MagicMock()
    session.is_authenticated.return_value = True
    session.state = VictorState.ACTIVE
    session.lock = AsyncMock()
    return session


@pytest.fixture
def gateway():
    registry = ToolRegistry()
    registry.register(DummySafeTool())
    registry.register(DummyDeleteTool())
    engine = PermissionEngine()
    return ToolGateway(registry=registry, permission_engine=engine)


@pytest.mark.asyncio
async def test_gateway_blocks_unauthenticated_session(gateway):
    unauth_session = MagicMock()
    unauth_session.is_authenticated.return_value = False
    unauth_session.state = VictorState.LOCKED

    req = GatewayRequest(tool_name="dummy_safe_tool")
    res = await gateway.execute(req, session_manager=unauth_session)

    assert res.success is False
    assert "Access Denied" in res.error
    assert res.permission_level == "BLOCKED"


@pytest.mark.asyncio
async def test_gateway_executes_safe_tool(gateway, mock_session):
    req = GatewayRequest(tool_name="dummy_safe_tool")
    res = await gateway.execute(req, session_manager=mock_session)

    assert res.success is True
    assert res.result == "Safe output"
    assert res.risk_level == RiskLevel.READ_ONLY
    assert res.trace_id != ""


@pytest.mark.asyncio
async def test_gateway_blocks_unknown_tool(gateway, mock_session):
    req = GatewayRequest(tool_name="nonexistent_tool")
    res = await gateway.execute(req, session_manager=mock_session)

    assert res.success is False
    assert "not registered" in res.error


@pytest.mark.asyncio
async def test_gateway_destructive_tool_requires_confirmation(gateway, mock_session):
    req = GatewayRequest(tool_name="dummy_delete_file", arguments={"path": "C:/test.txt"})
    res = await gateway.execute(req, session_manager=mock_session)

    assert res.success is False
    assert res.requires_confirmation is True
    assert res.risk_level == RiskLevel.DESTRUCTIVE
    assert "destructive or high-impact" in (res.confirmation_prompt or "")


@pytest.mark.asyncio
async def test_gateway_destructive_tool_with_confirmation(gateway, mock_session):
    # With explicit confirmation, execution proceeds
    req = GatewayRequest(
        tool_name="dummy_delete_file",
        arguments={"path": "C:/test.txt"},
        is_confirmed=True,
    )
    res = await gateway.execute(req, session_manager=mock_session)

    assert res.success is True
    assert res.result == "Deleted C:/test.txt"


@pytest.mark.asyncio
async def test_gateway_records_execution_traces(gateway, mock_session):
    req = GatewayRequest(tool_name="dummy_safe_tool")
    await gateway.execute(req, session_manager=mock_session)

    traces = gateway.get_recent_traces(5)
    assert len(traces) >= 1
    last_trace = traces[-1]
    assert last_trace.tool_name == "dummy_safe_tool"
    assert last_trace.success is True
    assert last_trace.duration_ms >= 0.0

    phases = [s.phase for s in last_trace.steps]
    assert "REQUEST_RECEIVED" in phases
    assert "AUTH_CHECK" in phases
    assert "TOOL_LOOKUP" in phases
    assert "PERMISSION_CHECK" in phases
    assert "TOOL_EXECUTION_COMPLETED" in phases


@pytest.mark.asyncio
async def test_gateway_gemini_function_call_adapter(gateway, mock_session):
    fc = MagicMock()
    fc.name = "dummy_safe_tool"
    fc.args = {}
    fc.id = "call_abc123"

    f_resp = await gateway.execute_function_call(fc, session_manager=mock_session)
    assert isinstance(f_resp, types.FunctionResponse)
    assert f_resp.name == "dummy_safe_tool"
    assert f_resp.id == "call_abc123"
    assert f_resp.response.get("status") == "success"
    assert f_resp.response.get("result") == "Safe output"


def test_gateway_dynamic_tool_timeout(gateway):
    """Verify tool timeouts adapt based on tool attributes and categories."""
    assert gateway.get_tool_timeout("music_play") == 30.0
    assert gateway.get_tool_timeout("browser_open") == 30.0
    assert gateway.get_tool_timeout("coding_execute_task") == 60.0
    assert gateway.get_tool_timeout("unknown_fast_tool") == 15.0


@pytest.mark.asyncio
async def test_gateway_function_call_timeout_returns_instruction(gateway, mock_session):
    """Verify timed out function calls return failed status and prompt Gemini not to retry blindly."""
    fc = MagicMock()
    fc.name = "slow_hanging_tool"
    fc.args = {}
    fc.id = "call_timeout_99"

    async def mock_slow_execute(*args, **kwargs):
        await asyncio.sleep(0.3)

    gateway.execute = mock_slow_execute

    f_resp = await gateway.execute_function_call(fc, session_manager=mock_session, timeout_seconds=0.05)
    assert isinstance(f_resp, types.FunctionResponse)
    assert f_resp.name == "slow_hanging_tool"
    assert f_resp.response.get("status") == "failed"
    assert "timed out" in f_resp.response.get("error", "")
    assert "Do NOT retry this tool call immediately" in f_resp.response.get("result", "")

