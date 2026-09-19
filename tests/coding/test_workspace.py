"""
Tests for WorkspaceResolver and path sandboxing.
"""

from pathlib import Path
import pytest

from app.coding.workspace import (
    WorkspaceResolver,
    WorkspaceResolutionError,
    WorkspaceSecurityError,
)


def test_resolve_explicit_valid_path(tmp_path: Path):
    approved = [str(tmp_path)]
    resolver = WorkspaceResolver(approved)

    project_dir = tmp_path / "MyTestApp"
    project_dir.mkdir()

    resolved = resolver.resolve_workspace(str(project_dir))
    assert resolved == project_dir.resolve()


def test_reject_path_outside_approved_roots(tmp_path: Path):
    approved = [str(tmp_path / "approved")]
    (tmp_path / "approved").mkdir()
    (tmp_path / "unapproved").mkdir()

    resolver = WorkspaceResolver(approved)

    with pytest.raises(WorkspaceSecurityError):
        resolver.resolve_workspace(str(tmp_path / "unapproved"))


def test_reject_nonexistent_path(tmp_path: Path):
    approved = [str(tmp_path)]
    resolver = WorkspaceResolver(approved)

    with pytest.raises(WorkspaceResolutionError) as exc_info:
        resolver.resolve_workspace(str(tmp_path / "does_not_exist"))
    assert "does not exist" in str(exc_info.value)


def test_resolve_bare_name_shallow_search(tmp_path: Path):
    approved = [str(tmp_path)]
    resolver = WorkspaceResolver(approved)

    # Create shallow project: tmp_path / "CareerLens"
    project_dir = tmp_path / "CareerLens"
    project_dir.mkdir()

    resolved = resolver.resolve_workspace("CareerLens")
    assert resolved == project_dir.resolve()


def test_resolve_bare_name_level_2(tmp_path: Path):
    approved = [str(tmp_path)]
    resolver = WorkspaceResolver(approved)

    # Create subfolder project: tmp_path / "Projects" / "CareerLens"
    sub_dir = tmp_path / "Projects" / "CareerLens"
    sub_dir.mkdir(parents=True)

    resolved = resolver.resolve_workspace("CareerLens")
    assert resolved == sub_dir.resolve()


def test_resolve_empty_name():
    resolver = WorkspaceResolver([])
    with pytest.raises(WorkspaceResolutionError):
        resolver.resolve_workspace("")
