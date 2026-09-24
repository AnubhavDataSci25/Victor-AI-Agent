"""
Unit tests for DecisionEngine (Fast-path heuristics + Jev integration).
"""

from unittest.mock import AsyncMock, MagicMock
import pytest

from app.decision.engine import DecisionEngine
from app.decision.jev_client import JevClient
from app.decision.models import JevAnswer, JevDecisionResponse


@pytest.fixture
def mock_jev():
    jev = MagicMock(spec=JevClient)
    jev.is_available.return_value = True
    return jev


@pytest.mark.asyncio
async def test_fast_path_routing_without_jev_call(mock_jev):
    engine = DecisionEngine(jev_client=mock_jev)

    # 1. Weather fast-path
    res1 = await engine.route_intent("What is the weather today in Mumbai?")
    assert res1.intent == "public_api"
    assert "api_get_weather" in res1.candidate_tools
    assert res1.source == "deterministic"
    assert mock_jev.decide.call_count == 0  # Did not call Jev!

    # 2. Stock fast-path
    res2 = await engine.route_intent("Check Apple stock price AAPL")
    assert res2.intent == "public_api"
    assert "api_get_stock_price" in res2.candidate_tools
    assert res2.source == "deterministic"
    assert mock_jev.decide.call_count == 0

    # 3. Volume fast-path
    res3 = await engine.route_intent("Mute volume please")
    assert res3.intent == "system_control"
    assert "system_adjust_volume" in res3.candidate_tools
    assert res3.source == "deterministic"
    assert mock_jev.decide.call_count == 0


@pytest.mark.asyncio
async def test_ambiguous_routing_calls_jev(mock_jev):
    engine = DecisionEngine(jev_client=mock_jev)

    mock_jev.decide = AsyncMock(
        return_value=JevDecisionResponse(
            answers={
                "intent": JevAnswer(
                    type="choice",
                    choice="computer_coding",
                    confidence=0.92,
                )
            }
        )
    )

    res = await engine.route_intent("Inspect the codebase and build the project")
    assert res.intent == "computer_coding"
    assert res.confidence == 0.92
    assert res.source == "jev"
    assert mock_jev.decide.call_count == 1


@pytest.mark.asyncio
async def test_jev_unavailable_fallback():
    mock_jev = MagicMock(spec=JevClient)
    mock_jev.is_available.return_value = False

    engine = DecisionEngine(jev_client=mock_jev)
    res = await engine.route_intent("Something totally ambiguous")

    assert res.intent == "general_conversation"
    assert res.source == "deterministic_fallback"


@pytest.mark.asyncio
async def test_risk_assessment_destructive_file_deletion(mock_jev):
    engine = DecisionEngine(jev_client=mock_jev)

    risk_res = await engine.assess_risk("delete_file", {"path": "important.txt"})
    assert risk_res.risk_level == "DESTRUCTIVE"
    assert risk_res.requires_confirmation is True
    assert risk_res.source == "deterministic"


@pytest.mark.asyncio
async def test_memory_worthiness_evaluation(mock_jev):
    engine = DecisionEngine(jev_client=mock_jev)

    # Deterministic phrase
    mem1 = await engine.evaluate_memory_worthiness("Remember that I prefer dark mode in all apps")
    assert mem1.is_worthy is True
    assert mem1.probability >= 0.90
    assert mem1.priority == "high"
    assert mem1.should_ask_user is False
    assert mem1.source == "deterministic"

    # Jev-evaluated phrase with medium priority requiring consent
    mock_jev.decide = AsyncMock(
        return_value=JevDecisionResponse(
            answers={
                "worthy": JevAnswer(type="noul", noul=0.88),
                "priority": JevAnswer(type="choice", choice="medium"),
                "category": JevAnswer(type="choice", choice="preference"),
                "ask_consent": JevAnswer(type="noul", noul=0.75),
            }
        )
    )
    mem2 = await engine.evaluate_memory_worthiness("I might start learning Rust next month")
    assert mem2.is_worthy is True
    assert mem2.probability == 0.88
    assert mem2.priority == "medium"
    assert mem2.should_ask_user is True
    assert mem2.source == "jev"


@pytest.mark.asyncio
async def test_memory_sanitizer_security_block(mock_jev):
    """Verify passwords and API keys are blocked by decision memory evaluation."""
    engine = DecisionEngine(jev_client=mock_jev)
    mem = await engine.evaluate_memory_worthiness("Remember that my password is superSecret123")
    assert mem.is_worthy is False
    assert mem.priority == "low"
    assert mem.source == "sanitizer"
    assert "Security policy rejection" in mem.reasoning


@pytest.mark.asyncio
async def test_transient_action_not_worthy(mock_jev):
    """Verify fleeting queries and tool commands are not saved to memory."""
    engine = DecisionEngine(jev_client=mock_jev)
    mem = await engine.evaluate_memory_worthiness("what is the time right now?")
    assert mem.is_worthy is False
    assert mem.priority == "low"
    assert mem.source == "deterministic"

