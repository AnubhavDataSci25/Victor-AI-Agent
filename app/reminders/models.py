"""
Data models and enumerations for Victor's Real-Time Date & Reminder System.
"""

from __future__ import annotations

import time as time_module
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ReminderStatus(str, Enum):
    PENDING = "pending"
    COMPLETED = "completed"
    POSTPONED = "postponed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ReminderCategory(str, Enum):
    PROFESSIONAL = "professional"  # Project deadlines, meetings, submissions, assignments, work tasks
    PERSONAL = "personal"          # Personal commitments, health, errands
    BIRTHDAY = "birthday"          # Annually recurring birthdays
    ANNIVERSARY = "anniversary"    # Annually recurring anniversaries
    OTHER = "other"                # Custom/extensible tasks


class ReminderRecurrence(str, Enum):
    NONE = "none"
    ANNUALLY = "annually"
    MONTHLY = "monthly"
    WEEKLY = "weekly"
    DAILY = "daily"


class ReminderMilestone(str, Enum):
    THREE_DAYS_BEFORE = "3_days_before"
    TWO_DAYS_BEFORE = "2_days_before"
    ONE_DAY_BEFORE = "1_day_before"
    SAME_DAY_MORNING = "same_day_morning"
    SAME_DAY_DUE = "same_day_due"
    OVERDUE = "overdue"


def generate_reminder_id() -> str:
    """Generate a compact, unique reminder ID."""
    return f"rem_{uuid.uuid4().hex[:10]}"


class ReminderRecord(BaseModel):
    """
    Structured persistent record for a task, deadline, or recurring event.
    """
    id: str = Field(default_factory=generate_reminder_id)
    work_task: str
    category: ReminderCategory = ReminderCategory.PROFESSIONAL
    date: str  # Format: YYYY-MM-DD
    time: str = "09:00:00"  # Format: HH:MM:SS or HH:MM
    timezone: str = "Asia/Kolkata"
    due_datetime: float  # Unix epoch timestamp in seconds
    status: ReminderStatus = ReminderStatus.PENDING
    recurrence: ReminderRecurrence = ReminderRecurrence.NONE
    notification_schedule: List[str] = Field(default_factory=list)
    delivered_milestones: List[str] = Field(default_factory=list)
    last_reminded_at: Optional[float] = None
    next_reminder_at: Optional[float] = None  # Next epoch timestamp to fire
    created_at: float = Field(default_factory=time_module.time)
    updated_at: float = Field(default_factory=time_module.time)
    is_archived: bool = False

    def is_recurring(self) -> bool:
        return self.recurrence != ReminderRecurrence.NONE or self.category in (
            ReminderCategory.BIRTHDAY,
            ReminderCategory.ANNIVERSARY,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "work_task": self.work_task,
            "category": self.category.value if isinstance(self.category, Enum) else self.category,
            "date": self.date,
            "time": self.time,
            "timezone": self.timezone,
            "due_datetime": self.due_datetime,
            "status": self.status.value if isinstance(self.status, Enum) else self.status,
            "recurrence": self.recurrence.value if isinstance(self.recurrence, Enum) else self.recurrence,
            "notification_schedule": self.notification_schedule,
            "delivered_milestones": self.delivered_milestones,
            "last_reminded_at": self.last_reminded_at,
            "next_reminder_at": self.next_reminder_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "is_archived": self.is_archived,
        }

    def format_display(self) -> str:
        """User-friendly summary of the reminder."""
        status_symbol = "⏳" if self.status == ReminderStatus.PENDING else ("✅" if self.status == ReminderStatus.COMPLETED else "⚠️")
        rec_tag = f" (Recurs: {self.recurrence.value})" if self.is_recurring() else ""
        return (
            f"[{self.id}] {status_symbol} {self.work_task} | Due: {self.date} at {self.time} "
            f"({self.timezone}) | Category: {self.category.value} | Status: {self.status.value}{rec_tag}"
        )
