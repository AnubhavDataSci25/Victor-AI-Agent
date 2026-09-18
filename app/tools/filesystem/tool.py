"""
list_directory - read-only directory listing tool.

SAFE permission level (spec section 12), so it can execute
automatically through the permission engine without needing
authentication or confirmation.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.tools.base import Tool
from app.tools.filesystem.path_validation import PathValidationError, validate_path
from app.tools.models import ToolResult
from app.tools.permissions import PermissionLevel


class ListDirectoryArgs(BaseModel):
    path: str

    model_config = {"extra": "forbid"}


class ListDirectoryTool(Tool):
    name = "list_directory"
    description = "List the files and subdirectories of a directory."
    permission_level = PermissionLevel.SAFE
    args_model = ListDirectoryArgs
    timeout_seconds = 5.0

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ListDirectoryArgs)

        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=str(exc),
                error="path_validation_failed",
            )

        if not resolved.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Directory does not exist: {resolved}",
                error="not_found",
            )
        if not resolved.is_dir():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Path is not a directory: {resolved}",
                error="not_a_directory",
            )

        try:
            entries = sorted(
                entry.name + ("/" if entry.is_dir() else "")
                for entry in resolved.iterdir()
            )
        except PermissionError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Permission denied reading {resolved}: {exc}",
                error="os_permission_denied",
            )

        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Found {len(entries)} item(s) in {resolved}",
            data={"path": str(resolved), "entries": entries},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        return result
