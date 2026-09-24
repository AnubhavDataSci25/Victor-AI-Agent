"""
Data models and question schemas for TypeSafe Jev Decision Layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class QuestionType(str, Enum):
    CHOICE = "choice"
    NOUL = "noul"
    SCORE = "score"


class JevQuestion(BaseModel):
    """Specification for a single question sent to Jev."""
    type: QuestionType
    instructions: str
    criteria: Optional[Dict[str, str]] = None
    options: Optional[List[str]] = None
    scale: Optional[Dict[str, Any]] = None


class JevAnswer(BaseModel):
    """Normalized answer returned by Jev for a single question."""
    type: str
    choice: Optional[str] = None
    confidence: Optional[float] = None
    probabilities: Optional[Dict[str, float]] = None
    noul: Optional[float] = None
    score: Optional[float] = None


class JevDecisionResponse(BaseModel):
    """Complete structured response envelope returned by Jev."""
    answers: Dict[str, JevAnswer] = Field(default_factory=dict)
    model: str = ""
    provider: str = "TypeSafe"
    latency_ms: float = 0.0
    raw_payload: Optional[Dict[str, Any]] = None


class IntentDecision(BaseModel):
    """Decision output for intent classification."""
    intent: str
    confidence: float = 1.0
    candidate_tools: List[str] = Field(default_factory=list)
    source: str = "deterministic"  # "deterministic" or "jev"


class RiskDecision(BaseModel):
    """Decision output for risk assessment."""
    risk_level: str = "READ_ONLY"
    requires_confirmation: bool = False
    confidence: float = 1.0
    reasoning: str = ""
    source: str = "deterministic"


class MemoryDecision(BaseModel):
    """Decision output for memory suitability evaluation."""
    is_worthy: bool = False
    probability: float = 0.0
    category: str = "preference"
    priority: str = "low"  # "high", "medium", "low"
    suggested_key: str = ""
    extracted_fact: str = ""
    should_ask_user: bool = False
    reasoning: str = ""
    source: str = "deterministic"

