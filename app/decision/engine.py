"""
Decision Engine for Victor.

Unites high-speed deterministic heuristic routing with TypeSafe Jev structured decisions.
Provides:
- Intent classification and tool domain routing.
- Advisory risk classification.
- Action confirmation recommendations.
- Memory worthiness evaluation.
- Coding task outcome verification.
- 100% resilient fallback when Jev / OpenRouter is offline or unconfigured.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.decision.jev_client import JevClient
from app.decision.models import (
    IntentDecision,
    JevQuestion,
    MemoryDecision,
    QuestionType,
    RiskDecision,
)

logger = logging.getLogger(__name__)

# Fast-path keyword heuristics to avoid LLM calls on obvious commands
FAST_PATH_RULES: List[Tuple[re.Pattern, str, List[str]]] = [
    (re.compile(r"\b(weather|forecast|temperature|rain|cloudy)\b", re.I), "public_api", ["api_get_weather"]),
    (re.compile(r"\b(stock|ticker|shares?|sensex|nifty|nasdaq)\b", re.I), "public_api", ["api_get_stock_price"]),
    (re.compile(r"\b(forex|exchange rate|convert.*to|currency)\b", re.I), "public_api", ["api_get_forex_rate"]),
    (re.compile(r"\b(crypto|bitcoin|btc|ethereum|eth|solana|sol|doge)\b", re.I), "public_api", ["api_get_crypto_price"]),
    (re.compile(r"\b(news|headlines|breaking news)\b", re.I), "public_api", ["api_get_news_headlines", "current_affairs_get_updates"]),
    (re.compile(r"\b(public ip|my ip|isp|ip address)\b", re.I), "public_api", ["api_get_public_ip_info"]),
    (re.compile(r"\b(holiday|holidays|public holiday)\b", re.I), "public_api", ["api_get_public_holidays"]),
    (re.compile(r"\b(volume|mute|unmute|sound)\b", re.I), "system_control", ["system_adjust_volume", "system_get_volume"]),
    (re.compile(r"\b(brightness|screen light)\b", re.I), "system_control", ["system_adjust_brightness", "system_get_brightness"]),
    (re.compile(r"\b(battery|charge|power status)\b", re.I), "system_control", ["system_get_battery"]),
    (re.compile(r"\b(bluetooth)\b", re.I), "system_control", ["system_get_bluetooth"]),
    (re.compile(r"\b(wifi|network status|internet connection)\b", re.I), "system_control", ["system_get_network"]),
    (re.compile(r"\b(screenshot|capture screen|screen shot)\b", re.I), "computer_control", ["computer_take_screenshot"]),
    (re.compile(r"\b(lock victor|lock yourself|lock session)\b", re.I), "system_control", ["lock_victor"]),
    (re.compile(r"\b(keep note|take a note|create a note)\b", re.I), "google_services", ["google_keep_create_note"]),
    (re.compile(r"\b(meet|meeting link|launch meet)\b", re.I), "google_services", ["google_meet_create"]),
    (re.compile(r"\b(calendar|schedule event)\b", re.I), "google_services", ["google_calendar_create_event"]),
    (re.compile(r"\b(call\s+[A-Za-z]+|dial)\b", re.I), "phone_companion", ["phone_resolve_contact", "phone_initiate_call"]),
]


class DecisionEngine:
    """Combines deterministic routing with Jev structured decisions."""

    def __init__(self, jev_client: Optional[JevClient] = None) -> None:
        self.jev = jev_client or JevClient()

    async def route_intent(self, user_input: str) -> IntentDecision:
        """
        Determine which system domain and candidate tools should handle the user's input.
        Fast-path heuristic runs first; Jev handles ambiguous requests.
        """
        clean_input = (user_input or "").strip()
        if not clean_input:
            return IntentDecision(intent="general_conversation", confidence=1.0, source="deterministic")

        # 1. Fast-Path Deterministic Evaluation
        for pattern, domain, tools in FAST_PATH_RULES:
            if pattern.search(clean_input):
                logger.debug(f"[DecisionEngine] Fast-path matched domain: '{domain}'")
                return IntentDecision(
                    intent=domain,
                    confidence=1.0,
                    candidate_tools=tools,
                    source="deterministic",
                )

        # 2. Bounded Jev Decision via OpenRouter
        if self.jev.is_available():
            question = JevQuestion(
                type=QuestionType.CHOICE,
                instructions="Which system domain best matches the user's primary intent?",
                criteria={
                    "system_control": "Controlling OS volume, brightness, battery, locking, settings",
                    "browser_web": "Web searching, opening links, visiting websites",
                    "public_api": "Checking live weather, stocks, forex rates, crypto, public IP, holidays, news",
                    "google_services": "Managing notes in Google Keep, calendar events, Google Meet",
                    "computer_coding": "VS Code, coding tasks, terminal commands, workspace management",
                    "phone_companion": "Phone calls, SMS/WhatsApp notifications, mobile YouTube",
                    "memory_recall": "Remembering or recalling user personal preferences and project facts",
                    "general_conversation": "Conversational dialogue, general knowledge, greetings",
                },
            )

            jev_resp = await self.jev.decide(
                state=f"User says: '{clean_input}'",
                questions={"intent": question},
            )

            if jev_resp and "intent" in jev_resp.answers:
                ans = jev_resp.answers["intent"]
                chosen = ans.choice or "general_conversation"
                conf = ans.confidence if ans.confidence is not None else 0.85
                return IntentDecision(
                    intent=chosen,
                    confidence=conf,
                    source="jev",
                )

        # 3. Default fallback
        return IntentDecision(
            intent="general_conversation",
            confidence=0.5,
            source="deterministic_fallback",
        )

    async def assess_risk(self, tool_name: str, args: Dict[str, Any]) -> RiskDecision:
        """
        Assess risk of an action.
        Deterministic baseline is authoritative; Jev provides advisory refinement.
        """
        name_lower = tool_name.lower()

        # Deterministic baseline
        if any(k in name_lower for k in ("delete", "remove", "unlink", "unpair")):
            return RiskDecision(
                risk_level="DESTRUCTIVE",
                requires_confirmation=True,
                confidence=1.0,
                reasoning="Operation performs permanent resource deletion or unpairing.",
                source="deterministic",
            )

        if any(k in name_lower for k in ("move", "rename", "call", "schedule", "run_command")):
            return RiskDecision(
                risk_level="MODERATE_RISK",
                requires_confirmation=False,
                confidence=0.9,
                reasoning="Operation has external or filesystem side-effects.",
                source="deterministic",
            )

        # Jev advisory evaluation for ambiguous dynamic actions
        if self.jev.is_available() and any(k in name_lower for k in ("coding", "computer", "file")):
            question = JevQuestion(
                type=QuestionType.NOUL,
                instructions="Is this operation irreversible, destructive, or likely to cause unexpected data loss?",
            )
            resp = await self.jev.decide(
                state=f"Tool: {tool_name}, Arguments: {args}",
                questions={"is_destructive": question},
            )
            if resp and "is_destructive" in resp.answers:
                noul_prob = resp.answers["is_destructive"].noul or 0.0
                if noul_prob > 0.65:
                    return RiskDecision(
                        risk_level="DESTRUCTIVE",
                        requires_confirmation=True,
                        confidence=noul_prob,
                        reasoning=f"Jev classified action as high-risk (prob: {noul_prob:.2f}).",
                        source="jev",
                    )

        return RiskDecision(
            risk_level="READ_ONLY",
            requires_confirmation=False,
            confidence=1.0,
            reasoning="Safe read-only or low-impact operation.",
            source="deterministic",
        )

    async def evaluate_memory_worthiness(self, text: str) -> MemoryDecision:
        """
        Evaluate whether a piece of user speech contains a durable preference or fact worth storing.
        """
        clean_text = (text or "").strip()
        if len(clean_text) < 5:
            return MemoryDecision(is_worthy=False, probability=0.0)

        # Deterministic keywords
        if any(k in clean_text.lower() for k in ("remember that", "my preferred", "i prefer", "always use", "never use")):
            return MemoryDecision(is_worthy=True, probability=0.95, source="deterministic")

        if self.jev.is_available():
            question = JevQuestion(
                type=QuestionType.NOUL,
                instructions="Does this user statement express a durable personal preference, enduring fact, or long-term instruction?",
            )
            resp = await self.jev.decide(
                state=f"User stated: '{clean_text}'",
                questions={"worthy": question},
            )
            if resp and "worthy" in resp.answers:
                prob = resp.answers["worthy"].noul or 0.0
                return MemoryDecision(
                    is_worthy=prob >= 0.70,
                    probability=prob,
                    source="jev",
                )

        return MemoryDecision(is_worthy=False, probability=0.0, source="deterministic_fallback")
