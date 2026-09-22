"""
Client for TypeSafe AI Jev model via OpenRouter API.

Implements non-autoregressive "System One" decision requests with:
- Strict timeouts (sub-second to few seconds).
- Typed question formatting: choice, noul, score.
- Structured answers parsing.
- Safe secret handling (never logs or leaks OPENROUTER_API_KEY).
- Seamless graceful fallback when API is unconfigured or unavailable.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
import httpx

from app.config import DecisionConfig, load_config
from app.decision.models import JevAnswer, JevDecisionResponse, JevQuestion

logger = logging.getLogger(__name__)


class JevClient:
    """Async HTTP client for TypeSafe Jev via OpenRouter."""

    def __init__(self, config: Optional[DecisionConfig] = None) -> None:
        self.config = config or load_config().decision
        self._http_client: Optional[httpx.AsyncClient] = None

    def is_available(self) -> bool:
        """True if OpenRouter API key is configured and decision layer is enabled."""
        return bool(self.config.enabled and self.config.openrouter_api_key and self.config.openrouter_api_key.strip())

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            headers = {
                "Authorization": f"Bearer {self.config.openrouter_api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/VictorAIAgent",
                "X-Title": "Victor-AI-Agent",
            }
            timeout = httpx.Timeout(self.config.timeout_seconds, connect=3.0)
            self._http_client = httpx.AsyncClient(headers=headers, timeout=timeout)
        return self._http_client

    async def decide(
        self,
        state: str,
        questions: Dict[str, JevQuestion],
    ) -> Optional[JevDecisionResponse]:
        """
        Send a decision request to Jev.
        Returns JevDecisionResponse on success, or None on failure/unavailability.
        """
        if not self.is_available():
            logger.debug("[JevClient] OpenRouter API key not configured; skipping Jev.")
            return None

        if not questions:
            return None

        endpoint = f"{self.config.openrouter_base_url.rstrip('/')}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.config.jev_model,
            "state": state,
            "questions": {
                qid: q.model_dump(exclude_none=True) for qid, q in questions.items()
            },
        }

        start_time = time.monotonic()
        try:
            client = await self._get_client()
            resp = await client.post(endpoint, json=payload)

            if resp.status_code != 200:
                logger.warning(
                    f"[JevClient] OpenRouter returned status {resp.status_code}: {resp.text[:150]}"
                )
                return None

            data = resp.json()
            latency_ms = round((time.monotonic() - start_time) * 1000, 2)

            answers_dict: Dict[str, JevAnswer] = {}
            raw_answers = data.get("answers", {})

            for qid, ans in raw_answers.items():
                if isinstance(ans, dict):
                    answers_dict[qid] = JevAnswer(
                        type=ans.get("type", "unknown"),
                        choice=ans.get("choice"),
                        confidence=ans.get("confidence"),
                        probabilities=ans.get("probabilities"),
                        noul=ans.get("noul"),
                        score=ans.get("score"),
                    )

            logger.info(
                f"[JevClient] Jev decision completed in {latency_ms}ms (model: {data.get('model', self.config.jev_model)})"
            )

            return JevDecisionResponse(
                answers=answers_dict,
                model=data.get("model", self.config.jev_model),
                provider=data.get("provider", "TypeSafe"),
                latency_ms=latency_ms,
                raw_payload=data,
            )

        except httpx.TimeoutException:
            logger.warning(f"[JevClient] Jev request timed out after {self.config.timeout_seconds}s. Falling back.")
            return None
        except httpx.HTTPError as exc:
            logger.warning(f"[JevClient] Network error querying Jev: {exc}. Falling back.")
            return None
        except Exception as exc:
            logger.error(f"[JevClient] Unexpected error in Jev decision: {exc}. Falling back.")
            return None

    async def close(self) -> None:
        """Close underlying HTTP client connections."""
        if self._http_client and not self._http_client.is_closed:
            await self._http_client.aclose()
            self._http_client = None
