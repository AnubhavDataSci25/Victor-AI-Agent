"""
Lightweight summarization utility for Victor's Current Affairs module.

Follows strict guidelines:
- Returns concise 1-3 sentence factual summaries.
- Reuses reliable concise source descriptions when available to prevent unnecessary AI calls.
- Optionally synthesizes multi-source clusters using the existing Groq model only when needed.
- Gracefully falls back to headline context if Groq is unavailable or times out.
"""

from __future__ import annotations

import html
import logging
import os
import re
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


def clean_html_snippet(raw_html: str) -> str:
    """Strips HTML tags and decodes common entities from feed snippets."""
    if not raw_html:
        return ""
    # Decode HTML entities like &nbsp;, &amp;, &#39;
    text = html.unescape(raw_html)
    # Strip HTML tags
    text = re.sub(r"<[^>]+>", " ", text)
    # Replace whitespace sequences
    text = re.sub(r"\s+", " ", text).strip()
    return text


class NewsSummarizer:
    """Provides fast factual summarization with optional Groq synthesis."""

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        groq_model: Optional[str] = None,
        groq_api_base: Optional[str] = None,
        timeout: float = 2.5,
    ) -> None:
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API") or os.getenv("GROQ_API_KEY") or ""
        self.groq_model = groq_model or os.getenv("GROQ_CODING_MODEL") or "openai/gpt-oss-20b"
        self.groq_api_base = groq_api_base or os.getenv("GROQ_API_BASE") or "https://api.groq.com/openai/v1"
        self.timeout = timeout

    async def summarize(
        self,
        headline: str,
        source: str = "",
        raw_snippet: str = "",
        cluster_headlines: Optional[list[str]] = None,
    ) -> str:
        """
        Produces a concise 1-3 sentence factual summary.
        
        Strategy:
        1. If clean concise description already exists (> 40 chars and informative), use it directly.
        2. If multiple cluster headlines exist or headline needs synthesis and Groq is available:
           ask Groq for a strict 2-sentence synthesis.
        3. Fallback: synthesize locally from clean headline and source.
        """
        is_cluster_list = "<ol>" in raw_snippet or "<li>" in raw_snippet
        clean_snippet = clean_html_snippet(raw_snippet)

        # Rule: don't summarize when a reliable concise source summary is already available
        # Avoid generic Google News wrapper text like "Comprehensive, up-to-date news coverage..."
        if (
            not is_cluster_list
            and clean_snippet
            and len(clean_snippet) > 40
            and "comprehensive, up-to-date news coverage" not in clean_snippet.lower()
        ):
            # Trim to 2 sentences max
            sentences = re.split(r"(?<=[.!?])\s+", clean_snippet)
            return " ".join(sentences[:2]).strip()

        # If cluster headlines exist and Groq is configured, attempt fast synthesis
        if self.groq_api_key and cluster_headlines and len(cluster_headlines) > 1:
            try:
                synthesized = await self._synthesize_with_groq(headline, source, cluster_headlines)
                if synthesized:
                    return synthesized
            except Exception as e:
                logger.debug(f"[NewsSummarizer] Groq synthesis fallback: {e}")

        # Direct factual fallback
        return self._format_direct_summary(headline, source, cluster_headlines)

    async def _synthesize_with_groq(
        self,
        headline: str,
        source: str,
        cluster_headlines: list[str],
    ) -> Optional[str]:
        """Calls Groq for a strict 1-2 sentence factual summary."""
        url = f"{self.groq_api_base.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.groq_api_key}",
            "Content-Type": "application/json",
        }
        
        context_items = "\n".join(f"- {h}" for h in cluster_headlines[:4])
        system_prompt = (
            "You are a factual news summarizer. "
            "Write a concise, neutral 1-2 sentence factual summary based strictly on the provided headlines. "
            "Do not speculate, do not express opinions, and do not add conversational pleasantries."
        )
        user_prompt = f"Primary Headline: {headline} (Source: {source})\nRelated Reporting:\n{context_items}"

        payload = {
            "model": self.groq_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "max_tokens": 80,
            "temperature": 0.1,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                content = data["choices"][0]["message"]["content"].strip()
                if content:
                    return content

        return None

    def _format_direct_summary(
        self,
        headline: str,
        source: str,
        cluster_headlines: Optional[list[str]] = None,
    ) -> str:
        """Constructs a factual 1-sentence summary directly from verified source reports."""
        if cluster_headlines and len(cluster_headlines) > 1:
            other_sources = [h for h in cluster_headlines if h != headline]
            if other_sources:
                return f"Reporting by {source} and key outlets on {headline}."
        return f"Reported by {source or 'national wires'}."
