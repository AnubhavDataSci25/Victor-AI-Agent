"""
Victor Autonomous Email Assistant — Abstract Provider Interface.

Allows Gmail to be the primary provider while keeping VictorCore and all
email tools decoupled so Outlook/Graph API can be added later cleanly.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.email_assistant.models import (
    ContactCandidate,
    EmailDraft,
    EmailMessageSummary,
)


class EmailProvider(ABC):
    """Abstract email provider contract."""

    @abstractmethod
    async def is_connected(self) -> bool:
        """Return True if valid credentials are available."""

    @abstractmethod
    async def get_status(self) -> dict[str, Any]:
        """Return non-sensitive connection status and account email."""

    @abstractmethod
    async def disconnect(self) -> dict[str, Any]:
        """Revoke and remove stored credentials."""

    @abstractmethod
    async def search_contacts(self, query: str, limit: int = 5) -> list[ContactCandidate]:
        """Search authorized contacts matching a name or email fragment."""

    @abstractmethod
    async def search_messages(
        self,
        query: str = "",
        max_results: int = 10,
        unread_only: bool = False,
    ) -> list[EmailMessageSummary]:
        """Search inbox messages with minimal metadata and body preview."""

    @abstractmethod
    async def get_message(self, message_id: str) -> Optional[EmailMessageSummary]:
        """Retrieve a specific message by provider ID."""

    @abstractmethod
    async def save_draft(self, draft: EmailDraft) -> str:
        """Create or update a draft on the provider; return provider_draft_id."""

    @abstractmethod
    async def send_email(self, draft: EmailDraft) -> dict[str, Any]:
        """Send an approved EmailDraft and verify delivery; return message_id & status."""
