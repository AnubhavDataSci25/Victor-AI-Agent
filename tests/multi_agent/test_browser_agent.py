"""
Unit tests for MultiAgentBrowserManager fallback and tab isolation.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.multi_agent.browser_agent import MultiAgentBrowserManager
from app.multi_agent.models import AgentRole


@pytest.mark.asyncio
async def test_multi_agent_browser_urls():
    mgr = MultiAgentBrowserManager(simulate_responses=True)
    assert "gemini.google.com" in mgr.get_platform_url(AgentRole.GEMINI_RESEARCHER)
    assert "chatgpt.com" in mgr.get_platform_url(AgentRole.CHATGPT_PROMPT_ENGINEER)
    assert "claude.ai" in mgr.get_platform_url(AgentRole.CLAUDE_DEVELOPER)


@pytest.mark.asyncio
async def test_simulated_responses():
    mgr = MultiAgentBrowserManager(simulate_responses=True)
    gem_res = await mgr.send_prompt_and_receive(
        AgentRole.GEMINI_RESEARCHER,
        "PROJECT NAME: TestApp\nSome idea...",
    )
    assert "TestApp_IDEA_README.md" in gem_res
    assert "Recommended Technology Stack" in gem_res

    gpt_res = await mgr.send_prompt_and_receive(
        AgentRole.CHATGPT_PROMPT_ENGINEER,
        "PROJECT NAME: TestApp\nSpec...",
    )
    assert "TestApp_DEVELOPMENT_SPECIFICATION.md" in gpt_res

    claude_res = await mgr.send_prompt_and_receive(
        AgentRole.CLAUDE_DEVELOPER,
        "PROJECT NAME: TestApp\nDev...",
    )
    assert "Claude Development Status: TestApp" in claude_res


@pytest.mark.asyncio
async def test_generate_direct_llm_fallback():
    mgr = MultiAgentBrowserManager(simulate_responses=False)

    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.text = "# Mocked Direct Fallback Response"
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch("google.genai.Client", return_value=mock_client):
        fallback_text = await mgr.generate_direct_llm_fallback(
            AgentRole.GEMINI_RESEARCHER,
            "Research ideas for AI code editor",
        )
        assert fallback_text == "# Mocked Direct Fallback Response"
        mock_client.aio.models.generate_content.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_prompt_and_receive_raises_on_timeout():
    mgr = MultiAgentBrowserManager(simulate_responses=False)
    # Mock driver to return mock page with timeout
    mock_driver = MagicMock()
    mock_page = MagicMock()
    mock_page.is_closed.return_value = False
    mock_page.url = "https://chatgpt.com"
    mock_page.title = AsyncMock(return_value="ChatGPT")
    mock_page.wait_for_load_state = AsyncMock()
    mock_page.query_selector = AsyncMock(return_value=None)
    mock_driver.new_page = AsyncMock(return_value=mock_page)
    mgr.driver = mock_driver

    # Should raise RuntimeError, not return "Response captured."
    with pytest.raises(RuntimeError) as exc_info:
        await mgr.send_prompt_and_receive(AgentRole.CHATGPT_PROMPT_ENGINEER, "test prompt", timeout_seconds=1.0)
    assert "Could not locate chat input" in str(exc_info.value) or "No valid response" in str(exc_info.value)

