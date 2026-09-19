"""
Tests for CodingComputerController end-to-end execution loop and safety checks.
"""

from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from app.coding.controller import CodingComputerController
from app.coding.models import (
    CodingFixPlan,
    CodingPlan,
    FileAction,
    FileActionType,
)
from app.coding.provider import CodingModelProvider
from app.coding.vscode import VSCodeLauncher
from app.config import CodingConfig


class FakeCodingProvider(CodingModelProvider):
    """Deterministic fake provider for test predictability."""

    def __init__(self, plan: CodingPlan, fix_plan: CodingFixPlan | None = None) -> None:
        self.plan = plan
        self.fix_plan = fix_plan

    async def plan_and_generate_code(self, task, context, relevant_files=None) -> CodingPlan:
        return self.plan

    async def analyze_and_fix(self, task, context, failed_command, stdout, stderr, exit_code, files_modified) -> CodingFixPlan:
        if self.fix_plan:
            return self.fix_plan
        raise RuntimeError("No fix plan configured")


@pytest.mark.asyncio
async def test_controller_executes_task_successfully(tmp_path: Path):
    plan = CodingPlan(
        task_summary="Create hello.py",
        actions=[
            FileAction(
                path="hello.py",
                action_type=FileActionType.CREATE_FILE,
                content="print('Hello from Victor Test')",
                reason="Requested hello script",
            )
        ],
        run_command="python hello.py",
        expected_outcome="Prints greeting",
    )

    provider = FakeCodingProvider(plan)
    config = CodingConfig(approved_workspace_roots=[str(tmp_path)])
    # Mock VSCodeLauncher so it doesn't try to open actual GUI during automated test
    vscode = VSCodeLauncher()
    vscode.is_available = lambda: False

    controller = CodingComputerController(
        config=config,
        provider=provider,
        vscode_launcher=vscode,
    )

    result = await controller.execute_task(
        task="Create hello.py and run it",
        workspace_target=str(tmp_path),
        user_confirmed=True,
        open_in_vscode=False,
    )

    assert result["status"] == "success"
    assert (tmp_path / "hello.py").exists()
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('Hello from Victor Test')"
    assert "Hello from Victor Test" in (result.get("stdout") or "")


@pytest.mark.asyncio
async def test_controller_requires_confirmation_on_overwrite(tmp_path: Path):
    existing_file = tmp_path / "app.py"
    existing_file.write_text("print('existing')", encoding="utf-8")

    plan = CodingPlan(
        task_summary="Overwrite app.py",
        actions=[
            FileAction(
                path="app.py",
                action_type=FileActionType.CREATE_FILE,
                content="print('new content')",
                reason="Overwriting existing file",
            )
        ],
        run_command="python app.py",
    )

    provider = FakeCodingProvider(plan)
    config = CodingConfig(approved_workspace_roots=[str(tmp_path)])
    controller = CodingComputerController(config=config, provider=provider)

    # user_confirmed=False -> should return confirmation_required
    result = await controller.execute_task(
        task="Update app.py",
        workspace_target=str(tmp_path),
        user_confirmed=False,
        open_in_vscode=False,
    )

    assert result["status"] == "confirmation_required"
    assert "overwrite existing file" in result["message"].lower()
    # Ensure original content is preserved!
    assert existing_file.read_text(encoding="utf-8") == "print('existing')"


@pytest.mark.asyncio
async def test_controller_auto_fix_loop(tmp_path: Path):
    # Initial code has syntax error
    initial_plan = CodingPlan(
        task_summary="Create script with error",
        actions=[
            FileAction(
                path="calc.py",
                action_type=FileActionType.CREATE_FILE,
                content="prnt('broken syntax')",
                reason="Initial script",
            )
        ],
        run_command="python calc.py",
    )

    fix_plan = CodingFixPlan(
        error_analysis="NameError: name 'prnt' is not defined",
        fix_summary="Change prnt to print",
        actions=[
            FileAction(
                path="calc.py",
                action_type=FileActionType.MODIFY_FILE,
                content="print('fixed calculation')",
                reason="Correct function name",
            )
        ],
        run_command="python calc.py",
    )

    provider = FakeCodingProvider(initial_plan, fix_plan)
    config = CodingConfig(approved_workspace_roots=[str(tmp_path)], max_fix_iterations=1)
    controller = CodingComputerController(config=config, provider=provider)

    result = await controller.execute_task(
        task="Create calc.py and run it",
        workspace_target=str(tmp_path),
        user_confirmed=True,
        open_in_vscode=False,
    )

    assert result["status"] == "success"
    assert result["fix_iterations"] == 1
    assert (tmp_path / "calc.py").read_text(encoding="utf-8") == "print('fixed calculation')"
    assert "fixed calculation" in (result.get("stdout") or "")
