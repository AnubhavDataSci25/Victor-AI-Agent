"""
Data models and schemas for Victor's Central Tool Gateway.

Defines GatewayRequest, GatewayResult, RiskLevel, and execution trace structures.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Dict, List, Optional
import uuid
from pydantic import BaseModel, Field


class RiskLevel(str, Enum):
    """Granular risk classification for tool actions."""
    READ_ONLY = "READ_ONLY"
    LOW_RISK = "LOW_RISK"
    MODERATE_RISK = "MODERATE_RISK"
    DESTRUCTIVE = "DESTRUCTIVE"
    EXTERNAL_SIDE_EFFECT = "EXTERNAL_SIDE_EFFECT"


class TraceStep(BaseModel):
    """A single milestone step within an execution trace."""
    phase: str
    timestamp: float = Field(default_factory=time.time)
    status: str = "ok"
    details: Dict[str, Any] = Field(default_factory=dict)


class ExecutionTrace(BaseModel):
    """Sanitized, end-to-end audit trace for a tool invocation."""
    trace_id: str = Field(default_factory=lambda: str(uuid.uuid4())[:8])
    tool_name: str
    start_time: float = Field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    permission_level: str = "SAFE"
    steps: List[TraceStep] = Field(default_factory=list)
    success: bool = True
    error: Optional[str] = None

    def add_step(self, phase: str, status: str = "ok", details: Optional[Dict[str, Any]] = None) -> None:
        """Record a milestone step in the trace."""
        self.steps.append(
            TraceStep(
                phase=phase,
                status=status,
                details=details or {},
            )
        )

    def complete(self, success: bool, error: Optional[str] = None) -> None:
        """Mark the trace as completed and calculate elapsed duration."""
        self.end_time = time.time()
        self.duration_ms = round((self.end_time - self.start_time) * 1000, 2)
        self.success = success
        self.error = error


class GatewayRequest(BaseModel):
    """Unified request envelope sent to the Central Tool Gateway."""
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    call_id: Optional[str] = None
    session_id: Optional[str] = None
    is_confirmed: bool = False
    client_context: Optional[Dict[str, Any]] = None


class GatewayResult(BaseModel):
    """Unified result envelope returned by the Central Tool Gateway."""
    tool_name: str
    success: bool
    result: Any = None
    error: Optional[str] = None
    permission_level: str = "SAFE"
    risk_level: RiskLevel = RiskLevel.READ_ONLY
    requires_confirmation: bool = False
    confirmation_prompt: Optional[str] = None
    verified: bool = True
    verification_details: Optional[str] = None
    duration_ms: float = 0.0
    trace_id: str = ""
