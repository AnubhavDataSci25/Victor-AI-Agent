"""
Coding Computer Controller for Victor 2.0.

Coordinates the complete coding lifecycle:
Understand Path -> Inspect Project -> Plan -> Confirm if Needed ->
Modify Files -> Open VS Code -> Run in Controlled Terminal -> Read Result -> Auto-Fix -> Verify.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from app.coding.models import (
    CodingFixPlan,
    CodingPlan,
    CompactProjectContext,
    ExecutionResult,
    FileAction,
    FileActionType,
    WorkspaceContext,
)
from app.coding.provider import CodingModelProvider, GroqCodingModelProvider
from app.coding.runner import (
    CommandConfirmationRequired,
    CommandSecurityError,
    ControlledTerminalRunner,
)
from app.coding.vscode import VSCodeLauncher
from app.coding.workspace import (
    ProjectInspector,
    WorkspaceResolutionError,
    WorkspaceResolver,
    WorkspaceSecurityError,
)
from app.config import CodingConfig, load_config
from app.logging import get_logger
from app.tools.permissions import PermissionDecision, PermissionEngine, PermissionLevel

logger = get_logger("coding.controller")


class CodingComputerController:
    """
    Central coordinator for coding-focused computer control tasks.
    Maintains workspace session context so Victor does not re-discover information.
    """

    def __init__(
        self,
        config: CodingConfig | None = None,
        provider: CodingModelProvider | None = None,
        permission_engine: PermissionEngine | None = None,
        vscode_launcher: VSCodeLauncher | None = None,
    ) -> None:
        self.config = config or load_config().coding
        self.permission_engine = permission_engine or PermissionEngine()
        self.resolver = WorkspaceResolver(self.config.approved_workspace_roots)
        self.vscode = vscode_launcher or VSCodeLauncher(self.config.vscode_path)

        if provider is not None:
            self.provider = provider
        else:
            self.provider = GroqCodingModelProvider(
                api_key=self.config.groq_api_key,
                model=self.config.groq_model,
                api_base=self.config.groq_api_base,
            )

        self.current_context: WorkspaceContext | None = None

    def resolve_and_set_workspace(self, target: str) -> WorkspaceContext:
        """Resolve a workspace path or name, inspect it, and set as active context."""
        workspace_path = self.resolver.resolve_workspace(target)
        metadata = ProjectInspector.detect_project_type(workspace_path)

        self.current_context = WorkspaceContext(
            workspace_path=str(workspace_path),
            project_name=workspace_path.name,
            metadata=metadata,
        )
        logger.info(f"Active coding workspace set to: {workspace_path} ({metadata.language})")
        return self.current_context

    def get_active_workspace(self) -> WorkspaceContext | None:
        return self.current_context

    async def execute_task(
        self,
        task: str,
        workspace_target: str | None = None,
        user_confirmed: bool = False,
        open_in_vscode: bool = True,
    ) -> dict[str, Any]:
        """
        Execute an end-to-end coding task following the closed-loop workflow:
        Understand Path -> Inspect Project -> Plan -> Confirm -> Modify ->
        Open VS Code -> Run -> Read -> Auto-Fix -> Verify.
        """
        # 1. Understand Path / Resolve Workspace
        if workspace_target:
            try:
                self.resolve_and_set_workspace(workspace_target)
            except (WorkspaceResolutionError, WorkspaceSecurityError) as exc:
                return {
                    "status": "error",
                    "stage": "resolve_path",
                    "message": str(exc),
                }

        if not self.current_context:
            return {
                "status": "need_input",
                "stage": "resolve_path",
                "message": (
                    "Please specify the project path or name (e.g. 'Victor AI Agent' or 'E:\\Projects\\MyApp') "
                    "so I can locate the workspace before making changes."
                ),
            }

        workspace_path = Path(self.current_context.workspace_path)
        if not workspace_path.exists():
            return {
                "status": "error",
                "stage": "resolve_path",
                "message": f"Active workspace path no longer exists: {workspace_path}",
            }

        # 2. Inspect Project & Build Compact Context
        compact_ctx = ProjectInspector.build_compact_context(workspace_path, task_query=task)

        # 3. Plan (via Groq coding adapter)
        logger.info(f"Requesting coding plan from model for task: {task[:60]}...")
        try:
            plan: CodingPlan = await self.provider.plan_and_generate_code(task, compact_ctx)
        except Exception as exc:
            logger.error(f"Coding provider error: {exc}")
            return {
                "status": "error",
                "stage": "planning",
                "message": f"Failed to generate coding plan: {exc}",
            }

        # 4. Confirm if Needed (Safety & Permission Engine checks)
        files_to_overwrite: list[str] = []
        for action in plan.actions:
            target_file = (workspace_path / action.path).resolve()
            # Ensure path does not escape workspace
            try:
                target_file.relative_to(workspace_path)
            except ValueError:
                return {
                    "status": "error",
                    "stage": "permission_check",
                    "message": f"Security violation: path {action.path} escapes the project workspace.",
                }

            if action.action_type in (FileActionType.MODIFY_FILE, FileActionType.CREATE_FILE):
                if target_file.exists() and target_file.is_file():
                    files_to_overwrite.append(action.path)

        if files_to_overwrite and not user_confirmed:
            files_list = ", ".join(files_to_overwrite)
            return {
                "status": "confirmation_required",
                "stage": "permission_check",
                "permission_level": PermissionLevel.MEDIUM.value,
                "message": (
                    f"CONFIRMATION REQUIRED: The requested plan will overwrite existing file(s): [{files_list}]. "
                    f"Please confirm if you want me to proceed with these changes (user_confirmed=True)."
                ),
                "plan": plan.model_dump(),
            }

        runner = ControlledTerminalRunner(
            workspace=workspace_path,
            permission_engine=self.permission_engine,
            timeout_seconds=self.config.command_timeout_seconds,
        )

        if plan.run_command:
            level = runner.classify_command(plan.run_command)
            decision = self.permission_engine.decide(level, confirmed=user_confirmed)
            if decision is PermissionDecision.DENIED:
                return {
                    "status": "error",
                    "stage": "permission_check",
                    "message": f"Command '{plan.run_command}' is blocked for safety.",
                }
            if decision is PermissionDecision.REQUIRES_CONFIRMATION:
                return {
                    "status": "confirmation_required",
                    "stage": "permission_check",
                    "permission_level": level.value,
                    "message": (
                        f"CONFIRMATION REQUIRED: Command '{plan.run_command}' requires explicit confirmation. "
                        f"Please confirm to proceed (user_confirmed=True)."
                    ),
                    "plan": plan.model_dump(),
                }

        # 5. Modify (Deterministic direct filesystem write)
        modified_files_info: list[dict[str, Any]] = []
        primary_file_path: Path | None = None

        for action in plan.actions:
            target_path = (workspace_path / action.path).resolve()
            try:
                if action.action_type == FileActionType.CREATE_DIRECTORY:
                    target_path.mkdir(parents=True, exist_ok=True)
                    self.current_context.record_change("create_directory", action.path)
                    modified_files_info.append({"path": action.path, "action": "created_directory"})
                elif action.action_type in (FileActionType.CREATE_FILE, FileActionType.MODIFY_FILE):
                    target_path.parent.mkdir(parents=True, exist_ok=True)
                    target_path.write_text(action.content, encoding="utf-8")
                    if not target_path.exists():
                        raise OSError(f"Failed to verify creation of {target_path}")
                    self.current_context.record_change(action.action_type.value, action.path)
                    modified_files_info.append({"path": action.path, "action": action.action_type.value, "bytes": len(action.content.encode("utf-8"))})
                    if primary_file_path is None:
                        primary_file_path = target_path
                elif action.action_type == FileActionType.DELETE_FILE:
                    if target_path.exists():
                        target_path.unlink()
                        self.current_context.record_change("delete_file", action.path)
                        modified_files_info.append({"path": action.path, "action": "deleted"})
            except Exception as exc:
                return {
                    "status": "error",
                    "stage": "filesystem_modify",
                    "message": f"Error modifying {action.path}: {exc}",
                }

        # 6. Open in VS Code (Visible computer automation)
        vscode_opened = False
        vscode_msg = ""
        if open_in_vscode and self.vscode.is_available():
            vscode_opened, vscode_msg = self.vscode.open_workspace(workspace_path)
            if primary_file_path and primary_file_path.exists():
                self.vscode.open_file(primary_file_path)

        # 7. Run (Controlled Terminal Execution)
        exec_result: ExecutionResult | None = None
        fix_history: list[dict[str, Any]] = []

        if plan.run_command:
            try:
                exec_result = await runner.run_command(plan.run_command, user_confirmed=user_confirmed)
                self.current_context.record_execution(exec_result)
            except (CommandSecurityError, CommandConfirmationRequired) as exc:
                return {
                    "status": "confirmation_required" if isinstance(exc, CommandConfirmationRequired) else "error",
                    "stage": "terminal_run",
                    "message": str(exc),
                    "modified_files": modified_files_info,
                }

            # 8. Error Analysis & Auto-Fix Loop
            iterations = 0
            while not exec_result.success and iterations < self.config.max_fix_iterations:
                iterations += 1
                logger.info(f"Command failed (exit code {exec_result.exit_code}). Running fix loop iteration {iterations}/{self.config.max_fix_iterations}...")

                try:
                    fix_plan: CodingFixPlan = await self.provider.analyze_and_fix(
                        task=task,
                        context=compact_ctx,
                        failed_command=exec_result.command,
                        stdout=exec_result.stdout,
                        stderr=exec_result.stderr,
                        exit_code=exec_result.exit_code,
                        files_modified=plan.actions,
                    )

                    # Apply fixes
                    for fix_action in fix_plan.actions:
                        target_fix = (workspace_path / fix_action.path).resolve()
                        target_fix.parent.mkdir(parents=True, exist_ok=True)
                        target_fix.write_text(fix_action.content, encoding="utf-8")
                        self.current_context.record_change("fix_modified_file", fix_action.path)

                    # Re-run verification
                    cmd_to_rerun = fix_plan.run_command or plan.run_command
                    exec_result = await runner.run_command(cmd_to_rerun, user_confirmed=user_confirmed)
                    self.current_context.record_execution(exec_result)

                    fix_history.append({
                        "iteration": iterations,
                        "analysis": fix_plan.error_analysis,
                        "fix_summary": fix_plan.fix_summary,
                        "rerun_command": cmd_to_rerun,
                        "rerun_success": exec_result.success,
                    })

                    if exec_result.success:
                        logger.info("Auto-fix successfully resolved the error!")
                        break

                except Exception as fix_exc:
                    logger.warning(f"Auto-fix iteration {iterations} failed: {fix_exc}")
                    break

        # 9. Verify & Assemble Final Output
        is_success = exec_result.success if exec_result else True

        return {
            "status": "success" if is_success else "completed_with_errors",
            "workspace": str(workspace_path),
            "task_summary": plan.task_summary,
            "modified_files": modified_files_info,
            "vscode_status": vscode_msg if vscode_opened else "VS Code not launched or not found",
            "command_executed": exec_result.command if exec_result else None,
            "exit_code": exec_result.exit_code if exec_result else None,
            "stdout": exec_result.stdout if exec_result else None,
            "stderr": exec_result.stderr if exec_result else None,
            "fix_iterations": len(fix_history),
            "fix_history": fix_history,
            "notes": plan.notes,
        }

    def delete_workspace_file(
        self,
        file_path: str,
        user_confirmed: bool = False,
    ) -> dict[str, Any]:
        """
        Deletes a specific file within the active approved workspace.
        Enforces:
        - Must have an active workspace.
        - Path must resolve strictly inside the active workspace.
        - Refuses directories (file deletion only).
        - Refuses non-existent files.
        - Evaluates PermissionLevel.HIGH: requires user_confirmed=True.
        - Verifies the file no longer exists.
        - Records the change in WorkspaceContext.
        """
        if not self.current_context:
            return {
                "status": "need_input",
                "message": "No active workspace is set. Please resolve a workspace before deleting files.",
            }

        workspace_path = Path(self.current_context.workspace_path).resolve()
        if not workspace_path.exists() or not workspace_path.is_dir():
            return {
                "status": "error",
                "message": f"Active workspace directory does not exist: {workspace_path}",
            }

        if not file_path or not file_path.strip():
            return {
                "status": "error",
                "message": "File path cannot be empty.",
            }

        target_file = (workspace_path / file_path.strip()).resolve()

        # Enforce sandbox boundary: target must be inside workspace
        try:
            rel_path = target_file.relative_to(workspace_path)
        except ValueError:
            return {
                "status": "security_error",
                "message": f"Security violation: path '{file_path}' resolves outside the approved workspace.",
            }

        if not target_file.exists():
            return {
                "status": "error",
                "message": f"File does not exist: {rel_path}",
            }

        if target_file.is_dir():
            return {
                "status": "error",
                "message": f"Target '{rel_path}' is a directory. Folder deletion is not permitted in this update.",
            }

        # PermissionEngine check for HIGH level
        decision = self.permission_engine.decide(PermissionLevel.HIGH, confirmed=user_confirmed)
        if decision is not PermissionDecision.ALLOWED:
            return {
                "status": "confirmation_required",
                "permission_level": PermissionLevel.HIGH.value,
                "message": (
                    f"CONFIRMATION REQUIRED (Permission Level: HIGH): Are you sure you want to permanently delete "
                    f"'{rel_path}' from workspace '{workspace_path.name}'? "
                    f"Please confirm to proceed (user_confirmed=True)."
                ),
                "file_path": str(rel_path),
            }

        try:
            target_file.unlink()
            if target_file.exists():
                return {
                    "status": "error",
                    "message": f"Deletion could not be verified: file still exists at {rel_path}",
                }
            self.current_context.record_change("delete_file", str(rel_path), "User-confirmed deletion")
            logger.info(f"Deleted file {rel_path} in workspace {workspace_path}")
            return {
                "status": "success",
                "message": f"Successfully deleted '{rel_path}' from workspace '{workspace_path.name}'.",
                "file_path": str(rel_path),
            }
        except OSError as exc:
            return {
                "status": "error",
                "message": f"Failed to delete file '{rel_path}': {exc}",
            }

    def close_workspace_vscode(
        self,
        user_confirmed: bool = False,
    ) -> dict[str, Any]:
        """
        Closes the VS Code window associated with the active workspace.
        Enforces:
        - Must have an active workspace.
        - Evaluates PermissionLevel.MEDIUM: requires user_confirmed=True.
        - Targets only the specific VS Code window for this workspace.
        """
        if not self.current_context:
            return {
                "status": "need_input",
                "message": "No active workspace is set. Please resolve a workspace first.",
            }

        workspace_path = Path(self.current_context.workspace_path)

        decision = self.permission_engine.decide(PermissionLevel.MEDIUM, confirmed=user_confirmed)
        if decision is not PermissionDecision.ALLOWED:
            return {
                "status": "confirmation_required",
                "permission_level": PermissionLevel.MEDIUM.value,
                "message": (
                    f"CONFIRMATION REQUIRED (Permission Level: MEDIUM): Are you sure you want to close "
                    f"the VS Code window for workspace '{workspace_path.name}'? "
                    f"Please confirm to proceed (user_confirmed=True)."
                ),
            }

        success, msg = self.vscode.close_workspace_window(workspace_path)
        return {
            "status": "success" if success else "not_found",
            "message": msg,
        }

