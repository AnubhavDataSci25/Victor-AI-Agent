"""
Read-only filesystem tools (spec section 21): search_files, find_file,
read_file. All SAFE - none of them modify anything on disk.

Directory walking uses os.walk(followlinks=False) deliberately rather
than Path.rglob(): a symlink inside an allowed root could otherwise
point outside it, letting a search silently escape the sandbox that
path_validation.py is meant to enforce. Every file returned still sits
under the validated root because we never follow a link out of it.
"""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field

from app.tools.base import Tool
from app.tools.filesystem.path_validation import PathValidationError, validate_path
from app.tools.models import ToolResult
from app.tools.permissions import PermissionLevel

_DEFAULT_MAX_RESULTS = 200


def _walk_matches(root: Path, predicate) -> list[str]:
    matches: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        for filename in filenames:
            if predicate(filename):
                matches.append(str(Path(dirpath) / filename))
    return matches


# --- search_files -----------------------------------------------------


class SearchFilesArgs(BaseModel):
    path: str
    query: str
    max_results: int = Field(default=_DEFAULT_MAX_RESULTS, ge=1, le=1000)

    model_config = {"extra": "forbid"}


class SearchFilesTool(Tool):
    name = "search_files"
    description = "Search for files whose name contains a substring, recursively."
    permission_level = PermissionLevel.SAFE
    args_model = SearchFilesArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, SearchFilesArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if not resolved.is_dir():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{resolved} is not a directory.", error="not_a_directory",
            )

        query_lower = args.query.lower()
        matches = _walk_matches(resolved, lambda name: query_lower in name.lower())
        truncated = len(matches) > args.max_results
        matches = matches[: args.max_results]

        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Found {len(matches)} match(es) for {args.query!r}.",
            data={"matches": matches, "truncated": truncated},
        )


# --- find_file ----------------------------------------------------------


class FindFileArgs(BaseModel):
    path: str
    filename: str
    max_results: int = Field(default=_DEFAULT_MAX_RESULTS, ge=1, le=1000)

    model_config = {"extra": "forbid"}


class FindFileTool(Tool):
    name = "find_file"
    description = "Find files by exact filename (case-insensitive), recursively."
    permission_level = PermissionLevel.SAFE
    args_model = FindFileArgs

    def __init__(self, allowed_roots: list[Path]) -> None:
        self._allowed_roots = allowed_roots

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, FindFileArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if not resolved.is_dir():
            return ToolResult(
                success=False, tool=self.name,
                message=f"{resolved} is not a directory.", error="not_a_directory",
            )

        target = args.filename.lower()
        matches = _walk_matches(resolved, lambda name: name.lower() == target)
        truncated = len(matches) > args.max_results
        matches = matches[: args.max_results]

        if not matches:
            return ToolResult(
                success=False,
                tool=self.name,
                message=f"No file named {args.filename!r} was found under {resolved}.",
                error="not_found",
            )
        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Found {len(matches)} match(es) for {args.filename!r}.",
            data={"matches": matches, "truncated": truncated},
        )


# --- read_file ------------------------------------------------------------


class ReadFileArgs(BaseModel):
    path: str

    model_config = {"extra": "forbid"}


class ReadFileTool(Tool):
    name = "read_file"
    description = "Read the text content of a file."
    permission_level = PermissionLevel.SAFE
    args_model = ReadFileArgs

    def __init__(self, allowed_roots: list[Path], max_read_bytes: int) -> None:
        self._allowed_roots = allowed_roots
        self._max_read_bytes = max_read_bytes

    def run(self, args: BaseModel) -> ToolResult:
        assert isinstance(args, ReadFileArgs)
        try:
            resolved = validate_path(args.path, self._allowed_roots)
        except PathValidationError as exc:
            return ToolResult(
                success=False, tool=self.name, message=str(exc),
                error="path_validation_failed",
            )
        if not resolved.exists():
            return ToolResult(
                success=False, tool=self.name,
                message=f"File does not exist: {resolved}", error="not_found",
            )
        if not resolved.is_file():
            return ToolResult(
                success=False, tool=self.name,
                message=f"Path is not a file: {resolved}", error="not_a_file",
            )

        size = resolved.stat().st_size
        if size > self._max_read_bytes:
            return ToolResult(
                success=False,
                tool=self.name,
                message=(
                    f"{resolved} is {size} bytes, over the "
                    f"{self._max_read_bytes}-byte read limit, Sir."
                ),
                error="file_too_large",
            )

        try:
            content = resolved.read_text(encoding="utf-8", errors="replace")
        except (OSError, PermissionError) as exc:
            return ToolResult(
                success=False, tool=self.name,
                message=f"Could not read {resolved}: {exc}",
                error="os_permission_denied",
            )

        return ToolResult(
            success=True,
            tool=self.name,
            message=f"Read {size} byte(s) from {resolved}.",
            data={"path": str(resolved), "content": content, "size_bytes": size},
        )