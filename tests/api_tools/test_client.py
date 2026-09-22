"""
Unit tests for ApiClient error handling, timeouts, and retries.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import httpx
import pytest

from app.api_tools.client import (
    ApiClient,
    ApiClientError,
    ApiNotFoundError,
    ApiRateLimitError,
    ApiTimeoutError,
)
from app.api_tools.config import ApiToolsConfig


@pytest.mark.asyncio
async def test_client_get_json_success():
    config = ApiToolsConfig(timeout_seconds=2.0)
    client = ApiClient(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok", "value": 42}

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        result = await client.get_json("https://api.example.com/data")
        assert result == {"status": "ok", "value": 42}

    await client.close()


@pytest.mark.asyncio
async def test_client_404_raises_not_found():
    config = ApiToolsConfig(timeout_seconds=2.0)
    client = ApiClient(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with pytest.raises(ApiNotFoundError):
            await client.get_json("https://api.example.com/unknown")

    await client.close()


@pytest.mark.asyncio
async def test_client_429_raises_rate_limit():
    config = ApiToolsConfig(timeout_seconds=2.0)
    client = ApiClient(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 429
    mock_resp.text = "Too Many Requests"

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with pytest.raises(ApiRateLimitError):
            await client.get_json("https://api.example.com/ratelimited")

    await client.close()


@pytest.mark.asyncio
async def test_client_timeout_raises_timeout_error():
    config = ApiToolsConfig(timeout_seconds=1.0, max_retries=0)
    client = ApiClient(config)

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.side_effect = httpx.TimeoutException("Connection timed out")
        with pytest.raises(ApiTimeoutError):
            await client.get_json("https://api.example.com/timeout")

    await client.close()


@pytest.mark.asyncio
async def test_client_500_retries_and_fails():
    config = ApiToolsConfig(timeout_seconds=1.0, max_retries=1)
    client = ApiClient(config)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch.object(httpx.AsyncClient, "get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp
        with pytest.raises(ApiClientError):
            await client.get_json("https://api.example.com/error")

        assert mock_get.call_count == 2  # 1 initial + 1 retry

    await client.close()
