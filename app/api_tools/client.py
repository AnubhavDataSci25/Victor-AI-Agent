"""
Centralized Async HTTP Client for Victor's Free Public API Tools.

Wraps httpx.AsyncClient with:
- Strict timeouts and connection pooling
- Standard browser/agent headers
- Transparent error classification and retries
- Safe resource management
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional
import httpx

from app.api_tools.config import ApiToolsConfig

logger = logging.getLogger(__name__)


class ApiClientError(Exception):
    """Base exception for API client failures."""
    def __init__(self, message: str, status_code: Optional[int] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ApiTimeoutError(ApiClientError):
    """Raised when an external API call times out."""


class ApiRateLimitError(ApiClientError):
    """Raised when an external API rate limits requests (HTTP 429)."""


class ApiNotFoundError(ApiClientError):
    """Raised when an external resource or ticker is not found (HTTP 404)."""


class ApiClient:
    """Reusable asynchronous HTTP client with timeouts, headers, and retries."""

    def __init__(self, config: Optional[ApiToolsConfig] = None) -> None:
        self.config = config or ApiToolsConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._lock = asyncio.Lock()

    async def _get_client(self) -> httpx.AsyncClient:
        async with self._lock:
            if self._client is None or self._client.is_closed:
                headers = {
                    "User-Agent": self.config.user_agent,
                    "Accept": "application/json, text/plain, */*",
                }
                timeout = httpx.Timeout(self.config.timeout_seconds, connect=5.0)
                self._client = httpx.AsyncClient(
                    headers=headers,
                    timeout=timeout,
                    follow_redirects=True,
                )
            return self._client

    async def get_json(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        retries: Optional[int] = None,
    ) -> Any:
        """Execute a GET request and parse the response as JSON."""
        max_retries = self.config.max_retries if retries is None else retries
        last_err: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                client = await self._get_client()
                response = await client.get(url, params=params, headers=headers)

                if response.status_code == 200:
                    try:
                        return response.json()
                    except Exception as json_err:
                        raise ApiClientError(f"Malformed JSON response from {url}: {json_err}") from json_err

                if response.status_code == 204:
                    return None

                if response.status_code == 404:
                    raise ApiNotFoundError(f"Resource not found at {url} (HTTP 404)", status_code=404)

                if response.status_code == 429:
                    raise ApiRateLimitError("Rate limit exceeded for public endpoint (HTTP 429)", status_code=429)

                if response.status_code >= 500:
                    # Retry on server error
                    logger.warning(f"API server error {response.status_code} for {url} (attempt {attempt + 1})")
                    if attempt < max_retries:
                        await asyncio.sleep(0.5 * (attempt + 1))
                        continue
                    raise ApiClientError(f"External service error (HTTP {response.status_code})", status_code=response.status_code)

                raise ApiClientError(
                    f"Unexpected API response status {response.status_code}: {response.text[:200]}",
                    status_code=response.status_code,
                )

            except (ApiNotFoundError, ApiRateLimitError):
                raise
            except httpx.TimeoutException as exc:
                last_err = exc
                logger.warning(f"Timeout connecting to {url} (attempt {attempt + 1}/{max_retries + 1})")
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ApiTimeoutError(f"Request to {url} timed out after {self.config.timeout_seconds}s") from exc
            except httpx.RequestError as exc:
                last_err = exc
                logger.warning(f"Network error querying {url}: {exc} (attempt {attempt + 1})")
                if attempt < max_retries:
                    await asyncio.sleep(0.5 * (attempt + 1))
                    continue
                raise ApiClientError(f"Network error connecting to {url}: {exc}") from exc

        if last_err:
            raise ApiClientError(f"API request failed after {max_retries + 1} attempts: {last_err}")
        raise ApiClientError(f"API request failed: {url}")

    async def get_text(
        self,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
    ) -> str:
        """Execute a GET request and return the raw text (e.g. for RSS or XML)."""
        try:
            client = await self._get_client()
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response.text
        except httpx.TimeoutException as exc:
            raise ApiTimeoutError(f"Request to {url} timed out after {self.config.timeout_seconds}s") from exc
        except httpx.HTTPStatusError as exc:
            raise ApiClientError(f"HTTP error {exc.response.status_code} from {url}", status_code=exc.response.status_code) from exc
        except httpx.RequestError as exc:
            raise ApiClientError(f"Network error connecting to {url}: {exc}") from exc

    async def close(self) -> None:
        """Close the underlying HTTP client session."""
        async with self._lock:
            if self._client is not None and not self._client.is_closed:
                await self._client.aclose()
                self._client = None
