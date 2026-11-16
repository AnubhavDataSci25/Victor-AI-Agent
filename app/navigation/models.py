"""
Victor Dashboard Navigation — Data Models.
Defines schemas for navigation destinations, intents, actions, and results.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class NavigationAction(str, Enum):
    OPEN = "open"
    SWITCH = "switch"
    BACK = "back"
    HOME = "home"
    CLOSE = "close"


class NavigationDestination(BaseModel):
    """Metadata describing a registered dashboard destination."""
    id: str = Field(..., description="Canonical destination ID (e.g., 'dashboard', 'finance', 'documents', 'memory')")
    title: str = Field(..., description="Human-readable title (e.g., 'Memory & Context')")
    description: str = Field(..., description="Description of the section")
    view_type: str = Field(..., description="'main_view', 'dedicated_view', or 'drawer_module'")
    subtabs: Dict[str, str] = Field(default_factory=dict, description="Map of subtab ID to human-readable subtab name")
    aliases: List[str] = Field(default_factory=list, description="List of natural language aliases and keywords")


class NavigationIntent(BaseModel):
    """Structured navigation intent extracted from user command or tool invocation."""
    intent: str = Field(default="dashboard_navigation")
    destination: str = Field(..., description="Target destination ID or 'back'/'home'")
    tab: Optional[str] = Field(default=None, description="Optional subtab within the destination")
    action: NavigationAction = Field(default=NavigationAction.OPEN, description="Navigation action")
    source: str = Field(default="voice", description="Source of navigation ('voice', 'text', 'ui', 'tool')")
    filters: Dict[str, Any] = Field(default_factory=dict, description="Optional contextual filters")


class NavigationResult(BaseModel):
    """Execution outcome returned by the Dashboard Navigation Controller."""
    success: bool
    destination: str
    tab: Optional[str] = None
    action: str = "open"
    previous_destination: Optional[str] = None
    spoken_feedback: str
    is_already_active: bool = False
    error: Optional[str] = None
