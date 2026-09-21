"""
Google Services Registry for Victor 2.0.

Provides a centralized discovery and registration hub for all Google services.
New Google services (Gmail, Drive, Docs, Sheets, etc.) can be registered here
without modifying existing modules.
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

from app.google_services.base import BaseGoogleService

logger = logging.getLogger(__name__)


class GoogleServiceRegistry:
    """Registry managing available Google services."""

    def __init__(self) -> None:
        self._services: Dict[str, BaseGoogleService] = {}

    def register(self, service: BaseGoogleService) -> None:
        """Register a Google service instance."""
        key = service.name.lower().strip()
        self._services[key] = service
        logger.info(f"Registered Google service: '{service.display_name}' (key='{key}')")

    def get(self, name: str) -> Optional[BaseGoogleService]:
        """Retrieve a registered Google service by key."""
        return self._services.get(name.lower().strip())

    def list_services(self) -> list[str]:
        """List all registered service names."""
        return list(self._services.keys())


# Global singleton registry instance
google_services = GoogleServiceRegistry()
