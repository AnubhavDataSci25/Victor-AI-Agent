"""
Tests for browser tool gateway execution, confirmation recognition,
and Gemini function response resilience.
"""

import pytest
from unittest.mock import AsyncMock, patch
from google.genai import types

from app.gateway.models import GatewayRequest
from app.gateway.tool_gateway import ToolGateway
from app.tools.browser.tool import BrowserCloseTabTool
from app.tools.registry import ToolRegistry


@pytest.fixture
def browser_gateway():
    registry = ToolRegistry()
    registry.register(BrowserCloseTabTool())
    return ToolGateway(registry=registry)


@pytest.mark.asyncio
async def test_browser_close_tab_recognized_with_user_confirmed(browser_gateway):
    """
    Confirms that browser_close_tab succeeds without getting blocked by
    PermissionEngine when user_confirmed=True is supplied.
    """
    with patch("app.tools.browser.playwright_driver.PlaywrightBrowserDriver.close_tab", new_callable=AsyncMock) as mock_close:
        mock_close.return_value = True

        req = GatewayRequest(
            tool_name="browser_close_tab",
            arguments={"user_confirmed": True},
        )
        res = await browser_gateway.execute(req)

        assert res.success is True
        assert "Active browser tab has been successfully closed" in str(res.result)
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_browser_close_tab_unconfirmed_returns_verbal_guidance(browser_gateway):
    """
    When called without confirmation, the tool execute() runs and returns verbal
    confirmation guidance rather than throwing or entering an infinite loop.
    """
    req = GatewayRequest(
        tool_name="browser_close_tab",
        arguments={},
    )
    res = await browser_gateway.execute(req)

    # Tool executes safely and returns the confirmation prompt string
    assert "CONFIRMATION REQUIRED" in str(res.result)


@pytest.mark.asyncio
async def test_execute_function_call_always_has_result_key(browser_gateway):
    """
    Confirms types.FunctionResponse response always contains 'result' key,
    ensuring Gemini Live can verbally synthesize tool outputs without looping.
    """
    # 1. Success case
    fc_success = types.FunctionCall(
        name="browser_close_tab",
        args={"user_confirmed": True},
        id="call_1",
    )
    with patch("app.tools.browser.playwright_driver.PlaywrightBrowserDriver.close_tab", new_callable=AsyncMock) as mock_close:
        mock_close.return_value = True
        resp_success = await browser_gateway.execute_function_call(fc_success)
        assert "result" in resp_success.response

    # 2. Unknown tool failure case
    fc_fail = types.FunctionCall(
        name="unknown_tool_xyz",
        args={},
        id="call_2",
    )
    resp_fail = await browser_gateway.execute_function_call(fc_fail)
    assert "result" in resp_fail.response
    assert resp_fail.response["status"] == "failed"
