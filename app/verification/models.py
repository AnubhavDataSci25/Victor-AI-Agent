"""
Data models for Result Verification layer.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class VerificationStatus(str, Enum):
    """Categorized status of tool execution outcome."""
    SUCCESS = "SUCCESS"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    UNEXPECTED_RESULT = "UNEXPECTED_RESULT"


class VerificationResult(BaseModel):
    """Normalized result verification details."""
    verified: bool = True
    status: VerificationStatus = VerificationStatus.SUCCESS
    details: str = "Verified deterministically"
    is_deterministic: bool = True
    confidence: float = 1.0
    recommendation: Optional[str] = None
