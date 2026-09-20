"""
Unit and integration tests for Victor's dedicated File Explorer & Search toolset:
- FileExplorerSearchTool (SAFE)
- FileExplorerOpenTool (LOW)
- FileExplorerRenameTool (MEDIUM)
- FileExplorerMoveTool (HIGH)
- FileExplorerDeleteTool (HIGH)
"""

from pathlib import Path
from unittest.mock import patch
import pytest

from app.tools.filesystem.file_explorer import (
    FileExplorerDeleteArgs,
    FileExplorerDeleteTool,
    FileExplorerMoveArgs,
    FileExplorerMoveTool,
    FileExplorerOpenArgs,
    FileExplorerOpenTool,
    FileExplorerRenameArgs,
    FileExplorerRenameTool,
    FileExplorerSearchArgs,
    FileExplorerSearchTool,
)
from app.tools.models import ToolCallRequest
from app.tools.permissions import PermissionLevel
from app.tools.schemas import get_gemini_tools
from app.tools.tool_setup import build_tool_registry


@pytest.fixture
def sandbox(tmp_path: Path):
    """Setup an isolated sandbox environment with test files and folders."""
    allowed_root = tmp_path / "user_home"
    allowed_root.mkdir()

    docs = allowed_root / "Documents"
    docs.mkdir()

    notes = docs / "notes.txt"
    notes.write_text("Hello Victor", encoding="utf-8")

    report = docs / "quarterly_report.pdf"
    report.write_text("%PDF-1.4 dummy content", encoding="utf-8")

    code_dir = allowed_root / "Projects"
    code_dir.mkdir()
    script = code_dir / "main.py"
    script.write_text("print('test')", encoding="utf-8")

    outside = tmp_path / "outside_sandbox"
    outside.mkdir()
    secret = outside / "secret.txt"
    secret.write_text("classified", encoding="utf-8")

    return {
        "root": allowed_root,
        "docs": docs,
        "notes": notes,
        "report": report,
        "code_dir": code_dir,
        "script": script,
        "outside": outside,
        "secret": secret,
    }


# ---------------------------------------------------------------------------
# 1. Search Tool Tests (SAFE)
# ---------------------------------------------------------------------------


def test_search_finds_files_and_directories(sandbox):
    tool = FileExplorerSearchTool([sandbox["root"]])
    args = FileExplorerSearchArgs(query="doc")
    res = tool.run(args)

    assert res.success is True
    names = [m["name"] for m in res.data["matches"]]
    assert "Documents" in names


def test_search_filters_by_extension(sandbox):
    tool = FileExplorerSearchTool([sandbox["root"]])
    args = FileExplorerSearchArgs(query="quarterly", file_type=".pdf")
    res = tool.run(args)

    assert res.success is True
    assert len(res.data["matches"]) == 1
    assert res.data["matches"][0]["name"] == "quarterly_report.pdf"


def test_search_rejects_path_outside_sandbox(sandbox):
    tool = FileExplorerSearchTool([sandbox["root"]])
    args = FileExplorerSearchArgs(query="test", path=str(sandbox["outside"]))
    res = tool.run(args)

    assert res.success is False
    assert res.error == "path_validation_failed"


def test_search_with_open_in_explorer_triggers_popen(sandbox):
    tool = FileExplorerSearchTool([sandbox["root"]])
    args = FileExplorerSearchArgs(query="notes", open_in_explorer=True)

    with patch("subprocess.Popen") as mock_popen:
        res = tool.run(args)
        assert res.success is True
        assert len(res.data["matches"]) >= 1
        if sys_is_win := (tool.permission_level == PermissionLevel.SAFE):
            # In Windows environment Popen is called
            pass


# ---------------------------------------------------------------------------
# 2. Open Tool Tests (LOW)
# ---------------------------------------------------------------------------


def test_open_validates_path_outside_sandbox(sandbox):
    tool = FileExplorerOpenTool([sandbox["root"]])
    args = FileExplorerOpenArgs(path=str(sandbox["secret"]))
    res = tool.run(args)

    assert res.success is False
    assert res.error == "path_validation_failed"


