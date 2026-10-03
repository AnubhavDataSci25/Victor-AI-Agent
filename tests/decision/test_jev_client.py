"""
Unit tests for JevClient (TypeSafe Jev via OpenRouter).
"""

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.config import DecisionConfig
from app.decision.jev_client import JevClient
from app.decision.models import JevQuestion, QuestionType


@pytest.mark.asyncio
async def test_jev_client_unconfigured_availability():
    config = DecisionConfig(openrouter_api_key="", enabled=True)
    client = JevClient(config)
    assert client.is_available() is False

    # Calling decide returns None without making network calls
    res = await client.decide("Hello", {})
    assert res is None


@pytest.mark.asyncio
async def test_jev_client_success_parsing():
    config = DecisionConfig(
        openrouter_api_key="sk-or-test-key",
        openrouter_base_url="https://openrouter.ai/api/v1",
        jev_model="~typesafe/jev-latest",
        enabled=True,
    )
    client = JevClient(config)
    assert client.is_available() is True

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "public_api",
                "confidence": 0.96,
                "probabilities": {"public_api": 0.96, "general_conversation": 0.04},
            },
            "is_urgent": {
                "type": "noul",
                "noul": 0.12,
            },
        },
        "model": "typesafe/jev-1.13",
        "provider": "TypeSafe",
    }

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        questions = {
            "intent": JevQuestion(type=QuestionType.CHOICE, instructions="Pick a domain"),
            "is_urgent": JevQuestion(type=QuestionType.NOUL, instructions="Is it urgent?"),
        }

        resp = await client.decide("What is the weather in Delhi?", questions)
        assert resp is not None
        assert "intent" in resp.answers
        assert resp.answers["intent"].choice == "public_api"
        assert resp.answers["intent"].confidence == 0.96
        assert "is_urgent" in resp.answers
        assert resp.answers["is_urgent"].noul == 0.12

    await client.close()


@pytest.mark.asyncio
async def test_jev_client_openrouter_choices_parsing():
    import json
    config = DecisionConfig(
        openrouter_api_key="sk-or-test-key",
        openrouter_base_url="https://openrouter.ai/api/v1",
        jev_model="~typesafe/jev-latest",
        enabled=True,
    )
    client = JevClient(config)
    assert client.is_available() is True

    choices_content = json.dumps({
        "answers": {
            "intent": {
                "type": "choice",
                "choice": "music_control",
                "confidence": 0.98,
            },
            "worthy": {
                "type": "noul",
                "noul": 0.85,
            }
        }
    })

    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "id": "gen-12345",
        "model": "~typesafe/jev-latest",
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": choices_content,
                }
            }
        ],
    }

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        questions = {
            "intent": JevQuestion(type=QuestionType.CHOICE, instructions="Domain"),
            "worthy": JevQuestion(type=QuestionType.NOUL, instructions="Is it worthy?"),
        }

        resp = await client.decide("Play Daru Badnaam", questions)
        assert resp is not None
        assert "intent" in resp.answers
        assert resp.answers["intent"].choice == "music_control"
        assert resp.answers["intent"].confidence == 0.98
        assert "worthy" in resp.answers
        assert resp.answers["worthy"].noul == 0.85

        # Verify outgoing payload contained messages for OpenRouter compliance
        mock_post.assert_called_once()
        _, kwargs = mock_post.call_args
        sent_json = kwargs["json"]
        assert "messages" in sent_json
        assert len(sent_json["messages"]) == 2
        assert sent_json["messages"][0]["role"] == "system"
        assert sent_json["messages"][1]["role"] == "user"

    await client.close()


@pytest.mark.asyncio
async def test_jev_client_timeout_fallback():
    config = DecisionConfig(
        openrouter_api_key="sk-or-test-key",
        timeout_seconds=0.5,
        enabled=True,
    )
    client = JevClient(config)

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.side_effect = httpx.TimeoutException("OpenRouter timeout")

        questions = {
            "intent": JevQuestion(type=QuestionType.CHOICE, instructions="Domain"),
        }

        res = await client.decide("Hello", questions)
        assert res is None  # Graceful fallback on timeout

    await client.close()


@pytest.mark.asyncio
async def test_jev_client_http_error_fallback():
    config = DecisionConfig(
        openrouter_api_key="sk-or-test-key",
        enabled=True,
    )
    client = JevClient(config)

    mock_response = MagicMock()
    mock_response.status_code = 502
    mock_response.text = "Bad Gateway"

    with patch.object(httpx.AsyncClient, "post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = mock_response

        questions = {
            "intent": JevQuestion(type=QuestionType.CHOICE, instructions="Domain"),
        }

        res = await client.decide("Hello", questions)
        assert res is None  # Graceful fallback on server error

    await client.close()
