"""
Unit tests for ResultVerifier (Phase 3).
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.decision.jev_client import JevClient
from app.decision.models import JevAnswer, JevDecisionResponse
from app.verification.models import VerificationStatus
from app.verification.verifier import ResultVerifier


@pytest.fixture
def mock_jev():
    jev = MagicMock(spec=JevClient)
    jev.is_available.return_value = True
    return jev


@pytest.mark.asyncio
async def test_verifier_file_deletion_confirmed(tmp_path):
    verifier = ResultVerifier()
    test_file = tmp_path / "deleted.txt"
    # File does NOT exist
    assert not test_file.exists()

    res = await verifier.verify("delete_file", {"path": str(test_file)}, "File removed")
    assert res.verified is True
    assert res.status == VerificationStatus.SUCCESS
    assert "confirmed absent" in res.details


@pytest.mark.asyncio
async def test_verifier_file_deletion_failed_if_file_still_exists(tmp_path):
    verifier = ResultVerifier()
    test_file = tmp_path / "still_here.txt"
    test_file.write_text("content")
    assert test_file.exists()

    res = await verifier.verify("delete_file", {"path": str(test_file)}, "File removed")
    assert res.verified is False
    assert res.status == VerificationStatus.FAILED
    assert "still exists on disk" in res.details


@pytest.mark.asyncio
async def test_verifier_file_creation_confirmed(tmp_path):
    verifier = ResultVerifier()
    test_file = tmp_path / "created.txt"
    test_file.write_text("hello world")

    res = await verifier.verify("write_file", {"path": str(test_file)}, "Written")
    assert res.verified is True
    assert res.status == VerificationStatus.SUCCESS
    assert "successfully created" in res.details


@pytest.mark.asyncio
async def test_verifier_api_tools():
    verifier = ResultVerifier()

    # Success case
    res1 = await verifier.verify("api_get_weather", {"location": "London"}, "Weather in London: Clear sky, 20°C.")
    assert res1.verified is True
    assert res1.status == VerificationStatus.SUCCESS

    # Error case
    res2 = await verifier.verify("api_get_stock_price", {"ticker": "XYZ"}, "Error (Yahoo Finance): Current price unavailable")
    assert res2.verified is False
    assert res2.status == VerificationStatus.FAILED


@pytest.mark.asyncio
async def test_verifier_phone_tools():
    verifier = ResultVerifier()

    res_ok = await verifier.verify("phone_answer_call", {}, "Call answered successfully.")
    assert res_ok.verified is True
    assert res_ok.status == VerificationStatus.SUCCESS

    res_err = await verifier.verify("phone_initiate_call", {}, "Error: Phone is not connected.")
    assert res_err.verified is False
    assert res_err.status == VerificationStatus.FAILED


@pytest.mark.asyncio
async def test_verifier_jev_semantic_audit(mock_jev):
    verifier = ResultVerifier(jev_client=mock_jev)

    mock_jev.decide = AsyncMock(
        return_value=JevDecisionResponse(
            answers={
                "outcome": JevAnswer(
                    type="choice",
                    choice="SUCCESS",
                    confidence=0.95,
                )
            }
        )
    )

    res = await verifier.verify(
        "multi_agent_start_project",
        {"name": "MYPROJECT"},
        "Specification and architecture completed and validated.",
    )
    assert res.verified is True
    assert res.status == VerificationStatus.SUCCESS
    assert "Jev classified outcome as SUCCESS" in res.details
    assert res.is_deterministic is False