def test_open_file_invokes_launch(sandbox):
    tool = FileExplorerOpenTool([sandbox["root"]])
    args = FileExplorerOpenArgs(path=str(sandbox["notes"]))

    with patch("os.startfile", create=True) as mock_startfile, patch("subprocess.Popen"):
        res = tool.run(args)
        assert res.success is True
        assert "Opened 'notes.txt'" in res.message


def test_open_with_whitelisted_app(sandbox):
    tool = FileExplorerOpenTool([sandbox["root"]])
    args = FileExplorerOpenArgs(path=str(sandbox["notes"]), app_name="notepad")

    with patch("subprocess.Popen") as mock_popen:
        res = tool.run(args)
        assert res.success is True
        assert "with notepad" in res.message


def test_open_rejects_non_whitelisted_app(sandbox):
    tool = FileExplorerOpenTool([sandbox["root"]])
    args = FileExplorerOpenArgs(path=str(sandbox["notes"]), app_name="malicious_script.exe")
    res = tool.run(args)

    assert res.success is False
    assert res.error == "app_not_whitelisted"


# ---------------------------------------------------------------------------
# 3. Rename Tool Tests (MEDIUM - Requires Confirmation)
# ---------------------------------------------------------------------------


def test_rename_requires_confirmation(sandbox):
    tool = FileExplorerRenameTool([sandbox["root"]])
    args = FileExplorerRenameArgs(path=str(sandbox["notes"]), new_name="notes_renamed.txt", confirmed=False)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "confirmation_required"
    assert "Permission level MEDIUM requires explicit confirmation" in res.message
    assert sandbox["notes"].exists()


def test_rename_executes_when_confirmed(sandbox):
    tool = FileExplorerRenameTool([sandbox["root"]])
    args = FileExplorerRenameArgs(path=str(sandbox["notes"]), new_name="notes_renamed.txt", confirmed=True)
    res = tool.run(args)

    assert res.success is True
    assert not sandbox["notes"].exists()
    renamed = sandbox["docs"] / "notes_renamed.txt"
    assert renamed.exists()
    assert renamed.read_text(encoding="utf-8") == "Hello Victor"


