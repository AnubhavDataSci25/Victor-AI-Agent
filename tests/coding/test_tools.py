"""
Tests for Coding BaseTool implementations and ToolRegistry integration.
"""

from pathlib import Path
import pytest

from app.tools.coding.tool import (
    CodingExecuteTaskTool,
    CodingGetWorkspaceStatusTool,
    CodingResolveWorkspaceTool,
    CodingRunCommandTool,
    get_coding_controller,
)
from app.tools.tool_setup import build_tool_registry


@pytest.mark.asyncio
async def test_coding_tools_registered_in_registry():
    registry = build_tool_registry()
    assert registry.get("coding_resolve_workspace") is not None
    assert registry.get("coding_execute_task") is not None
    assert registry.get("coding_run_command") is not None
    assert registry.get("coding_get_workspace_status") is not None


@pytest.mark.asyncio
async def test_resolve_workspace_tool(tmp_path: Path):
    controller = get_coding_controller()
    controller.config.approved_workspace_roots.append(str(tmp_path))
    controller.resolver = controller.resolver.__class__(controller.config.approved_workspace_roots)

    project_dir = tmp_path / "MyProject"
    project_dir.mkdir()
    (project_dir / "requirements.txt").write_text("pytest\nfastapi", encoding="utf-8")

    tool = CodingResolveWorkspaceTool()
    res = await tool.execute({"target": str(project_dir)})

    assert "Successfully resolved workspace" in res
    assert "MyProject" in res
    assert "fastapi" in res.lower() or "python" in res.lower()


@pytest.mark.asyncio
async def test_workspace_status_tool(tmp_path: Path):
    controller = get_coding_controller()
    controller.config.approved_workspace_roots.append(str(tmp_path))
    controller.resolver = controller.resolver.__class__(controller.config.approved_workspace_roots)

    project_dir = tmp_path / "ActiveProj"
    project_dir.mkdir()
    controller.resolve_and_set_workspace(str(project_dir))

    tool = CodingGetWorkspaceStatusTool()
    res = await tool.execute({})

    assert "Active Workspace:" in res
    assert "ActiveProj" in res


@pytest.mark.asyncio
async def test_run_command_tool_with_active_workspace(tmp_path: Path):
    controller = get_coding_controller()
    controller.config.approved_workspace_roots.append(str(tmp_path))
    controller.resolver = controller.resolver.__class__(controller.config.approved_workspace_roots)

    project_dir = tmp_path / "RunProj"
    project_dir.mkdir()
    controller.resolve_and_set_workspace(str(project_dir))

    tool = CodingRunCommandTool()
    res = await tool.execute({"command": "python --version"})

    assert "Exit Code: 0" in res
    assert "Python" in res
