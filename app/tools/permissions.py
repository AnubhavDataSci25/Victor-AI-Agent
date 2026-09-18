"""
Permission engine - Layer 2 of Victor's two-layer security model
(spec section 11/12).

Layer 1 (authentication) proves *who* is talking to Victor. Layer 2
(this module) decides *what that session is allowed to do*, on a
per-tool basis, regardless of how confident or insistent the LLM's
tool call looks.

This is deterministic application code. The LLM never sees or
influences PermissionLevel assignment - each tool declares its own
level as a class attribute, and this engine is the only thing that
turns a level into an allow/deny decision (rule 20: the deterministic
safety layer is authoritative over the LLM).

Phase 2 scope: SAFE and LOW execute automatically. MEDIUM and HIGH are
correctly identified as requiring user confirmation, but Victor has no
confirmation UI or authenticated session yet (that's Phase 3+), so
they are deterministically denied with a clear reason rather than
silently executed or silently skipped. BLOCKED is always denied.
"""

from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    SAFE = "SAFE"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    BLOCKED = "BLOCKED"


class PermissionDecision(str, Enum):
    ALLOWED = "ALLOWED"
    REQUIRES_CONFIRMATION = "REQUIRES_CONFIRMATION"
    DENIED = "DENIED"


# Static, auditable mapping from permission level to default decision.
# This table - not the LLM, not the tool itself - is the source of truth.
_DEFAULT_DECISIONS: dict[PermissionLevel, PermissionDecision] = {
    PermissionLevel.SAFE: PermissionDecision.ALLOWED,
    PermissionLevel.LOW: PermissionDecision.ALLOWED,
    PermissionLevel.MEDIUM: PermissionDecision.REQUIRES_CONFIRMATION,
    PermissionLevel.HIGH: PermissionDecision.REQUIRES_CONFIRMATION,
    PermissionLevel.BLOCKED: PermissionDecision.DENIED,
}


class PermissionEngine:
    """
    Decides whether a tool call may proceed.

    `confirmed` lets a caller that already obtained explicit user
    confirmation (a future feature - Phase 3+ session/consent flow)
    pass that fact in. Until that flow exists, nothing in Victor sets
    confirmed=True, so REQUIRES_CONFIRMATION tools are effectively
    denied - which is the safe default, not a bug.
    """

    def decide(
        self, level: PermissionLevel, confirmed: bool = False
    ) -> PermissionDecision:
        decision = _DEFAULT_DECISIONS[level]
        if decision is PermissionDecision.REQUIRES_CONFIRMATION and confirmed:
            return PermissionDecision.ALLOWED
        return decision

    def explain(self, level: PermissionLevel, decision: PermissionDecision) -> str:
        if decision is PermissionDecision.ALLOWED:
            return f"Permission level {level.value} is auto-approved."
        if decision is PermissionDecision.DENIED and level is PermissionLevel.BLOCKED:
            return "This action is permanently blocked and cannot be executed."
        if decision is PermissionDecision.REQUIRES_CONFIRMATION:
            return (
                f"Permission level {level.value} requires explicit user "
                f"confirmation, which is not yet available in this build."
            )
        return f"Action denied for permission level {level.value}."