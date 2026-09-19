"""
Coding Computer Control Module for Victor 2.0.

Provides workspace path resolution, project inspection, Groq-based coding plan
generation, controlled terminal execution, and VS Code integration.
"""

from app.coding.models import (
    CompactProjectContext,
    FileAction,
    FileActionType,
    CodingPlan,
    CodingFixPlan,
    ExecutionResult,
    ProjectMetadata,
    ProjectType,
    WorkspaceContext,
)

__all__ = [
    "CompactProjectContext",
    "FileAction",
    "FileActionType",
    "CodingPlan",
    "CodingFixPlan",
    "ExecutionResult",
    "ProjectMetadata",
    "ProjectType",
    "WorkspaceContext",
]