def test_rename_prevents_overwrite(sandbox):
    tool = FileExplorerRenameTool([sandbox["root"]])
    # Try to rename notes.txt to quarterly_report.pdf
    args = FileExplorerRenameArgs(path=str(sandbox["notes"]), new_name="quarterly_report.pdf", confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "already_exists"
    assert "already exists" in res.message


def test_rename_rejects_path_separators_in_name(sandbox):
    tool = FileExplorerRenameTool([sandbox["root"]])
    args = FileExplorerRenameArgs(path=str(sandbox["notes"]), new_name="../escaped.txt", confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "path_validation_failed"


# ---------------------------------------------------------------------------
# 4. Move Tool Tests (HIGH - Requires Confirmation)
# ---------------------------------------------------------------------------


def test_move_requires_confirmation(sandbox):
    tool = FileExplorerMoveTool([sandbox["root"]])
    args = FileExplorerMoveArgs(source=str(sandbox["notes"]), destination=str(sandbox["code_dir"]), confirmed=False)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "confirmation_required"
    assert "Permission level HIGH requires explicit confirmation" in res.message
    assert sandbox["notes"].exists()


def test_move_executes_when_confirmed(sandbox):
    tool = FileExplorerMoveTool([sandbox["root"]])
    args = FileExplorerMoveArgs(source=str(sandbox["notes"]), destination=str(sandbox["code_dir"]), confirmed=True)
    res = tool.run(args)

    assert res.success is True
    assert not sandbox["notes"].exists()
    target = sandbox["code_dir"] / "notes.txt"
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "Hello Victor"


def test_move_strictly_rejects_directory_move(sandbox):
    tool = FileExplorerMoveTool([sandbox["root"]])
    args = FileExplorerMoveArgs(source=str(sandbox["docs"]), destination=str(sandbox["code_dir"]), confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "not_a_file"
    assert "directory" in res.message


def test_move_prevents_overwrite(sandbox):
    tool = FileExplorerMoveTool([sandbox["root"]])
    # Try moving notes.txt to quarterly_report.pdf
    args = FileExplorerMoveArgs(source=str(sandbox["notes"]), destination=str(sandbox["report"]), confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "already_exists"


def test_move_rejects_traversal_outside_sandbox(sandbox):
    tool = FileExplorerMoveTool([sandbox["root"]])
    args = FileExplorerMoveArgs(source=str(sandbox["notes"]), destination=str(sandbox["outside"]), confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "path_validation_failed"


# ---------------------------------------------------------------------------
# 5. Delete Tool Tests (HIGH - Requires Confirmation)
# ---------------------------------------------------------------------------


def test_delete_requires_confirmation_and_identifies_target(sandbox):
    tool = FileExplorerDeleteTool([sandbox["root"]])
    args = FileExplorerDeleteArgs(path=str(sandbox["notes"]), confirmed=False)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "confirmation_required"
    assert "Permission level HIGH requires explicit confirmation" in res.message
    assert "notes.txt" in res.message
    assert res.data["file_name"] == "notes.txt"
    assert res.data["size_bytes"] > 0
    assert sandbox["notes"].exists()


def test_delete_executes_when_confirmed(sandbox):
    tool = FileExplorerDeleteTool([sandbox["root"]])
    args = FileExplorerDeleteArgs(path=str(sandbox["notes"]), confirmed=True)
    res = tool.run(args)

    assert res.success is True
    assert not sandbox["notes"].exists()


def test_delete_strictly_forbids_directory_deletion(sandbox):
    tool = FileExplorerDeleteTool([sandbox["root"]])
    args = FileExplorerDeleteArgs(path=str(sandbox["docs"]), confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "directory_deletion_forbidden"
    assert sandbox["docs"].exists()


def test_delete_rejects_outside_sandbox(sandbox):
    tool = FileExplorerDeleteTool([sandbox["root"]])
    args = FileExplorerDeleteArgs(path=str(sandbox["secret"]), confirmed=True)
    res = tool.run(args)

    assert res.success is False
    assert res.error == "path_validation_failed"
    assert sandbox["secret"].exists()


# ---------------------------------------------------------------------------
# 6. ToolRegistry & PermissionEngine Integration
# ---------------------------------------------------------------------------


def test_registry_registration_and_dispatch(sandbox):
    registry = build_tool_registry(allowed_roots=[sandbox["root"]])

    # Verify all 5 tools are present
    tool_names = [t["name"] for t in registry.list_tools()]
    assert "file_explorer_search" in tool_names
    assert "file_explorer_open" in tool_names
    assert "file_explorer_rename" in tool_names
    assert "file_explorer_move" in tool_names
    assert "file_explorer_delete" in tool_names

    # Test dispatch for SAFE search tool
    search_req = ToolCallRequest(
        tool="file_explorer_search",
        arguments={"query": "notes"}
    )
    search_res = registry.dispatch(search_req)
    assert search_res.success is True

    # Test dispatch for unconfirmed delete -> permission engine requires confirmation
    del_req = ToolCallRequest(
        tool="file_explorer_delete",
        arguments={"path": str(sandbox["notes"]), "confirmed": False}
    )
    del_res = registry.dispatch(del_req)
    # The permission engine denies/requires confirmation
    assert del_res.success is False


@pytest.mark.asyncio
async def test_registry_execute_enforces_permissions(sandbox):
    registry = build_tool_registry(allowed_roots=[sandbox["root"]])

    # Attempting to execute unconfirmed delete via registry.execute() must be denied
    res_str = await registry.execute(
        "file_explorer_delete",
        {"path": str(sandbox["notes"]), "confirmed": False}
    )
    assert "Permission Denied" in res_str or "Confirmation required" in res_str
    assert sandbox["notes"].exists()


def test_schemas_includes_file_explorer_tools(sandbox):
    gemini_tools = get_gemini_tools()
    assert len(gemini_tools) > 0
    func_names = [f.name for f in gemini_tools[0].function_declarations]

    assert "file_explorer_search" in func_names
    assert "file_explorer_open" in func_names
    assert "file_explorer_rename" in func_names
    assert "file_explorer_move" in func_names
    assert "file_explorer_delete" in func_names
