"""
Integration tests ensuring all 7 Public API tools are registered in Victor's ToolRegistry
and properly converted to Gemini Live function declarations.
"""

import pytest

from app.tools.schemas import get_gemini_tools
from app.tools.tool_setup import build_tool_registry


def test_public_api_tools_registered_in_registry():
    registry = build_tool_registry()
    tools = registry.get_all_tools()

    expected_tool_names = [
        "api_get_weather",
        "api_get_stock_price",
        "api_get_forex_rate",
        "api_get_crypto_price",
        "api_get_news_headlines",
        "api_get_public_ip_info",
        "api_get_public_holidays",
    ]

    for name in expected_tool_names:
        assert name in tools, f"Expected tool '{name}' not found in registry"
        tool = tools[name]
        assert hasattr(tool, "execute")
        assert hasattr(tool, "parameters")
        assert tool.permission_level.value == "SAFE"


def test_public_api_tools_in_gemini_schemas():
    gemini_tools = get_gemini_tools()
    assert len(gemini_tools) == 1

    fn_declarations = gemini_tools[0].function_declarations
    declared_names = {fn.name for fn in fn_declarations}

    expected_tool_names = [
        "api_get_weather",
        "api_get_stock_price",
        "api_get_forex_rate",
        "api_get_crypto_price",
        "api_get_news_headlines",
        "api_get_public_ip_info",
        "api_get_public_holidays",
    ]

    for name in expected_tool_names:
        assert name in declared_names, f"Tool '{name}' missing from Gemini function declarations"
