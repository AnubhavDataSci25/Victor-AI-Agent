"""
Victor 2.0 BaseTool implementations for Coding Computer Control.

Exposes workspace resolution, structured multi-step coding task execution,
controlled project terminal commands, and workspace status reporting.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.coding.controller import CodingComputerController
from app.coding.runner import ControlledTerminalRunner
from app.logging import get_logger
from app.tools.base import BaseTool

logger = get_logger("tools.coding")

# Module-level singleton controller shared across tool calls in a session
_coding_controller: CodingComputerController | None = None


def get_coding_controller() -> CodingComputerController:
    global _coding_controller
    if _coding_controller is None:
        _coding_controller = CodingComputerController()
    return _coding_controller


class CodingResolveWorkspaceTool(BaseTool):
    name = "coding_resolve_workspace"
    description = (
        "Resolves and validates a target project or workspace path on the Windows filesystem "
        "(e.g. 'E:\\Projects\\MyApp' or project name 'CareerLens'). Inspects the directory structure, "
        "detects the project type (Python, FastAPI, Node, React, etc.), and sets it as the active workspace."
    )
    parameters = {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "The exact project directory path or bare project name to locate.",
            }
        },
        "required": ["target"],
    }

    async def execute(self, args: dict) -> str:
        target = args.get("target", "").strip()
        if not target:
            return "Error: Target project path or name is required."

        controller = get_coding_controller()
        try:
            ctx = controller.resolve_and_set_workspace(target)
            tree_sample = "\n".join(ctx.metadata.config_files) if ctx.metadata.config_files else "None"
            return (
                f"Successfully resolved workspace: {ctx.workspace_path}\n"
                f"Project Type: {ctx.metadata.project_type.value} (Language: {ctx.metadata.language}, "
                f"Framework: {ctx.metadata.framework or 'None'})\n"
                f"Package Manager: {ctx.metadata.package_manager or 'default'}\n"
                f"Config Files: {tree_sample}\n"
                f"Active workspace is ready for coding tasks."
            )
        except Exception as exc:
            return f"Workspace resolution failed: {exc}"


class CodingExecuteTaskTool(BaseTool):
    name = "coding_execute_task"
    description = (
        "Performs a complete coding workflow on the user's computer: resolves/validates the project, "
        "uses Groq (openai/gpt-oss-20b) to generate code and plan changes, creates/modifies files on disk, "
        "opens the workspace and file in VS Code, runs the verification command in a controlled terminal, "
        "and automatically corrects errors if the command fails. "
        "SAFETY NOTE: If overwriting existing files, confirmation is required (user_confirmed=true)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "Clear description of the coding task (e.g. 'Create hello.py and run it', 'Add a career prediction endpoint in routers/prediction.py').",
            },
            "workspace": {
                "type": "string",
                "description": "Optional project path or name. If omitted, uses the currently active workspace.",
            },
            "user_confirmed": {
                "type": "boolean",
                "default": False,
                "description": "Set to true only if the user explicitly confirmed overwriting existing files or package installation.",
            },
        },
        "required": ["task"],
    }

    async def execute(self, args: dict) -> str:
        task = args.get("task", "").strip()
        workspace = args.get("workspace")
        user_confirmed = bool(args.get("user_confirmed", False))

        if not task:
            return "Error: Coding task description cannot be empty."

        controller = get_coding_controller()
        result = await controller.execute_task(
            task=task,
            workspace_target=workspace,
            user_confirmed=user_confirmed,
            open_in_vscode=True,
        )

        status = result.get("status")

        if status == "confirmation_required":
            return (
                f"{result.get('message')}\n"
                f"Plan Summary: {result.get('plan', {}).get('task_summary', '')}"
            )

        if status == "error":
            return f"Coding task failed at stage '{result.get('stage')}': {result.get('message')}"

        if status == "need_input":
            return result.get("message", "Please specify the workspace path.")

        # Format successful / completed response
        lines = [
            f"Workspace: {result.get('workspace')}",
            f"Task: {result.get('task_summary')}",
            f"VS Code: {result.get('vscode_status')}",
        ]

        modified = result.get("modified_files", [])
        if modified:
            lines.append("Files Modified / Created:")
            for m in modified:
                lines.append(f"  - {m.get('path')} ({m.get('action')})")

        cmd = result.get("command_executed")
        if cmd:
            lines.append(f"Command Executed: {cmd} (Exit Code: {result.get('exit_code')})")
            stdout = result.get("stdout")
            stderr = result.get("stderr")
            if stdout and stdout.strip():
                lines.append(f"Output:\n{stdout.strip()}")
            if stderr and stderr.strip():
                lines.append(f"Stderr:\n{stderr.strip()}")

        fix_count = result.get("fix_iterations", 0)
        if fix_count > 0:
            lines.append(f"Auto-Fix Iterations: {fix_count} error correction cycle(s) succeeded.")

        return "\n".join(lines)


class CodingRunCommandTool(BaseTool):
    name = "coding_run_command"
    description = (
        "Runs a project verification or test command (e.g. 'python hello.py', 'pytest', 'npm test') "
        "inside the active workspace directory in a controlled terminal. Captures stdout and stderr."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The command line string to execute in the workspace root.",
            },
            "user_confirmed": {
                "type": "boolean",
                "default": False,
                "description": "Must be true if executing commands that install packages or make substantial system changes.",
            },
        },
        "required": ["command"],
    }

    async def execute(self, args: dict) -> str:
        command = args.get("command", "").strip()
        user_confirmed = bool(args.get("user_confirmed", False))

        if not command:
            return "Error: Command cannot be empty."

        controller = get_coding_controller()
        ctx = controller.get_active_workspace()
        if not ctx:
            return "Error: No active workspace is set. Use coding_resolve_workspace first."

        runner = ControlledTerminalRunner(
            workspace=Path(ctx.workspace_path),
            permission_engine=controller.permission_engine,
            timeout_seconds=controller.config.command_timeout_seconds,
        )

        try:
            result = await runner.run_command(command, user_confirmed=user_confirmed)
            output_parts = [
                f"Command: {result.command}",
                f"Exit Code: {result.exit_code} ({'Success' if result.success else 'Failed'})",
                f"Duration: {result.duration_seconds:.2f}s",
            ]
            if result.stdout.strip():
                output_parts.append(f"STDOUT:\n{result.stdout.strip()}")
            if result.stderr.strip():
                output_parts.append(f"STDERR:\n{result.stderr.strip()}")

            ctx.record_execution(result)
            return "\n".join(output_parts)
        except Exception as exc:
            return f"Command execution error: {exc}"


class CodingGetWorkspaceStatusTool(BaseTool):
    name = "coding_get_workspace_status"
    description = (
        "Returns the currently active workspace, detected framework/language, "
        "recent file modifications, and recent command execution results."
    )
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        controller = get_coding_controller()
        ctx = controller.get_active_workspace()
        if not ctx:
            return "No workspace is currently active. Please specify a project path or name."

        recent_changes_str = (
            "\n".join(f"  - [{c.get('action')}] {c.get('path')}" for c in ctx.recent_changes[-5:])
            if ctx.recent_changes
            else "  None"
        )

        last_cmd_str = (
            f"{ctx.last_result.command} (Exit Code {ctx.last_result.exit_code})"
            if ctx.last_result
            else "None"
        )

        return (
            f"Active Workspace: {ctx.workspace_path}\n"
            f"Project Name: {ctx.project_name}\n"
            f"Type: {ctx.metadata.project_type.value} ({ctx.metadata.language})\n"
            f"Framework: {ctx.metadata.framework or 'None'}\n"
            f"Recent File Changes:\n{recent_changes_str}\n"
            f"Last Command: {last_cmd_str}"
        )


class CodingDeleteFileTool(BaseTool):
    name = "coding_delete_file"
    description = (
        "Permanently deletes a specific file located within the currently approved project/workspace. "
        "SAFETY REQUIREMENT: Deleting files is a HIGH-consequence operation and requires explicit user "
        "confirmation (user_confirmed=true) before deletion. Folder deletion is not permitted."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "Relative or absolute file path to delete within the active workspace.",
            },
            "user_confirmed": {
                "type": "boolean",
                "default": False,
                "description": "Must be set to true only after the user explicitly confirmed file deletion.",
            },
        },
        "required": ["path"],
    }

    async def execute(self, args: dict) -> str:
        path = args.get("path", "").strip()
        user_confirmed = bool(args.get("user_confirmed", False))

        if not path:
            return "Error: File path is required for deletion."

        controller = get_coding_controller()
        result = controller.delete_workspace_file(path, user_confirmed=user_confirmed)

        status = result.get("status")
        if status == "confirmation_required":
            return result.get("message", "Confirmation required to delete file.")
        elif status == "success":
            return result.get("message", "File successfully deleted.")
        elif status == "need_input":
            return result.get("message", "Please set an active workspace first.")
        elif status == "security_error":
            return f"Security Violation: {result.get('message')}"
        else:
            return f"Delete failed: {result.get('message')}"


class DeleteFileTool(CodingDeleteFileTool):
    name = "delete_file"


class CodingCloseVSCodeTool(BaseTool):
    name = "coding_close_vscode"
    description = (
        "Gracefully closes the specific VS Code window associated with the current workspace using "
        "Windows window messaging (WM_CLOSE), without closing unrelated VS Code windows or applications. "
        "SAFETY REQUIREMENT: Requires user confirmation (user_confirmed=true) before closing the editor."
    )
    parameters = {
        "type": "object",
        "properties": {
            "user_confirmed": {
                "type": "boolean",
                "default": False,
                "description": "Must be set to true only after the user explicitly confirmed closing the VS Code window.",
            },
        },
    }

    async def execute(self, args: dict) -> str:
        user_confirmed = bool(args.get("user_confirmed", False))

        controller = get_coding_controller()
        result = controller.close_workspace_vscode(user_confirmed=user_confirmed)

        status = result.get("status")
        if status == "confirmation_required":
            return result.get("message", "Confirmation required to close VS Code.")
        elif status == "success":
            return result.get("message", "VS Code window successfully closed.")
        elif status == "need_input":
            return result.get("message", "Please set an active workspace first.")
        else:
            return result.get("message", "Could not close VS Code window.")


class CloseVSCodeTool(CodingCloseVSCodeTool):
    name = "close_vscode"

