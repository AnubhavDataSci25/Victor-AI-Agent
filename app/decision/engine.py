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

from app.memory.sanitizer import MemorySanitizer
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
        Evaluate whether a piece of user speech contains a durable preference, fact, or instruction worth storing.
        Categorizes priority (high, medium, low) and determines whether user confirmation is required.
        """
        clean_text = (text or "").strip()
        if len(clean_text) < 4:
            return MemoryDecision(is_worthy=False, probability=0.0, priority="low")

        # 1. Zero credential leaks: Never store sensitive credentials, keys, or passwords
        is_sensitive, sec_reason = MemorySanitizer.is_sensitive(clean_text)
        if is_sensitive:
            logger.warning(f"Memory evaluation rejected sensitive content: {sec_reason}")
            return MemoryDecision(
                is_worthy=False,
                probability=0.0,
                priority="low",
                reasoning=f"Security policy rejection: {sec_reason}",
                source="sanitizer",
            )

        lower_text = clean_text.lower()

        # 2. Transient / fleeting action filter: Skip commands, system controls, quick questions, and news
        transient_starters = (
            "what is the time", "what's the time", "what time", "what is the date",
            "open youtube", "open google", "open chrome", "close the tab", "close tab",
            "search for", "how much is", "set volume", "mute", "unmute",
            "show notifications", "what is my battery", "how much battery",
            "get weather", "what's the weather", "current news", "get news",
        )
        if lower_text.startswith(transient_starters):
            return MemoryDecision(
                is_worthy=False,
                probability=0.0,
                priority="low",
                reasoning="Transient query or momentary action.",
                source="deterministic",
            )

        # 3. Explicit memory commands (Deterministic High-Priority)
        m_remember = re.search(r"\b(?:remember\s+that|remember|keep\s+in\s+mind(?:\s+that)?|note\s+that)\s+(.+)$", clean_text, re.I)
        if m_remember:
            statement = m_remember.group(1).strip().rstrip(".")
            words = re.findall(r"\w+", statement)
            suggested_key = "_".join(words[:4]).lower() if words else "user_note"
            return MemoryDecision(
                is_worthy=True,
                probability=0.98,
                category="user_fact",
                priority="high",
                suggested_key=suggested_key,
                extracted_fact=statement,
                should_ask_user=False,
                reasoning="Explicit user instruction to remember.",
                source="deterministic",
            )

        m_pref = re.search(r"\bmy\s+preferred\s+([a-zA-Z0-9_\s]{2,25})\s+is\s+(.+)$", clean_text, re.I)
        if m_pref:
            thing = m_pref.group(1).strip().lower().replace(" ", "_")
            val = m_pref.group(2).strip().rstrip(".")
            return MemoryDecision(
                is_worthy=True,
                probability=0.96,
                category="preference",
                priority="high",
                suggested_key=f"preferred_{thing}",
                extracted_fact=f"Preferred {thing.replace('_', ' ')} is {val}",
                should_ask_user=False,
                reasoning="Explicit statement of user preference.",
                source="deterministic",
            )

        m_fav = re.search(r"\bmy\s+favou?rite\s+([a-zA-Z0-9_\s]{2,25})\s+is\s+(.+)$", clean_text, re.I)
        if m_fav:
            thing = m_fav.group(1).strip().lower().replace(" ", "_")
            val = m_fav.group(2).strip().rstrip(".")
            return MemoryDecision(
                is_worthy=True,
                probability=0.95,
                category="preference",
                priority="high",
                suggested_key=f"favorite_{thing}",
                extracted_fact=f"Favorite {thing.replace('_', ' ')} is {val}",
                should_ask_user=False,
                reasoning="Explicit statement of favorite preference.",
                source="deterministic",
            )

        m_rule = re.search(r"\bi\s+(always|never)\s+(use|want|prefer|like|allow)\s+(.+)$", clean_text, re.I)
        if m_rule:
            adv = m_rule.group(1).lower()
            verb = m_rule.group(2).lower()
            detail = m_rule.group(3).strip().rstrip(".")
            words = re.findall(r"\w+", detail)
            suggested_key = f"rule_{adv}_{words[0].lower()}" if words else f"rule_{adv}"
            return MemoryDecision(
                is_worthy=True,
                probability=0.92,
                category="instruction",
                priority="high",
                suggested_key=suggested_key,
                extracted_fact=f"Always/Never rule: {adv} {verb} {detail}",
                should_ask_user=False,
                reasoning="Explicit behavioral constraint or preference.",
                source="deterministic",
            )

        # 4. Jev Advisory Evaluation (when available)
        if self.jev.is_available():
            questions = {
                "worthy": JevQuestion(
                    type=QuestionType.NOUL,
                    instructions="Does this user statement express a durable personal preference, enduring personal fact, family/identity detail, or long-term workflow instruction worth remembering across sessions?",
                ),
                "priority": JevQuestion(
                    type=QuestionType.CHOICE,
                    instructions="What is the priority level to preserve this in long-term memory?",
                    options=["high", "medium", "low"],
                ),
                "category": JevQuestion(
                    type=QuestionType.CHOICE,
                    instructions="What category best describes this information?",
                    options=["preference", "user_fact", "project", "instruction"],
                ),
                "ask_consent": JevQuestion(
                    type=QuestionType.NOUL,
                    instructions="Is this an implicit or personal detail where Victor should politely ask user confirmation ('Sir, should I remember that...?') before storing?",
                ),
            }
            resp = await self.jev.decide(
                state=f"User stated: '{clean_text}'",
                questions=questions,
            )
            if resp and "worthy" in resp.answers:
                prob = resp.answers["worthy"].noul or 0.0
                is_worthy = prob >= 0.65

                # Extract priority
                priority = "medium"
                if "priority" in resp.answers and resp.answers["priority"].choice:
                    priority = resp.answers["priority"].choice.lower()
                elif prob >= 0.85:
                    priority = "high"
                elif prob < 0.65:
                    priority = "low"

                # Extract category
                category = "preference"
                if "category" in resp.answers and resp.answers["category"].choice:
                    category = resp.answers["category"].choice.lower()

                # Extract user consent requirement
                ask_prob = 0.0
                if "ask_consent" in resp.answers:
                    ask_prob = resp.answers["ask_consent"].noul or 0.0
                should_ask = is_worthy and (ask_prob >= 0.60 or priority == "medium")

                # Build suggested key from keywords
                words = [w for w in re.findall(r"\w+", lower_text) if w not in ("i", "my", "the", "a", "an", "is", "am", "in", "to")]
                suggested_key = "_".join(words[:4]) if words else "user_fact"

                return MemoryDecision(
                    is_worthy=is_worthy,
                    probability=prob,
                    category=category,
                    priority=priority,
                    suggested_key=suggested_key,
                    extracted_fact=clean_text,
                    should_ask_user=should_ask,
                    reasoning=f"Jev evaluated worthiness (prob: {prob:.2f}, priority: {priority}).",
                    source="jev",
                )

        # 5. Deterministic Heuristic Fallback (when Jev is offline or for offline testing)
        # Enduring personal facts (family, residence, identity) -> High priority user_fact
        m_residence = re.search(r"\b(?:i\s+live\s+in|my\s+home\s+(?:city|town)\s+is|i\s+reside\s+in)\s+([a-zA-Z\s]{2,40})", clean_text, re.I)
        if m_residence:
            place = m_residence.group(1).strip().rstrip(".")
            return MemoryDecision(
                is_worthy=True,
                probability=0.90,
                category="user_fact",
                priority="high",
                suggested_key="home_location",
                extracted_fact=f"Lives in {place}",
                should_ask_user=False,
                reasoning="Core personal residence fact.",
                source="heuristic",
            )

        m_kin = re.search(r"\bmy\s+(wife|husband|partner|girlfriend|boyfriend|son|daughter|mother|father|brother|sister)\s+(?:is|is\s+named|named)\s+([a-zA-Z\s]{2,30})", clean_text, re.I)
        if m_kin:
            relation = m_kin.group(1).lower()
            name = m_kin.group(2).strip().rstrip(".")
            return MemoryDecision(
                is_worthy=True,
                probability=0.92,
                category="user_fact",
                priority="high",
                suggested_key=f"family_{relation}",
                extracted_fact=f"{relation.capitalize()} is {name}",
                should_ask_user=False,
                reasoning="User family / personal relationship fact.",
                source="heuristic",
            )

        # Active projects or pursuits -> Medium priority project, ask user consent
        m_proj = re.search(r"\b(?:i\s+am\s+(?:working\s+on|building|developing)|my\s+current\s+project\s+is)\s+([a-zA-Z0-9_\-\s]{2,50})", clean_text, re.I)
        if m_proj:
            proj = m_proj.group(1).strip().rstrip(".")
            words = re.findall(r"\w+", proj)
            key = f"project_{words[0].lower()}" if words else "current_project"
            return MemoryDecision(
                is_worthy=True,
                probability=0.82,
                category="project",
                priority="medium",
                suggested_key=key,
                extracted_fact=f"Working on {proj}",
                should_ask_user=True,
                reasoning="Active user project context; confirmation recommended.",
                source="heuristic",
            )

        # General preferences ("I like/love/prefer...") -> Medium priority preference, ask user consent
        m_like = re.search(r"\bi\s+(?:really\s+)?(?:prefer|like|love)\s+([a-zA-Z0-9_\-\s]{2,40})", clean_text, re.I)
        if m_like:
            fav = m_like.group(1).strip().rstrip(".")
            words = re.findall(r"\w+", fav)
            key = f"pref_{words[0].lower()}" if words else "user_preference"
            return MemoryDecision(
                is_worthy=True,
                probability=0.75,
                category="preference",
                priority="medium",
                suggested_key=key,
                extracted_fact=f"Prefers {fav}",
                should_ask_user=True,
                reasoning="General preference detected; confirmation recommended.",
                source="heuristic",
            )

        return MemoryDecision(is_worthy=False, probability=0.0, priority="low", source="deterministic_fallback")

