"""
Tests for Multi-Agent BaseTool implementations and ToolRegistry integration.
"""

from pathlib import Path
import pytest

from app.config import MultiAgentConfig
from app.multi_agent.browser_agent import MultiAgentBrowserManager
from app.multi_agent.orchestrator import MultiAgentOrchestrator
from app.tools.multi_agent.tool import (
    MultiAgentDownloadArtifactTool,
    MultiAgentGetStatusTool,
    MultiAgentReviewTool,
    MultiAgentStartProjectTool,
    set_multi_agent_orchestrator,
)
from app.tools.tool_setup import build_tool_registry


@pytest.fixture(autouse=True)
def setup_test_orchestrator(tmp_path: Path):
    cfg = MultiAgentConfig(
        downloads_dir=tmp_path / "Downloads",
        simulate_responses=True,
    )
    mgr = MultiAgentBrowserManager(
        downloads_dir=cfg.downloads_dir,
        simulate_responses=True,
    )
    orch = MultiAgentOrchestrator(config=cfg, browser_manager=mgr)
    set_multi_agent_orchestrator(orch)
    yield orch
    set_multi_agent_orchestrator(None)


@pytest.mark.asyncio
async def test_multi_agent_tools_registered_in_registry():
    registry = build_tool_registry()
    assert registry.get("multi_agent_start_project") is not None
    assert registry.get("multi_agent_review_artifact") is not None
    assert registry.get("multi_agent_get_status") is not None
    assert registry.get("multi_agent_download_artifact") is not None


def test_tool_schemas():
    tools = [
        MultiAgentStartProjectTool(),
        MultiAgentReviewTool(),
        MultiAgentGetStatusTool(),
        MultiAgentDownloadArtifactTool(),
    ]
    for t in tools:
        schema = t.get_schema()
        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema
        assert schema["name"] == t.name


@pytest.mark.asyncio
async def test_start_project_tool_execution():
    tool = MultiAgentStartProjectTool()
    res = await tool.execute({"idea": "AI Resume Scanner", "project_name": "ResumeScanner"})

    assert "STAGE 1 (RESEARCH COMPLETE)" in res
    assert "ResumeScanner".upper() in res
    assert "AUDIT CHECKPOINT" in res
    assert "multi_agent_review_artifact" in res


@pytest.mark.asyncio
async def test_review_artifact_tool_execution():
    start_tool = MultiAgentStartProjectTool()
    await start_tool.execute({"idea": "Crypto Portfolio Tracker", "project_name": "CryptoTrack"})

    review_tool = MultiAgentReviewTool()

    # Test request_changes
    rev_res = await review_tool.execute({
        "action": "request_changes",
        "feedback": "Include tax calculation module.",
    })
    assert "AUDIT CHECKPOINT" in rev_res
    assert "Revision 1" in rev_res

    # Test approve -> progresses to ChatGPT
    appr_res = await review_tool.execute({"action": "approve"})
    assert "ChatGPT" in appr_res
    assert "AUDIT CHECKPOINT" in appr_res

    # Test second approve -> progresses to Claude development
    claude_res = await review_tool.execute({"action": "approve"})
    assert "DEVELOPMENT INITIATED" in claude_res
    assert "Claude" in claude_res


@pytest.mark.asyncio
async def test_status_and_download_tools():
    status_tool = MultiAgentGetStatusTool()
    st_empty = await status_tool.execute({})
    assert "No active multi-agent project" in st_empty

    start_tool = MultiAgentStartProjectTool()
    await start_tool.execute({"idea": "Personal fitness coach", "project_name": "FitCoach"})

    st_active = await status_tool.execute({})
    assert "FITCOACH" in st_active
    assert "Human Review Pending: True" in st_active

    # Download tool before approval
    dl_tool = MultiAgentDownloadArtifactTool()
    dl_res_before = await dl_tool.execute({})
    assert "No artifacts have been generated or saved" in dl_res_before

    # Approve research README
    review_tool = MultiAgentReviewTool()
    await review_tool.execute({"action": "approve"})

    # Download tool after approval
    dl_res_after = await dl_tool.execute({})
    assert "Downloads Directory" in dl_res_after
    assert "FITCOACH_IDEA_README.md" in dl_res_after
