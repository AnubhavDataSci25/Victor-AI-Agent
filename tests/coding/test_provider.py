"""
Tests for CodingModelProvider and Groq adapter.
"""

from unittest.mock import AsyncMock, patch
import pytest

from app.coding.models import (
    CompactProjectContext,
    FileAction,
    FileActionType,
    ProjectMetadata,
    ProjectType,
)
from app.coding.provider import GroqCodingModelProvider, _clean_json_text


def test_clean_json_text_strip_markdown():
    wrapped = "```json\n{\"status\": \"ok\"}\n```"
    assert _clean_json_text(wrapped) == '{"status": "ok"}'

    raw = '{"status": "ok"}'
    assert _clean_json_text(raw) == '{"status": "ok"}'


@pytest.mark.asyncio
async def test_mocked_plan_generation():
    provider = GroqCodingModelProvider(api_key="mock_key")
    ctx = CompactProjectContext(
        root_path="E:/Test",
        project_name="TestApp",
        metadata=ProjectMetadata(project_type=ProjectType.PYTHON, language="python"),
        skeleton_tree="test.py",
    )

    mock_resp = {
        "task_summary": "Create hello.py",
        "actions": [
            {
                "path": "hello.py",
                "action_type": "create_file",
                "content": "print('hello')",
                "reason": "Requested hello script",
            }
        ],
        "run_command": "python hello.py",
        "expected_outcome": "Prints hello",
        "notes": "",
    }

    with patch.object(provider, "_send_request", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp
        plan = await provider.plan_and_generate_code("Create hello.py", ctx)

        assert plan.task_summary == "Create hello.py"
        assert len(plan.actions) == 1
        assert plan.actions[0].path == "hello.py"
        assert plan.actions[0].action_type == FileActionType.CREATE_FILE
        assert plan.run_command == "python hello.py"


@pytest.mark.asyncio
async def test_mocked_analyze_and_fix():
    provider = GroqCodingModelProvider(api_key="mock_key")
    ctx = CompactProjectContext(
        root_path="E:/Test",
        project_name="TestApp",
        metadata=ProjectMetadata(project_type=ProjectType.PYTHON, language="python"),
        skeleton_tree="test.py",
    )

    mock_resp = {
        "error_analysis": "Syntax error in hello.py",
        "fix_summary": "Fix missing quote",
        "actions": [
            {
                "path": "hello.py",
                "action_type": "modify_file",
                "content": "print('fixed hello')",
                "reason": "Fix syntax error",
            }
        ],
        "run_command": "python hello.py",
    }

    with patch.object(provider, "_send_request", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = mock_resp
        fix = await provider.analyze_and_fix(
            task="Create hello.py",
            context=ctx,
            failed_command="python hello.py",
            stdout="",
            stderr="SyntaxError: unterminated string literal",
            exit_code=1,
            files_modified=[FileAction(path="hello.py", action_type=FileActionType.CREATE_FILE, content="print('hello")],
        )

        assert fix.error_analysis == "Syntax error in hello.py"
        assert len(fix.actions) == 1
        assert fix.actions[0].action_type == FileActionType.MODIFY_FILE
