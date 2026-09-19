"""
Controlled Terminal Runner for Victor 2.0.

Executes project commands inside the validated workspace directory with
timeout enforcement, output capture bounds, and PermissionEngine safety checks.
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import time
from pathlib import Path

from app.coding.models import ExecutionResult
from app.logging import get_logger
from app.tools.permissions import PermissionDecision, PermissionEngine, PermissionLevel

logger = get_logger("coding.runner")

# Strictly forbidden dangerous commands or syntax
DANGEROUS_PATTERNS = [
    r"\brm\s+-rf\s+[/~]",
    r"\bdel\b.*[a-z]:\\",
    r"\brmdir\b.*[a-z]:\\",
    r"\bformat\s+[a-z]:",
    r"\bmkfs\b",
    r"\bdd\s+if=",
    r"\bsudo\b",
    r"\|\s*(?:bash|sh|powershell|iex)\b",
    r"-encodedcommand\b",
    r"-enc\b",
    r"\bshutdown\b",
    r"\breboot\b",
]

# Commands that install external packages (requires confirmation)
PACKAGE_INSTALL_PATTERNS = [
    r"\bpip\s+install\b",
    r"\bpip3\s+install\b",
    r"\bnpm\s+install\b",
    r"\bnpm\s+i\b",
    r"\byarn\s+add\b",
    r"\bpnpm\s+add\b",
    r"\bcargo\s+add\b",
    r"\bdotnet\s+add\s+package\b",
    r"\bgo\s+get\b",
]


class CommandSecurityError(Exception):
    """Raised when an unsafe or blocked command is attempted."""


class CommandConfirmationRequired(Exception):
    """Raised when an action requires explicit user confirmation."""


class ControlledTerminalRunner:
    """Executes validated commands in the workspace under deterministic safety boundaries."""

    def __init__(
        self,
        workspace: Path,
        permission_engine: PermissionEngine | None = None,
        timeout_seconds: float = 30.0,
        max_output_bytes: int = 50_000,
    ) -> None:
        self.workspace = workspace
        self.permission_engine = permission_engine or PermissionEngine()
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    def classify_command(self, command: str) -> PermissionLevel:
        """Classify command risk level for PermissionEngine."""
        cmd_lower = command.lower().strip()

        # Check for dangerous blocked patterns
        for pattern in DANGEROUS_PATTERNS:
            if re.search(pattern, cmd_lower):
                return PermissionLevel.BLOCKED

        # Check for package installation patterns
        for pattern in PACKAGE_INSTALL_PATTERNS:
            if re.search(pattern, cmd_lower):
                return PermissionLevel.MEDIUM

        # Read-only / test / execution commands (python hello.py, pytest, npm test, etc.)
        return PermissionLevel.LOW

    async def run_command(
        self,
        command: str,
        user_confirmed: bool = False,
        timeout_override: float | None = None,
    ) -> ExecutionResult:
        """
        Execute command with timeout and safety validation inside the workspace cwd.
        """
        if not command or not command.strip():
            return ExecutionResult(
                command="",
                exit_code=1,
                stdout="",
                stderr="Command cannot be empty.",
                duration_seconds=0.0,
                success=False,
                error_type="empty_command",
            )

        command = command.strip()
        level = self.classify_command(command)
        decision = self.permission_engine.decide(level, confirmed=user_confirmed)

        if decision is PermissionDecision.DENIED and level is PermissionLevel.BLOCKED:
            raise CommandSecurityError(
                f"Command '{command}' is classified as BLOCKED and cannot be executed."
            )

        if decision is PermissionDecision.REQUIRES_CONFIRMATION:
            reason = (
                f"CONFIRMATION REQUIRED: Command '{command}' involves package installation or "
                f"system modification. Please confirm before proceeding (user_confirmed=True)."
            )
            raise CommandConfirmationRequired(reason)

        timeout = timeout_override or self.timeout_seconds
        start_time = time.monotonic()

        logger.info(f"Executing controlled command in {self.workspace}: {command}")

        # Choose appropriate shell for Windows
        shell_cmd = command
        # If running python on Windows, prefer current venv if it exists and bare 'python' was called
        venv_python = Path(os.getcwd()) / ".venv" / "Scripts" / "python.exe"
        if venv_python.exists() and (command.startswith("python ") or command == "python"):
            shell_cmd = f'"{venv_python}" ' + command[7:]

        try:
            process = await asyncio.create_subprocess_shell(
                shell_cmd,
                cwd=str(self.workspace),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                # Terminate timed out process
                try:
                    process.kill()
                    await process.wait()
                except Exception:
                    pass
                duration = time.monotonic() - start_time
                return ExecutionResult(
                    command=command,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Command timed out after {timeout} seconds.",
                    duration_seconds=duration,
                    success=False,
                    error_type="timeout",
                )

            duration = time.monotonic() - start_time

            # Bound output size
            if len(stdout_bytes) > self.max_output_bytes:
                stdout_str = stdout_bytes[: self.max_output_bytes].decode("utf-8", errors="replace") + "\n... (output truncated)"
            else:
                stdout_str = stdout_bytes.decode("utf-8", errors="replace")

            if len(stderr_bytes) > self.max_output_bytes:
                stderr_str = stderr_bytes[: self.max_output_bytes].decode("utf-8", errors="replace") + "\n... (stderr truncated)"
            else:
                stderr_str = stderr_bytes.decode("utf-8", errors="replace")

            exit_code = process.returncode or 0
            success = exit_code == 0

            return ExecutionResult(
                command=command,
                exit_code=exit_code,
                stdout=stdout_str,
                stderr=stderr_str,
                duration_seconds=duration,
                success=success,
                error_type=None if success else "nonzero_exit_code",
            )

        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(f"Error executing command '{command}': {exc}")
            return ExecutionResult(
                command=command,
                exit_code=-1,
                stdout="",
                stderr=str(exc),
                duration_seconds=duration,
                success=False,
                error_type="execution_exception",
            )
