"""
Dedicated File Explorer & Search toolset for Victor.

Provides safe, deterministic filesystem operations adhering to Victor's
two-layer security model:
1. Search (SAFE): Search files/folders across allowed roots; optionally reveal in Windows File Explorer.
2. Open (LOW): Open files or folders with native Windows applications or whitelisted apps.
3. Rename (MEDIUM): Rename file in place, preventing overwrite and requiring confirmation.
4. Move (HIGH): Move file to destination, preventing traversal and overwrite, requiring confirmation.
5. Delete (HIGH): Permanently delete a file, strictly rejecting directory deletion, requiring confirmation.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.tools.base import Tool
from app.tools.computer.windows_driver import APP_WHITELIST
from app.tools.filesystem.path_validation import (
    PathValidationError,
    validate_new_file_name,
    validate_path,
)
from app.tools.models import ToolResult
from app.tools.permissions import PermissionLevel

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Search Operation (SAFE)
# ---------------------------------------------------------------------------


class FileExplorerSearchArgs(BaseModel):
    query: str = Field(
        description="Search term/substring to match against file or folder names."
    )
    path: Optional[str] = Field(
        default=None,
        description="Optional directory path to search within. If omitted, searches across all configured allowed roots.",
    )
    file_type: Optional[str] = Field(
        default=None,
        description="Optional filter: 'file', 'directory' / 'folder', or extension like '.txt', '.pdf', '.py'.",
    )
    open_in_explorer: bool = Field(
        default=False,
        description="Set to True ONLY if the user explicitly requested to open/show the result in Windows File Explorer.",
    )
    max_results: int = Field(
        default=50,
        ge=1,
        le=200,
        description="Maximum number of matches to return (concise limit).",
    )

    model_config = {"extra": "forbid"}


class FileExplorerSearchTool(Tool):
    name = "file_explorer_search"
    description = (
        "Search for files, folders, or directories by name/path across allowed roots. "
        "Can optionally open/activate Windows File Explorer at the matching location."
    )
    permission_level = PermissionLevel.SAFE
    args_model = FileExplorerSearchArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FileExplorerSearchArgs)

        # 1. Determine search roots
        search_roots: list[Path] = []
        if args.path and args.path.strip():
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
                    message=f"Search path does not exist: {resolved}",
                    error="not_found",
                )
            if not resolved.is_dir():
                return ToolResult(
                    success=False,
                    tool=self.name,
                    message=f"Search path is not a directory: {resolved}",
                    error="not_a_directory",
                )
            search_roots.append(resolved)
        else:
            for root in self._allowed_roots:
                if root.exists() and root.is_dir():
                    search_roots.append(root)

        if not search_roots:
            return ToolResult(
                success=False,
                tool=self.name,
                message="No valid allowed root directories available to search.",
                error="no_roots_found",
            )

        # 2. Filter setup
        query_lower = args.query.lower()
        type_filter = (args.file_type or "").strip().lower()

        include_dirs = type_filter not in ("file",) and not type_filter.startswith(".")
        include_files = type_filter not in ("directory", "folder")

        matches: list[dict[str, Any]] = []

        # 3. Walk directories (followlinks=False to prevent symlink traversal)
        for root in search_roots:
            for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
                current_dir = Path(dirpath)

                # Match directories
                if include_dirs:
                    for d in dirnames:
                        if query_lower in d.lower():
                            matches.append({
                                "name": d,
                                "path": str(current_dir / d),
                                "type": "directory",
                            })
                            if len(matches) >= args.max_results:
                                break

                if len(matches) >= args.max_results:
                    break

                # Match files
                if include_files:
                    for f in filenames:
                        if query_lower in f.lower():
                            if type_filter.startswith(".") and not f.lower().endswith(type_filter):
                                continue
                            file_path = current_dir / f
                            size = 0
                            try:
                                size = file_path.stat().st_size
                            except OSError:
                                pass
                            matches.append({
                                "name": f,
                                "path": str(file_path),
                                "type": "file",
                                "size_bytes": size,
                            })
                            if len(matches) >= args.max_results:
                                break

                if len(matches) >= args.max_results:
                    break

            if len(matches) >= args.max_results:
                break

        # 4. Optional Windows File Explorer activation
        explorer_opened = False
        explorer_target = None
        if args.open_in_explorer and matches:
            first_match_path = Path(matches[0]["path"])
            explorer_target = str(first_match_path)
            try:
                if sys.platform == "win32":
                    if first_match_path.is_file():
                        subprocess.Popen(
                            ["explorer.exe", f"/select,{first_match_path}"],
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                    else:
                        subprocess.Popen(
                            ["explorer.exe", str(first_match_path)],
                            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                        )
                    explorer_opened = True
            except Exception as e:
                logger.warning(f"Could not open Windows File Explorer: {e}")

        msg = f"Found {len(matches)} match(es) for {args.query!r}."
        if explorer_opened:
            msg += f" Opened Windows File Explorer at '{explorer_target}'."

        return ToolResult(
            success=True,
            tool=self.name,
            message=msg,
            data={
                "matches": matches,
                "count": len(matches),
                "explorer_opened": explorer_opened,
            },
        )


# ---------------------------------------------------------------------------
# 2. Open Operation (LOW)
# ---------------------------------------------------------------------------


class FileExplorerOpenArgs(BaseModel):
    path: str = Field(description="Path to the file or directory to open.")
    app_name: Optional[str] = Field(
        default=None,
        description="Optional whitelisted application name to open the file with (e.g., 'notepad', 'vscode').",
    )

    model_config = {"extra": "forbid"}


class FileExplorerOpenTool(Tool):
    name = "file_explorer_open"
    description = (
        "Open a requested file or directory using the appropriate Windows application with LOW permission. "
        "Enforces sandbox allowed-root boundaries."
    )
    permission_level = PermissionLevel.LOW
    args_model = FileExplorerOpenArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FileExplorerOpenArgs)
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
                message=f"Path does not exist: {resolved}",
                error="not_found",
            )

        # Opening with a specific requested application
        if args.app_name:
            app_key = args.app_name.lower().replace(" ", "_")
            if app_key not in APP_WHITELIST:
                allowed_apps = ", ".join(sorted(APP_WHITELIST.keys()))
                return ToolResult(
                    success=False,
                    tool=self.name,
                    message=f"Application '{args.app_name}' is not whitelisted. Approved applications: {allowed_apps}.",
                    error="app_not_whitelisted",
                )

            executable = APP_WHITELIST[app_key]
            try:
                if sys.platform == "win32":
                    subprocess.Popen(
                        [executable, str(resolved)],
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                return ToolResult(
                    success=True,
                    tool=self.name,
                    message=f"Opened '{resolved.name}' with {args.app_name}.",
                    data={"path": str(resolved), "application": args.app_name},
                )
            except Exception as e:
                return ToolResult(
                    success=False,
                    tool=self.name,
                    message=f"Failed to open '{resolved}' with {args.app_name}: {e}",
                    error="launch_failed",
                )

        # Default opening: use Windows shell association or File Explorer
        try:
            if sys.platform == "win32":
                if resolved.is_dir():
                    subprocess.Popen(
                        ["explorer.exe", str(resolved)],
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
                    )
                else:
                    os.startfile(str(resolved))  # type: ignore[attr-defined]
            return ToolResult(
                success=True,
                tool=self.name,
                message=f"Opened '{resolved.name}' successfully in default Windows application.",
                data={"path": str(resolved), "is_dir": resolved.is_dir()},
            )
        except Exception as e:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Failed to open '{resolved}': {e}",
                error="open_failed",
            )


# ---------------------------------------------------------------------------
# 3. Rename Operation (MEDIUM - Requires Confirmation)
# ---------------------------------------------------------------------------


class FileExplorerRenameArgs(BaseModel):
    path: str = Field(description="Current path to the file to rename.")
    new_name: str = Field(
        description="New bare filename (e.g. 'notes_updated.txt'), not a path."
    )
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation to perform the rename.",
    )

    model_config = {"extra": "forbid"}


class FileExplorerRenameTool(Tool):
    name = "file_explorer_rename"
    description = (
        "Rename a file within its current directory. Requires explicit user confirmation (MEDIUM permission). "
        "Prevents accidental overwrites."
    )
    permission_level = PermissionLevel.MEDIUM
    args_model = FileExplorerRenameArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FileExplorerRenameArgs)
        try:
            source = validate_path(args.path, self._allowed_roots)
            new_name = validate_new_file_name(args.new_name)
        except PathValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=str(exc),
                error="path_validation_failed",
            )

        if not source.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"File does not exist: {source}",
                error="not_found",
            )

        destination = source.parent / new_name
        try:
            validate_path(str(destination), self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Rename destination violates sandbox boundaries: {exc}",
                error="path_validation_failed",
            )

        if destination.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Destination '{destination.name}' already exists in '{source.parent}'. Overwrite is prevented.",
                error="already_exists",
            )

        # Deterministic confirmation requirement (MEDIUM permission)
        if not args.confirmed:
            return ToolResult(
                success=False,
                tool=self.name,
                message=(
                    f"Permission level MEDIUM requires explicit confirmation to rename "
                    f"'{source.name}' to '{new_name}' in '{source.parent}'. "
                    f"Please confirm this action with confirmed=True to proceed."
                ),
                error="confirmation_required",
                data={
                    "source": str(source),
                    "destination": str(destination),
                    "new_name": new_name,
                    "requires_confirmation": True,
                },
            )

        try:
            source.rename(destination)
        except OSError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Failed to rename '{source.name}': {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Renamed '{source.name}' to '{new_name}'.",
            data={"source": str(source), "destination": str(destination)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        source_path = Path(result.data["source"])
        dest_path = Path(result.data["destination"])
        if source_path.exists() or not dest_path.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message="Rename verification failed: destination file missing or source still exists.",
                error="verification_failed",
            )
        return result


# ---------------------------------------------------------------------------
# 4. Move Operation (HIGH - Requires Confirmation)
# ---------------------------------------------------------------------------


class FileExplorerMoveArgs(BaseModel):
    source: str = Field(description="Path to the file to move.")
    destination: str = Field(
        description="Destination directory or target file path."
    )
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation to perform the move.",
    )

    model_config = {"extra": "forbid"}


class FileExplorerMoveTool(Tool):
    name = "file_explorer_move"
    description = (
        "Move a file to a new location. Requires explicit user confirmation (HIGH permission). "
        "Prevents path traversal, directory moving, and accidental overwrites."
    )
    permission_level = PermissionLevel.HIGH
    args_model = FileExplorerMoveArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FileExplorerMoveArgs)
        try:
            source = validate_path(args.source, self._allowed_roots)
            dest_raw = validate_path(args.destination, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=str(exc),
                error="path_validation_failed",
            )

        if not source.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Source does not exist: {source}",
                error="not_found",
            )

        if not source.is_file():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Source '{source}' is a directory. Moving directories is not permitted.",
                error="not_a_file",
            )

        # Resolve target destination path
        if dest_raw.is_dir():
            target_dest = dest_raw / source.name
        else:
            target_dest = dest_raw

        # Re-verify target destination sits under allowed roots
        try:
            validate_path(str(target_dest), self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Move destination violates sandbox boundaries: {exc}",
                error="path_validation_failed",
            )

        if target_dest.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Destination '{target_dest}' already exists. Overwrite is prevented.",
                error="already_exists",
            )

        # Deterministic confirmation requirement (HIGH permission)
        if not args.confirmed:
            return ToolResult(
                success=False,
                tool=self.name,
                message=(
                    f"Permission level HIGH requires explicit confirmation to move file "
                    f"'{source.name}' from '{source.parent}' to '{target_dest}'. "
                    f"Please confirm this action with confirmed=True to proceed."
                ),
                error="confirmation_required",
                data={
                    "source": str(source),
                    "destination": str(target_dest),
                    "requires_confirmation": True,
                },
            )

        try:
            shutil.move(str(source), str(target_dest))
        except OSError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Failed to move '{source.name}': {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Moved '{source.name}' to '{target_dest}'.",
            data={"source": str(source), "destination": str(target_dest)},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        source_path = Path(result.data["source"])
        dest_path = Path(result.data["destination"])
        if source_path.exists() or not dest_path.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message="Move verification failed: destination file missing or source still exists.",
                error="verification_failed",
            )
        return result


# ---------------------------------------------------------------------------
# 5. Delete Operation (HIGH - Requires Confirmation)
# ---------------------------------------------------------------------------


class FileExplorerDeleteArgs(BaseModel):
    path: str = Field(description="Path to the file to permanently delete.")
    confirmed: bool = Field(
        default=False,
        description="Explicit user confirmation to permanently delete the file.",
    )

    model_config = {"extra": "forbid"}


class FileExplorerDeleteTool(Tool):
    name = "file_explorer_delete"
    description = (
        "Permanently delete a single file. Requires explicit user confirmation (HIGH permission). "
        "Strictly refuses directory deletion."
    )
    permission_level = PermissionLevel.HIGH
    args_model = FileExplorerDeleteArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FileExplorerDeleteArgs)
        try:
            target = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=str(exc),
                error="path_validation_failed",
            )

        if not target.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"File does not exist: {target}",
                error="not_found",
            )

        # Strictly forbid directory deletion
        if not target.is_file():
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Target '{target}' is a directory. Folder deletion is strictly forbidden in this module.",
                error="directory_deletion_forbidden",
            )

        size_bytes = 0
        try:
            size_bytes = target.stat().st_size
        except OSError:
            pass

        # Deterministic confirmation requirement (HIGH permission)
        if not args.confirmed:
            return ToolResult(
                success=False,
                tool=self.name,
                message=(
                    f"Permission level HIGH requires explicit confirmation to permanently delete "
                    f"file '{target.name}' at '{target}' ({size_bytes} bytes). "
                    f"Please confirm this action with confirmed=True to proceed."
                ),
                error="confirmation_required",
                data={
                    "path": str(target),
                    "file_name": target.name,
                    "size_bytes": size_bytes,
                    "requires_confirmation": True,
                },
            )

        try:
            target.unlink()
        except OSError as exc:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"Failed to delete '{target.name}': {exc}",
                error="os_error",
            )

        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Permanently deleted '{target.name}' ({size_bytes} bytes).",
            data={"path": str(target), "size_bytes": size_bytes},
        )

    def verify(self, args: BaseModel, result: ToolResult) -> ToolResult:
        if not result.success:
            return result
        target_path = Path(result.data["path"])
        if target_path.exists():
            return ToolResult(
                success=False,
                tool=self.name,
                message="Delete verification failed: file still exists on disk.",
                error="verification_failed",
            )
        return result
