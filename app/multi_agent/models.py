"""
Domain models and state representations for Victor's Multi-Agent Module.
"""

from __future__ import annotations

import time
from enum import Enum
from typing import Any
from pydantic import BaseModel, Field


class MultiAgentStage(str, Enum):
    IDEA_RECEIVED = "IDEA_RECEIVED"
    GEMINI_RESEARCH = "GEMINI_RESEARCH"
    GEMINI_REVIEW_REQUIRED = "GEMINI_REVIEW_REQUIRED"
    GEMINI_REVISION = "GEMINI_REVISION"
    GEMINI_APPROVED = "GEMINI_APPROVED"
    README_DOWNLOADED = "README_DOWNLOADED"
    CHATGPT_PROMPT_ENGINEERING = "CHATGPT_PROMPT_ENGINEERING"
    CHATGPT_REVIEW_REQUIRED = "CHATGPT_REVIEW_REQUIRED"
    CHATGPT_REVISION = "CHATGPT_REVISION"
    CHATGPT_APPROVED = "CHATGPT_APPROVED"
    CLAUDE_DEVELOPMENT = "CLAUDE_DEVELOPMENT"
    DEVELOPMENT_COMPLETE = "DEVELOPMENT_COMPLETE"


class AgentRole(str, Enum):
    GEMINI_RESEARCHER = "gemini_researcher"
    CHATGPT_PROMPT_ENGINEER = "chatgpt_prompt_engineer"
    CLAUDE_DEVELOPER = "claude_developer"


class ReviewAction(str, Enum):
    APPROVE = "approve"
    REJECT = "reject"
    REQUEST_CHANGES = "request_changes"


class ArtifactRecord(BaseModel):
    """Metadata for downloaded or generated artifacts."""
    filename: str
    file_path: str
    stage: MultiAgentStage
    revision: int = 1
    approved: bool = False
    created_at: float = Field(default_factory=time.time)


class WorkflowState(BaseModel):
    """
    Lightweight state container for the multi-agent planning & execution lifecycle.
    """
    project_name: str
    original_idea: str
    current_stage: MultiAgentStage = MultiAgentStage.IDEA_RECEIVED
    active_agent: AgentRole | None = None
    agent_tabs: dict[str, int] = Field(default_factory=dict)
    artifacts: list[ArtifactRecord] = Field(default_factory=list)
    revision_history: list[dict[str, Any]] = Field(default_factory=list)
    current_output: str = ""
    last_feedback: str = ""
    gemini_approved: bool = False
    chatgpt_approved: bool = False
    claude_approved: bool = False
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def transition_to(self, new_stage: MultiAgentStage, active_agent: AgentRole | None = None) -> None:
        self.current_stage = new_stage
        if active_agent is not None:
            self.active_agent = active_agent
        self.updated_at = time.time()

    def record_revision(self, stage: MultiAgentStage, feedback: str, previous_output: str) -> int:
        rev_number = len(self.revision_history) + 1
        self.revision_history.append({
            "revision": rev_number,
            "stage": stage.value,
            "feedback": feedback,
            "previous_output_preview": previous_output[:500],
            "timestamp": time.time(),
        })
        self.last_feedback = feedback
        self.updated_at = time.time()
        return rev_number

    def add_artifact(self, filename: str, file_path: str, stage: MultiAgentStage, approved: bool = False) -> ArtifactRecord:
        record = ArtifactRecord(
            filename=filename,
            file_path=file_path,
            stage=stage,
            revision=len(self.revision_history) + 1,
            approved=approved,
        )
        existing_idx = next((i for i, a in enumerate(self.artifacts) if a.filename == filename), None)
        if existing_idx is not None:
            self.artifacts[existing_idx] = record
        else:
            self.artifacts.append(record)
        self.updated_at = time.time()
        return record
