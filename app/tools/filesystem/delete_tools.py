"""
Destructive filesystem tools (spec section 21). Both HIGH per spec
section 12's explicit table ("Delete file -> HIGH", "Delete directory
-> HIGH"). Denied by default until Phase 12's confirmation flow
exists - this is intentional, not a gap.

delete_directory additionally requires an explicit `recursive=True`
even once HIGH-permission confirmation exists in a later phase - a
non-empty directory is refused outright otherwise. This is deliberate
defense in depth: even a confirmed HIGH action shouldn't be able to
silently wipe an entire tree because a request was ambiguous about
scope.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel

from app.tools.base import Tool
from app.tools.filesystem.path_validation import PathValidationError, validate_path
from app.tools.models import ToolResult
from app.tools.permissions import PermissionLevel


class DeleteFileArgs(BaseModel):
    path: str

    model_config = {"extra": "forbid"}


class DeleteFileTool(Tool):
    name = "delete_file"
    description = "Permanently delete a file."
    permission_level = PermissionLevel.HIGH
    args_model = DeleteFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, DeleteFileArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if not resolved.exists():
            return ToolResult(
                success=False, tool=self.name, message=f"{resolved} does not exist.",
                error="not_found",
            )
        if not resolved.is_file():
            return ToolResult(
                success=False, tool=self.name, message=f"{resolved} is not a file.",
                error="not_a_file",
            )

        try:
            resolved.unlink()
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to delete {resolved}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Deleted {resolved}.",
            data={"path": str(resolved)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if Path(result.data["path"]).exists():
            return ToolResult(
                success=False, tool=self.name,
                message="Delete could not be verified - the file still exists, Sir.",
                error="verification_failed",
            )
        return result


class DeleteDirectoryArgs(BaseModel):
    path: str
    recursive: bool = False

    model_config = {"extra": "forbid"}


class DeleteDirectoryTool(Tool):
    name = "delete_directory"
    description = (
        "Permanently delete a directory. Non-empty directories require "
        "recursive=True."
    )
    permission_level = PermissionLevel.HIGH
    args_model = DeleteDirectoryArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, DeleteDirectoryArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if not resolved.exists():
            return ToolResult(
                success=False, tool=self.name, message=f"{resolved} does not exist.",
                error="not_found",
            )
        if not resolved.is_dir():
            return ToolResult(
                success=False, tool=self.name, message=f"{resolved} is not a directory.",
                error="not_a_directory",
            )

        is_empty = not any(resolved.iterdir())
        if not is_empty and not args.recursive:
            return ToolResult(
                success=False, tool=self.name,
                message=(
                    f"{resolved} is not empty, Sir. Pass recursive=True to "
                    "delete it and everything inside."
                ),
                error="not_empty",
            )

        try:
            if is_empty:
                resolved.rmdir()
            else:
                shutil.rmtree(resolved)
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to delete {resolved}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Deleted directory {resolved}.",
            data={"path": str(resolved)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if Path(result.data["path"]).exists():
            return ToolResult(
                success=False, tool=self.name,
                message="Delete could not be verified - the directory still exists, Sir.",
                error="verification_failed",
            )
        return result