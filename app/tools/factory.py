"""
Legacy Tool Factory (Victor 1.x compatibility shim).

Superseded by app.tools.tool_setup.build_tool_registry in Victor 2.0.
Maintained as a compatibility wrapper returning the populated ToolRegistry.
"""

from __future__ import annotations

from typing import Any
from app.config import VictorConfig
from app.tools.registry import ToolRegistry
from app.tools.tool_setup import build_tool_registry


def build_registry(
    config: VictorConfig | None = None,
    computer_driver: Any = None,
    browser_driver: Any = None,
    **kwargs: Any,
) -> ToolRegistry:
    """Builds and returns the Victor 2.0 ToolRegistry.
    
    Provided for backwards compatibility with any callers expecting
    factory.build_registry().
    """
    return build_tool_registry()