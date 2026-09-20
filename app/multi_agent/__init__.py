"""
Multi-Agent Project Planning & Execution module for Victor 2.0.

Orchestrates Gemini (Research & README), ChatGPT (Prompt Engineering & Specification),
and Claude (Project Development) with human-in-the-loop review gating and artifact downloads.
"""

from app.multi_agent.models import (
    AgentRole,
    ArtifactRecord,
    MultiAgentStage,
    ReviewAction,
    WorkflowState,
)

__all__ = [
    "AgentRole",
    "ArtifactRecord",
    "MultiAgentStage",
    "ReviewAction",
    "WorkflowState",
]
