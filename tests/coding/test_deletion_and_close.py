"""
Tests for permission-controlled file deletion and workspace VS Code window closing.
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from app.coding.controller import CodingComputerController
from app.coding.vscode import VSCodeLauncher
from app.config import CodingConfig
from app.tools.coding.tool import (
    CloseVSCodeTool,
    CodingCloseVSCodeTool,
    CodingDeleteFileTool,
    DeleteFileTool,
    get_coding_controller,
)
from app.tools.tool_setup import build_tool_registry


@pytest.fixture
def controller_with_tmp_workspace(tmp_path: Path):
    cfg = CodingConfig(approved_workspace_roots=[str(tmp_path)])
    controller = CodingComputerController(config=cfg)
    controller.resolve_and_set_workspace(str(tmp_path))
    return controller


def test_delete_file_requires_confirmation(controller_with_tmp_workspace: CodingComputerController, tmp_path: Path):
    test_file = tmp_path / "delete_me.txt"
    test_file.write_text("important data", encoding="utf-8")

    # Without confirmation (user_confirmed=False)
    result = controller_with_tmp_workspace.delete_workspace_file("delete_me.txt", user_confirmed=False)

    assert result["status"] == "confirmation_required"
    assert "CONFIRMATION REQUIRED" in result["message"]
    assert "HIGH" in result["message"]
    # File must NOT be deleted
    assert test_file.exists()
    assert test_file.read_text(encoding="utf-8") == "important data"


def test_delete_file_confirmed_success(controller_with_tmp_workspace: CodingComputerController, tmp_path: Path):
    test_file = tmp_path / "temp.py"
    test_file.write_text("print('temporary')", encoding="utf-8")

    # With confirmation (user_confirmed=True)
    result = controller_with_tmp_workspace.delete_workspace_file("temp.py", user_confirmed=True)

    assert result["status"] == "success"
    assert "Successfully deleted" in result["message"]
    assert not test_file.exists()


def test_delete_file_rejects_directory(controller_with_tmp_workspace: CodingComputerController, tmp_path: Path):
    test_dir = tmp_path / "subfolder"
    test_dir.mkdir()

    result = controller_with_tmp_workspace.delete_workspace_file("subfolder", user_confirmed=True)

    assert result["status"] == "error"
    assert "is a directory" in result["message"]
    assert test_dir.exists()


def test_delete_file_rejects_path_traversal(controller_with_tmp_workspace: CodingComputerController, tmp_path: Path):
    outside_file = tmp_path.parent / "outside.txt"
    outside_file.write_text("secret", encoding="utf-8")

    result = controller_with_tmp_workspace.delete_workspace_file("../outside.txt", user_confirmed=True)

    assert result["status"] == "security_error"
    assert "outside the approved workspace" in result["message"]
    assert outside_file.exists()
    try:
        outside_file.unlink()
    except Exception:
        pass


def test_delete_file_rejects_nonexistent(controller_with_tmp_workspace: CodingComputerController):
    result = controller_with_tmp_workspace.delete_workspace_file("ghost.txt", user_confirmed=True)

    assert result["status"] == "error"
    assert "does not exist" in result["message"]


def test_close_vscode_requires_confirmation(controller_with_tmp_workspace: CodingComputerController):
    # Without confirmation (user_confirmed=False)
    result = controller_with_tmp_workspace.close_workspace_vscode(user_confirmed=False)

    assert result["status"] == "confirmation_required"
    assert "CONFIRMATION REQUIRED" in result["message"]
    assert "MEDIUM" in result["message"]


def test_close_vscode_confirmed_when_no_window(controller_with_tmp_workspace: CodingComputerController):
    # With confirmation, when no window is matching the temp directory
    result = controller_with_tmp_workspace.close_workspace_vscode(user_confirmed=True)

    assert result["status"] == "not_found"
    assert "No open VS Code window found" in result["message"]


def test_close_vscode_calls_launcher(controller_with_tmp_workspace: CodingComputerController):
    with patch.object(controller_with_tmp_workspace.vscode, "close_workspace_window") as mock_close:
        mock_close.return_value = (True, "Closed window")
        result = controller_with_tmp_workspace.close_workspace_vscode(user_confirmed=True)

        assert result["status"] == "success"
        assert result["message"] == "Closed window"
        mock_close.assert_called_once()


@pytest.mark.asyncio
async def test_tools_execution_via_basetool(tmp_path: Path):
    controller = get_coding_controller()
    controller.config.approved_workspace_roots.append(str(tmp_path))
    controller.resolver = controller.resolver.__class__(controller.config.approved_workspace_roots)
    controller.resolve_and_set_workspace(str(tmp_path))

    # Test delete_file tool
    f = tmp_path / "tool_test.txt"
    f.write_text("hello", encoding="utf-8")

    del_tool = DeleteFileTool()
    # 1. Unconfirmed
    res_unconfirmed = await del_tool.execute({"path": "tool_test.txt", "user_confirmed": False})
    assert "CONFIRMATION REQUIRED" in res_unconfirmed
    assert f.exists()

    # 2. Confirmed
    res_confirmed = await del_tool.execute({"path": "tool_test.txt", "user_confirmed": True})
    assert "Successfully deleted" in res_confirmed
    assert not f.exists()

    # Test close_vscode tool
    close_tool = CloseVSCodeTool()
    res_close_unconfirmed = await close_tool.execute({"user_confirmed": False})
    assert "CONFIRMATION REQUIRED" in res_close_unconfirmed

    res_close_confirmed = await close_tool.execute({"user_confirmed": True})
    assert "VS Code" in res_close_confirmed


def test_tools_registered_in_registry():
    registry = build_tool_registry()
    assert registry.get("delete_file") is not None
    assert registry.get("coding_delete_file") is not None
    assert registry.get("close_vscode") is not None
    assert registry.get("coding_close_vscode") is not None
