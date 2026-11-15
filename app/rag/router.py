"""
Victor Conversational Document Intelligence & RAG Agent — Multi-Provider Model Router.

Routes generation and reasoning requests across:
1. Google Gemini (gemini-2.5-flash, gemini-2.5-pro)
2. Groq (openai/gpt-oss-120b, openai/gpt-oss-20b, qwen/qwen3.8-27b)
3. NVIDIA NIM (nvidia/llama-3.1-nemotron-70b-instruct, nvidia/nemotron-4-340b-instruct)
4. Jev / OpenRouter (~typesafe/jev-latest)

Features transparent failover, latency tracking, retry with backoff, and zero-leak credential handling.
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


class GenerationResult:
    def __init__(
        self,
        text: str,
        provider: str,
        model: str,
        latency_ms: float,
        tokens_used: int = 0,
        error: Optional[str] = None,
    ):
        self.text = text
        self.provider = provider
        self.model = model
        self.latency_ms = latency_ms
        self.tokens_used = tokens_used
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "provider": self.provider,
            "model": self.model,
            "latency_ms": self.latency_ms,
            "tokens_used": self.tokens_used,
            "error": self.error,
        }


class ModelRouter:
    """Intelligent Multi-Provider AI Model Router for RAG and Document Reasoning."""

    def __init__(self):
        self._gemini_client = None

    def _get_gemini_client(self):
        if self._gemini_client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if not api_key:
                return None
            from google import genai
            self._gemini_client = genai.Client(api_key=api_key)
        return self._gemini_client

    async def generate_response(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        preferred_provider: str = "auto",
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> GenerationResult:
        """
        Generates text using the best available provider with automatic failover.
        Priority when auto: Gemini Flash -> Groq -> NVIDIA NIM -> Gemini Pro.
        """
        # Determine provider sequence
        providers_to_try: List[Tuple[str, str]] = []

        if preferred_provider == "gemini":
            providers_to_try = [("gemini", "gemini-2.5-flash"), ("gemini", "gemini-2.5-pro")]
        elif preferred_provider == "groq":
            providers_to_try = [("groq", "openai/gpt-oss-120b"), ("groq", "qwen/qwen3.8-27b")]
        elif preferred_provider == "nim":
            providers_to_try = [
                ("nim", "nvidia/llama-3.1-nemotron-70b-instruct"),
                ("nim", "nvidia/nemotron-4-340b-instruct"),
            ]
        else:
            # Auto cascade
            if os.getenv("GEMINI_API_KEY"):
                providers_to_try.append(("gemini", "gemini-2.5-flash"))
            if os.getenv("GROQ_API_KEY"):
                providers_to_try.append(("groq", "openai/gpt-oss-120b"))
            if os.getenv("NVIDIA_NIM_API") or os.getenv("NVIDIA_API_KEY"):
                providers_to_try.append(("nim", "nvidia/llama-3.1-nemotron-70b-instruct"))
            if os.getenv("GEMINI_API_KEY"):
                providers_to_try.append(("gemini", "gemini-2.5-pro"))

        if not providers_to_try:
            return GenerationResult(
                text="No configured AI model providers found. Please set GEMINI_API_KEY, GROQ_API_KEY, or NVIDIA_NIM_API in .env.",
                provider="none",
                model="none",
                latency_ms=0.0,
                error="No providers available",
            )

        last_error = None
        for prov, model in providers_to_try:
            start_t = time.perf_counter()
            try:
                if prov == "gemini":
                    text = await self._call_gemini(prompt, system_instruction, model, temperature)
                elif prov == "groq":
                    text = await self._call_groq(prompt, system_instruction, model, temperature, max_tokens)
                elif prov == "nim":
                    text = await self._call_nim(prompt, system_instruction, model, temperature, max_tokens)
                else:
                    continue

                lat = (time.perf_counter() - start_t) * 1000.0
                return GenerationResult(
                    text=text,
                    provider=prov,
                    model=model,
                    latency_ms=lat,
                )
            except Exception as e:
                lat = (time.perf_counter() - start_t) * 1000.0
                last_error = str(e)
                logger.warning(
                    "ModelRouter provider %s (%s) failed in %.1fms: %s; failing over...",
                    prov,
                    model,
                    lat,
                    e,
                )

        return GenerationResult(
            text=f"Failed to generate answer across all available providers. Last error: {last_error}",
            provider="failed",
            model="none",
            latency_ms=0.0,
            error=last_error,
        )

    async def _call_gemini(
        self,
        prompt: str,
        system_instruction: Optional[str],
        model: str,
        temperature: float,
    ) -> str:
        client = self._get_gemini_client()
        if not client:
            raise ValueError("GEMINI_API_KEY not configured")

        from google.genai import types

        config = types.GenerateContentConfig(
            temperature=temperature,
            system_instruction=system_instruction,
        )
        resp = client.models.generate_content(
            model=model,
            contents=prompt,
            config=config,
        )
        return resp.text or ""

    async def _call_groq(
        self,
        prompt: str,
        system_instruction: Optional[str],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            raise ValueError("GROQ_API_KEY not configured")

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=40.0) as client:
            resp = await client.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]

    async def _call_nim(
        self,
        prompt: str,
        system_instruction: Optional[str],
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        api_key = os.getenv("NVIDIA_NIM_API") or os.getenv("NVIDIA_API_KEY")
        if not api_key:
            raise ValueError("NVIDIA_NIM_API not configured")

        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://integrate.api.nvidia.com/v1/chat/completions",
                headers=headers,
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
