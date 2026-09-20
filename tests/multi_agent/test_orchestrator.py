"""
Tests for MultiAgentOrchestrator state machine, human review gating, and handoffs.
"""

from pathlib import Path
import pytest

from app.config import MultiAgentConfig
from app.multi_agent.browser_agent import MultiAgentBrowserManager
from app.multi_agent.models import AgentRole, MultiAgentStage, ReviewAction
from app.multi_agent.orchestrator import MultiAgentOrchestrator


@pytest.fixture
def mock_orchestrator(tmp_path: Path):
    cfg = MultiAgentConfig(
        downloads_dir=tmp_path / "Downloads",
        simulate_responses=True,
    )
    mgr = MultiAgentBrowserManager(
        downloads_dir=cfg.downloads_dir,
        simulate_responses=True,
    )
    return MultiAgentOrchestrator(config=cfg, browser_manager=mgr)


@pytest.mark.asyncio
async def test_start_project_empty_idea(mock_orchestrator: MultiAgentOrchestrator):
    res = await mock_orchestrator.start_project(idea="")
    assert res["status"] == "error"
    assert "cannot be empty" in res["message"]


@pytest.mark.asyncio
async def test_start_project_success_and_halts_at_review(mock_orchestrator: MultiAgentOrchestrator):
    res = await mock_orchestrator.start_project(
        idea="Build a personalized AI tutor that teaches coding through interactive games.",
        project_name="AITutor",
    )

    assert res["status"] == "review_required"
    assert res["stage"] == MultiAgentStage.GEMINI_REVIEW_REQUIRED.value
    assert res["project_name"] == "AITUTOR"
    assert "AITUTOR_IDEA_README.md" in res["artifact_name"]
    assert "AUDIT REQUIRED" in res["message"]
    assert len(res["content"]) > 0

    # Ensure state machine halted
    assert mock_orchestrator.state is not None
    assert mock_orchestrator.state.current_stage == MultiAgentStage.GEMINI_REVIEW_REQUIRED
    assert mock_orchestrator.state.gemini_approved is False


@pytest.mark.asyncio
async def test_gemini_review_revision_cycle(mock_orchestrator: MultiAgentOrchestrator):
    await mock_orchestrator.start_project(idea="An e-commerce analytics tool", project_name="AnalyticsHub")

    # Request changes without feedback -> error
    err_res = await mock_orchestrator.review_artifact(action=ReviewAction.REQUEST_CHANGES, feedback="")
    assert err_res["status"] == "error"
    assert "Feedback is required" in err_res["message"]

    # Request changes with feedback
    rev_res = await mock_orchestrator.review_artifact(
        action=ReviewAction.REQUEST_CHANGES,
        feedback="Include real-time Stripe webhook integration details.",
    )
    assert rev_res["status"] == "review_required"
    assert rev_res["stage"] == MultiAgentStage.GEMINI_REVIEW_REQUIRED.value
    assert rev_res["revision"] == 1
    assert mock_orchestrator.state.current_stage == MultiAgentStage.GEMINI_REVIEW_REQUIRED
    assert mock_orchestrator.state.gemini_approved is False
    assert len(mock_orchestrator.state.revision_history) == 1


@pytest.mark.asyncio
async def test_gemini_review_reject(mock_orchestrator: MultiAgentOrchestrator):
    await mock_orchestrator.start_project(idea="An app", project_name="App")
    res = await mock_orchestrator.review_artifact(action=ReviewAction.REJECT)
    assert res["status"] == "rejected"
    assert "workflow is paused" in res["message"]


@pytest.mark.asyncio
async def test_full_pipeline_with_mandatory_human_approvals(
    mock_orchestrator: MultiAgentOrchestrator, tmp_path: Path
):
    # Step 1: Start Project
    res1 = await mock_orchestrator.start_project(
        idea="Build a decentralized task management board",
        project_name="TaskBoard",
    )
    assert res1["status"] == "review_required"
    assert mock_orchestrator.state.current_stage == MultiAgentStage.GEMINI_REVIEW_REQUIRED

    # Step 2: Human Approves Gemini Research
    res2 = await mock_orchestrator.review_artifact(action=ReviewAction.APPROVE)
    assert res2["status"] == "review_required"
    assert res2["stage"] == MultiAgentStage.CHATGPT_REVIEW_REQUIRED.value
    assert "ChatGPT" in res2["active_agent"]

    # Check that Gemini artifact was saved into Downloads
    readme_file = tmp_path / "Downloads" / "TASKBOARD_IDEA_README.md"
    assert readme_file.exists()
    assert "# TASKBOARD_IDEA_README.md" in readme_file.read_text(encoding="utf-8")
    assert mock_orchestrator.state.gemini_approved is True
    assert mock_orchestrator.state.chatgpt_approved is False

    # Step 3: Human Approves ChatGPT Development Specification
    res3 = await mock_orchestrator.review_artifact(action=ReviewAction.APPROVE)
    assert res3["status"] == "development_started"
    assert res3["stage"] == MultiAgentStage.DEVELOPMENT_COMPLETE.value
    assert "Claude" in res3["active_agent"]

    # Check that Specification artifact was saved into Downloads
    spec_file = tmp_path / "Downloads" / "TASKBOARD_DEVELOPMENT_SPECIFICATION.md"
    assert spec_file.exists()
    assert "# TASKBOARD_DEVELOPMENT_SPECIFICATION.md" in spec_file.read_text(encoding="utf-8")
    assert mock_orchestrator.state.chatgpt_approved is True
    assert mock_orchestrator.state.claude_approved is True


@pytest.mark.asyncio
async def test_orchestrator_status_and_downloads(
    mock_orchestrator: MultiAgentOrchestrator, tmp_path: Path
):
    # Initially no project
    st0 = mock_orchestrator.get_status()
    assert st0["active_project"] is False

    dl0 = mock_orchestrator.download_artifact()
    assert dl0["status"] == "error"

    # Start and advance through Gemini
    await mock_orchestrator.start_project(idea="Smart calendar assistant", project_name="CalAI")
    st1 = mock_orchestrator.get_status()
    assert st1["active_project"] is True
    assert st1["project_name"] == "CALAI"
    assert st1["review_pending"] is True
    assert st1["gemini_approved"] is False

    # Approve Gemini README
    await mock_orchestrator.review_artifact(action=ReviewAction.APPROVE)

    # Check artifacts via download_artifact
    dl1 = mock_orchestrator.download_artifact()
    assert dl1["status"] == "success"
    assert len(dl1["artifacts"]) == 1
    assert dl1["artifacts"][0]["filename"] == "CALAI_IDEA_README.md"
    assert dl1["artifacts"][0]["exists"] is True

    # Check filtering by artifact_type
    dl_readme = mock_orchestrator.download_artifact("readme")
    assert dl_readme["status"] == "success"
    assert len(dl_readme["artifacts"]) == 1

    dl_spec = mock_orchestrator.download_artifact("specification")
    # Not yet saved to artifacts list, but current_output exists -> saves current
    assert dl_spec["status"] == "success"
