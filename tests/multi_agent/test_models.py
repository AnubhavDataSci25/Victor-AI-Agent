"""
Tests for Multi-Agent data models and state transitions.
"""

import pytest
from app.multi_agent.models import (
    AgentRole,
    ArtifactRecord,
    MultiAgentStage,
    ReviewAction,
    WorkflowState,
)


def test_agent_roles_and_review_actions():
    assert AgentRole.GEMINI_RESEARCHER.value == "gemini_researcher"
    assert AgentRole.CHATGPT_PROMPT_ENGINEER.value == "chatgpt_prompt_engineer"
    assert AgentRole.CLAUDE_DEVELOPER.value == "claude_developer"

    assert ReviewAction.APPROVE.value == "approve"
    assert ReviewAction.REJECT.value == "reject"
    assert ReviewAction.REQUEST_CHANGES.value == "request_changes"


def test_workflow_state_initialization():
    state = WorkflowState(
        project_name="TEST_APP",
        original_idea="Build an autonomous AI agent for finance.",
        current_stage=MultiAgentStage.IDEA_RECEIVED,
    )
    assert state.project_name == "TEST_APP"
    assert state.current_stage == MultiAgentStage.IDEA_RECEIVED
    assert not state.gemini_approved
    assert not state.chatgpt_approved
    assert not state.claude_approved
    assert len(state.artifacts) == 0
    assert len(state.revision_history) == 0


def test_workflow_state_transitions():
    state = WorkflowState(
        project_name="DEMO",
        original_idea="A real-time dashboard",
    )

    state.transition_to(MultiAgentStage.GEMINI_RESEARCH, active_agent=AgentRole.GEMINI_RESEARCHER)
    assert state.current_stage == MultiAgentStage.GEMINI_RESEARCH
    assert state.active_agent == AgentRole.GEMINI_RESEARCHER

    state.transition_to(MultiAgentStage.GEMINI_REVIEW_REQUIRED)
    assert state.current_stage == MultiAgentStage.GEMINI_REVIEW_REQUIRED

    # Add artifact
    state.add_artifact(
        filename="DEMO_IDEA_README.md",
        file_path="/downloads/DEMO_IDEA_README.md",
        stage=MultiAgentStage.GEMINI_APPROVED,
        approved=True,
    )
    assert len(state.artifacts) == 1
    assert state.artifacts[0].filename == "DEMO_IDEA_README.md"
    assert state.artifacts[0].approved is True

    # Record revision
    rev_num = state.record_revision(
        stage=MultiAgentStage.GEMINI_REVISION,
        feedback="Add PostgreSQL support",
        previous_output="# Initial output",
    )
    assert rev_num == 1
    assert len(state.revision_history) == 1
    assert state.revision_history[0]["feedback"] == "Add PostgreSQL support"
    assert state.last_feedback == "Add PostgreSQL support"

    rev_num_2 = state.record_revision(
        stage=MultiAgentStage.GEMINI_REVISION,
        feedback="Include Docker Compose",
        previous_output="# Revised output",
    )
    assert rev_num_2 == 2
    assert len(state.revision_history) == 2
