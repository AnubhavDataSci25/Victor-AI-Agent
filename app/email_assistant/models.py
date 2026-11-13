"""
Victor Autonomous Email Assistant — Data Models.
"""

from __future__ import annotations

from enum import Enum
import hashlib
import json
import time
from typing import Any, Optional
import uuid
from pydantic import BaseModel, Field


class EmailProviderType(str, Enum):
    GMAIL = "gmail"
    OUTLOOK = "outlook"  # Reserved for future extensibility


class EmailAttachment(BaseModel):
    path: str
    filename: str
    mime_type: str
    size_bytes: int


class ContactCandidate(BaseModel):
    name: str
    email: str
    source: str = "gmail_contacts"


class EmailDraft(BaseModel):
    draft_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    provider: EmailProviderType = EmailProviderType.GMAIL
    provider_draft_id: Optional[str] = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str = ""
    body: str = ""
    tone: str = "professional"
    attachments: list[EmailAttachment] = Field(default_factory=list)
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    is_approved: bool = False
    approved_hash: Optional[str] = None
    status: str = "DRAFT"  # DRAFT, APPROVED, SENT, DISCARDED
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def compute_content_hash(self) -> str:
        """Deterministic SHA-256 hash of all material email fields for approval integrity."""
        payload = {
            "to": sorted(a.strip().lower() for a in self.to),
            "cc": sorted(a.strip().lower() for a in self.cc),
            "bcc": sorted(a.strip().lower() for a in self.bcc),
            "subject": self.subject.strip(),
            "body": self.body.strip(),
            "attachments": sorted(f"{att.path}:{att.size_bytes}" for att in self.attachments),
            "thread_id": self.thread_id or "",
            "in_reply_to": self.in_reply_to or "",
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def mark_approved(self) -> None:
        self.approved_hash = self.compute_content_hash()
        self.is_approved = True
        self.status = "APPROVED"
        self.updated_at = time.time()

    def invalidate_approval(self) -> None:
        self.is_approved = False
        self.approved_hash = None
        if self.status == "APPROVED":
            self.status = "DRAFT"
        self.updated_at = time.time()

    def is_approval_valid(self) -> bool:
        return (
            self.is_approved
            and self.approved_hash is not None
            and self.approved_hash == self.compute_content_hash()
        )


class EmailMessageSummary(BaseModel):
    message_id: str
    thread_id: str = ""
    sender: str = "(unknown)"
    to: str = ""
    subject: str = "(no subject)"
    date: str = ""
    snippet: str = ""
    body_preview: str = ""
    is_unread: bool = False
    labels: list[str] = Field(default_factory=list)
    rfc_message_id: Optional[str] = None
    references: Optional[str] = None


class ScheduledEmailStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    CANCELLED = "CANCELLED"
    NEEDS_REAPPROVAL = "NEEDS_REAPPROVAL"
    FAILED = "FAILED"


class ScheduledEmailRecord(BaseModel):
    schedule_id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    draft_id: str
    to: list[str]
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)
    subject: str
    body: str
    attachments: list[EmailAttachment] = Field(default_factory=list)
    thread_id: Optional[str] = None
    in_reply_to: Optional[str] = None
    references: Optional[str] = None
    approved_hash: str
    send_at: float
    status: ScheduledEmailStatus = ScheduledEmailStatus.PENDING
    sent_message_id: Optional[str] = None
    error_message: Optional[str] = None
    follow_up_at: Optional[float] = None
    follow_up_note: Optional[str] = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    def compute_current_hash(self) -> str:
        payload = {
            "to": sorted(a.strip().lower() for a in self.to),
            "cc": sorted(a.strip().lower() for a in self.cc),
            "bcc": sorted(a.strip().lower() for a in self.bcc),
            "subject": self.subject.strip(),
            "body": self.body.strip(),
            "attachments": sorted(f"{att.path}:{att.size_bytes}" for att in self.attachments),
            "thread_id": self.thread_id or "",
            "in_reply_to": self.in_reply_to or "",
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=True).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


class AutoSendPolicy(BaseModel):
    enabled: bool = False
    allowed_recipients: list[str] = Field(default_factory=list)
    allowed_purposes: list[str] = Field(default_factory=lambda: ["follow_up", "acknowledgement"])
    max_per_day: int = 5
    sent_today: int = 0
    last_reset_date: str = ""
