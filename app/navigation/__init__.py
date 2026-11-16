"""
Victor Dashboard Navigation Package.
Centralized navigation registry, controller, and event dispatch.
"""

from app.navigation.models import (
    NavigationAction,
    NavigationDestination,
    NavigationIntent,
    NavigationResult,
)
from app.navigation.registry import NavigationRegistry, get_navigation_registry
from app.navigation.controller import (
    DashboardNavigationController,
    get_navigation_controller,
    register_navigation_ui_listener,
    unregister_navigation_ui_listener,
)

__all__ = [
    "NavigationAction",
    "NavigationDestination",
    "NavigationIntent",
    "NavigationResult",
    "NavigationRegistry",
    "get_navigation_registry",
    "DashboardNavigationController",
    "get_navigation_controller",
    "register_navigation_ui_listener",
    "unregister_navigation_ui_listener",
]
