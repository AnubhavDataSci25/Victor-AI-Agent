"""
Unit tests for Victor 2.0 tools, computer tools, and factory shim.
"""

from pathlib import Path
import os
import pytest

from app.tools.computer.tool import ComputerTakeScreenshotTool
from app.tools.system.tool import SystemVolumeTool
from app.tools.factory import build_registry


@pytest.mark.asyncio
async def test_computer_take_screenshot_creates_file():
    tool = ComputerTakeScreenshotTool()
    res = await tool.execute({})
    assert "Screenshot successfully taken" in res

    # Extract file path
    prefix = "saved to "
    idx = res.find(prefix)
    assert idx != -1
    file_path_str = res[idx + len(prefix):].rstrip(".")
    file_path = Path(file_path_str)

    assert file_path.exists()
    assert file_path.stat().st_size > 0

    # Clean up created screenshot
    try:
        file_path.unlink()
    except Exception:
        pass


@pytest.mark.asyncio
async def test_system_volume_tool_handles_string_steps():
    tool = SystemVolumeTool()
    # Test mute
    res = await tool.execute({"action": "mute"})
    assert "mute" in res.lower()

    # Test string steps (should not raise TypeError)
    res_up = await tool.execute({"action": "up", "steps": "2"})
    assert "2 steps" in res_up


def test_factory_shim_returns_registry():
    registry = build_registry()
    tools = registry.list_tools()
    assert len(tools) >= 20
    names = [t["name"] for t in tools]
    assert "browser_search_web" in names
    assert "system_adjust_volume" in names
    assert "computer_take_screenshot" in names
