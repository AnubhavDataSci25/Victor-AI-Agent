"""
Path validation for filesystem tools (spec section 21, rule 7).

Every filesystem tool must resolve and validate a path through this
module before touching disk. This is intentionally strict and boring:
- Resolves symlinks and ".." segments (Path.resolve()) so a crafted
  path like "~/../../etc/passwd" can't sneak past a naive prefix check.
- Requires the resolved path to sit inside one of the configured
  allowed roots.
- Never trusts the caller's string representation of the path - only
  the resolved, absolute result.
"""

from __future__ import annotations

import os
from pathlib import Path


class PathValidationError(Exception):
    """Raised when a requested path falls outside allowed roots."""


def _expand_user(path: str) -> Path:
    if path == "~" or path.startswith(("~/", "~\\")):
        home = os.environ.get("HOME")
        if home:
            return Path(home) / path[2:] if len(path) > 1 else Path(home)
    return Path(path).expanduser()


def resolve_allowed_roots(raw_roots: list[str]) -> list[Path]:
    return [_expand_user(root).resolve() for root in raw_roots]


def validate_path(raw_path: str, allowed_roots: list[Path]) -> Path:
    """
    Resolve `raw_path` and confirm it lives under one of the allowed
    roots. Returns the resolved, absolute Path on success. Raises
    PathValidationError otherwise. Works whether or not the path
    currently exists - callers creating a new file/directory still
    need this check to run before anything touches disk.
    """
    if not raw_path or not raw_path.strip():
        raise PathValidationError("Path must not be empty")

    candidate = _expand_user(raw_path).resolve()

    for root in allowed_roots:
        try:
            candidate.relative_to(root)
        except ValueError:
            continue
        else:
            return candidate

    raise PathValidationError(
        f"Path {raw_path!r} resolves outside of Victor's allowed directories"
    )


def validate_new_file_name(name: str) -> str:
    """
    Validate a bare filename (not a path) used for rename operations -
    rejects anything containing a path separator, which would let a
    'rename' silently become a move to an arbitrary location.
    """
    if not name or not name.strip():
        raise PathValidationError("Name must not be empty")
    if "/" in name or "\\" in name:
        raise PathValidationError(
            f"{name!r} must be a plain filename, not a path (use move_file to relocate)"
        )
    if name in (".", ".."):
        raise PathValidationError(f"{name!r} is not a valid filename")
    return name
