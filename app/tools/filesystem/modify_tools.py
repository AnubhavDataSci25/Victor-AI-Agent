"""
Filesystem tools that relocate or duplicate files (spec section 21).

- copy_file: LOW. Non-destructive by construction - fails outright if
  the destination already exists rather than silently overwriting it,
  so it can only ever add a duplicate, never destroy anything.
- rename_file / move_file: MEDIUM. Both remove the original location
  and can collide with an existing destination, so both fail closed
  (refuse) rather than overwrite. Denied by default until Phase 12's
  confirmation flow exists.

rename_file only accepts a bare filename for the new name (validated
by validate_new_file_name) - not a path - so "rename" can't be used to
smuggle a move to an arbitrary directory. Use move_file for that.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from pydantic import BaseModel

from app.tools.base import Tool
from app.tools.filesystem.path_validation import (
    PathValidationError,
    validate_new_file_name,
    validate_path,
)
from app.tools.models import ToolResult
from app.tools.permissions import PermissionLevel


def _validate_two_paths(
    source_raw: str, destination_raw: str, allowed_roots: list[Path]
) -> tuple[Path, Path] | ToolResult:
    """Shared validation for tools that take a source and destination
    path. Returns (source, destination) on success or a failed
    ToolResult ready to return directly on failure."""
    try:
        source = validate_path(source_raw, allowed_roots)
    except PathValidationError as exc:
        return ToolResult(
            success=False, tool="", message=str(exc), error="path_validation_failed"
        )
    try:
        destination = validate_path(destination_raw, allowed_roots)
    except PathValidationError as exc:
        return ToolResult(
            success=False, tool="", message=str(exc), error="path_validation_failed"
        )
    return source, destination


# --- rename_file (MEDIUM) --------------------------------------------------


class RenameFileArgs(BaseModel):
    path: str
    new_name: str

    model_config = {"extra": "forbid"}


class RenameFileTool(Tool):
    name = "rename_file"
    description = "Rename a file within its current directory."
    permission_level = PermissionLevel.MEDIUM
    args_model = RenameFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, RenameFileArgs)
        try:
            source = validate_path(args.path, self._allowed_roots)
            new_name = validate_new_file_name(args.new_name)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if not source.exists():
            return ToolResult(
                success=False, tool=self.name, message=f"{source} does not exist.",
                error="not_found",
            )
        destination = source.parent / new_name
        if destination.exists():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{destination} already exists, Sir.", error="already_exists",
            )

        try:
            source.rename(destination)
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to rename {source}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name,
            message=f"Renamed {source.name} to {new_name}.",
            data={"source": str(source), "destination": str(destination)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if Path(result.data["source"]).exists() or not Path(result.data["destination"]).exists():
            return ToolResult(
                success=False, tool=self.name,
                message="Rename could not be verified, Sir.", error="verification_failed",
            )
        return result


# --- copy_file (LOW) ---------------------------------------------------


class CopyFileArgs(BaseModel):
    source: str
    destination: str

    model_config = {"extra": "forbid"}


class CopyFileTool(Tool):
    name = "copy_file"
    description = "Copy a file to a new location. Fails if the destination exists."
    permission_level = PermissionLevel.LOW
    args_model = CopyFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CopyFileArgs)
        validated = _validate_two_paths(args.source, args.destination, self._allowed_roots)
        if isinstance(validated, ToolResult):
            validated.tool = self.name
            return validated
        source, destination = validated

        if not source.is_file():
            return ToolResult(
                success=False, tool=self.name, message=f"{source} is not a file.",
                error="not_a_file",
            )
        if destination.exists():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{destination} already exists, Sir.", error="already_exists",
            )

        try:
            shutil.copy2(source, destination)
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to copy {source}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Copied {source} to {destination}.",
            data={"source": str(source), "destination": str(destination)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if not Path(result.data["destination"]).is_file():
            return ToolResult(
                success=False, tool=self.name,
                message="Copy could not be verified, Sir.", error="verification_failed",
            )
        return result


# --- move_file (MEDIUM) -----------------------------------------------


class MoveFileArgs(BaseModel):
    source: str
    destination: str

    model_config = {"extra": "forbid"}


class MoveFileTool(Tool):
    name = "move_file"
    description = "Move a file to a new location. Fails if the destination exists."
    permission_level = PermissionLevel.MEDIUM
    args_model = MoveFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, MoveFileArgs)
        validated = _validate_two_paths(args.source, args.destination, self._allowed_roots)
        if isinstance(validated, ToolResult):
            validated.tool = self.name
            return validated
        source, destination = validated

        if not source.exists():
            return ToolResult(
                success=False, tool=self.name, message=f"{source} does not exist.",
                error="not_found",
            )
        if destination.exists():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{destination} already exists, Sir.", error="already_exists",
            )

        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to move {source}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Moved {source} to {destination}.",
            data={"source": str(source), "destination": str(destination)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if Path(result.data["source"]).exists() or not Path(result.data["destination"]).exists():
            return ToolResult(
                success=False, tool=self.name,
                message="Move could not be verified, Sir.", error="verification_failed",
            )
        return result