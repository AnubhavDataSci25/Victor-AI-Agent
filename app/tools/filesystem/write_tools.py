"""
Filesystem tools that create or write content (spec section 21).

Permission levels, and why:
- create_file: SAFE. Refuses to overwrite an existing file (use
  write_file for that), so it can only ever add something new -
  matches "Create folder -> SAFE" in section 12's spirit.
- create_directory: SAFE, same reasoning, and idempotent if the
  directory already exists.
- append_file: LOW. Never destroys existing bytes, only adds to them.
- write_file: MEDIUM. Silently overwrites existing content, which is
  a real risk of data loss - closer to "Modify configuration" than to
  a pure creation. Denied by default until Phase 12's confirmation
  flow exists, same as close_application in Phase 4.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from app.tools.base import Tool
from app.tools.filesystem.path_validation import PathValidationError, validate_path
from app.tools.models import ToolResult
from app.tools.permissions import PermissionLevel


def _validate_parent_exists(resolved: Path) -> str | None:
    """Returns an error message if the parent directory isn't usable, else None."""
    if not resolved.parent.exists():
        return f"Parent directory does not exist: {resolved.parent}"
    if not resolved.parent.is_dir():
        return f"Parent is not a directory: {resolved.parent}"
    return None


# --- create_file ------------------------------------------------------


class CreateFileArgs(BaseModel):
    path: str
    content: str = ""

    model_config = {"extra": "forbid"}


class CreateFileTool(Tool):
    name = "create_file"
    description = "Create a new file with optional content. Fails if it already exists."
    permission_level = PermissionLevel.SAFE
    args_model = CreateFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CreateFileArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if resolved.exists():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{resolved} already exists, Sir. Use write_file to overwrite it.",
                error="already_exists",
            )
        parent_error = _validate_parent_exists(resolved)
        if parent_error:
            return ToolResult(
                success=False, tool=self.name, message=parent_error,
                error="parent_not_found",
            )

        try:
            resolved.write_text(args.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to create {resolved}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Created {resolved}.",
            data={"path": str(resolved), "bytes_written": len(args.content.encode("utf-8"))},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if not Path(result.data["path"]).is_file():
            return ToolResult(
                success=False, tool=self.name,
                message="File was created but could not be verified, Sir.",
                error="verification_failed",
            )
        return result


# --- write_file (MEDIUM - overwrites) --------------------------------------


class WriteFileArgs(BaseModel):
    path: str
    content: str

    model_config = {"extra": "forbid"}


class WriteFileTool(Tool):
    name = "write_file"
    description = "Write content to a file, overwriting it if it already exists."
    permission_level = PermissionLevel.MEDIUM
    args_model = WriteFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, WriteFileArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if resolved.exists() and not resolved.is_file():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{resolved} exists and is not a file.", error="not_a_file",
            )
        parent_error = _validate_parent_exists(resolved)
        if parent_error:
            return ToolResult(
                success=False, tool=self.name, message=parent_error,
                error="parent_not_found",
            )

        try:
            resolved.write_text(args.content, encoding="utf-8")
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to write {resolved}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Wrote {resolved}.",
            data={"path": str(resolved), "bytes_written": len(args.content.encode("utf-8"))},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        path = Path(result.data["path"])
        if not path.is_file() or path.stat().st_size != result.data["bytes_written"]:
            return ToolResult(
                success=False, tool=self.name,
                message="Write could not be verified, Sir.",
                error="verification_failed",
            )
        return result


# --- append_file (LOW) -----------------------------------------------------


class AppendFileArgs(BaseModel):
    path: str
    content: str

    model_config = {"extra": "forbid"}


class AppendFileTool(Tool):
    name = "append_file"
    description = "Append content to a file, creating it if it doesn't exist."
    permission_level = PermissionLevel.LOW
    args_model = AppendFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, AppendFileArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if resolved.exists() and not resolved.is_file():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{resolved} exists and is not a file.", error="not_a_file",
            )
        parent_error = _validate_parent_exists(resolved)
        if parent_error:
            return ToolResult(
                success=False, tool=self.name, message=parent_error,
                error="parent_not_found",
            )

        try:
            with resolved.open("a", encoding="utf-8") as f:
                f.write(args.content)
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to append to {resolved}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Appended to {resolved}.",
            data={"path": str(resolved), "bytes_appended": len(args.content.encode("utf-8"))},
        )


# --- create_directory ----------------------------------------------------


class CreateDirectoryArgs(BaseModel):
    path: str

    model_config = {"extra": "forbid"}


class CreateDirectoryTool(Tool):
    name = "create_directory"
    description = "Create a new directory. Idempotent if it already exists."
    permission_level = PermissionLevel.SAFE
    args_model = CreateDirectoryArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, CreateDirectoryArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if resolved.exists():
            if resolved.is_dir():
                return ToolResult(
                    success=True, tool=self.name,
                    message=f"{resolved} already exists.",
                    data={"path": str(resolved)},
                )
            return ToolResult(
                success=False, tool=self.name,
                message=f"{resolved} exists and is not a directory.",
                error="not_a_directory",
            )

        try:
            resolved.mkdir(parents=True)
        except OSError as exc:
            return ToolResult(
                success=False, tool=self.name, message=f"Failed to create {resolved}: {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True, tool=self.name, message=f"Created directory {resolved}.",
            data={"path": str(resolved)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        if not Path(result.data["path"]).is_dir():
            return ToolResult(
                success=False, tool=self.name,
                message="Directory creation could not be verified, Sir.",
                error="verification_failed",
            )
        return result