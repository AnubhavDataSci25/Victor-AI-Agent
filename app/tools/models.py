"""
Shared structured models for the tool subsystem.

Every tool call, no matter what it does, produces a ToolResult. This is
the contract the rest of Victor (response generation, logging,
verification) is built against - never a raw exception, never a bare
string, never an untyped dict (spec section 32).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ToolCallRequest(BaseModel):
    """
    An abstract request to invoke a tool, produced by the brain layer
    (router / LLM) and consumed by the tool registry. This is the only
    thing the brain layer is allowed to hand to the execution layer -
    never a shell command, never a file path string interpolated
    directly into an OS call.
    """

    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    """Structured outcome of a tool execution."""

    success: bool
    tool: str
    message: str
    data: dict[str, Any] = Field(default_factory=dict)
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None
    error: str | None = None

    model_config = {"extra": "forbid"}