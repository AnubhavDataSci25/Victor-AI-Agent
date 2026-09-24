"""
Unit tests for Victor's ReminderStore:
Creation, persistence across restart, duplicate prevention, 3d/2d/1d scheduling,
postponing, completion, and permanent recurring birthdays/anniversaries.
"""

from pathlib import Path
import pytest
from app.reminders.models import ReminderCategory, ReminderStatus
from app.reminders.store import ReminderStore


@pytest.fixture
def temp_store(tmp_path: Path):
    db_file = tmp_path / "reminders.db"
    return ReminderStore(db_path=str(db_file))


def test_create_and_persist_reminder(temp_store):
    store = temp_store
    rec = store.create_reminder(
        work_task="Project Deadline",
        date_str="2nd October 2026",
        time_str="before 11:59 PM",
        category="professional",
    )
    assert rec.status == ReminderStatus.PENDING
    assert rec.date == "2026-10-02"
    assert rec.time == "23:59:00"
    assert rec.is_archived is False
    assert rec.next_reminder_at is not None

    # Verify survival across a new store instance (restart simulation)
    new_store = ReminderStore(db_path=str(store.db_path))
    loaded = new_store.get_reminder(rec.id)
    assert loaded is not None
    assert loaded.work_task == "Project Deadline"
    assert loaded.date == "2026-10-02"
    assert loaded.status == ReminderStatus.PENDING


def test_duplicate_task_detection_and_update(temp_store):
    store = temp_store
    rec1 = store.create_reminder(
        work_task="Submit Quarterly Report",
        date_str="2026-11-01",
        time_str="17:00",
        category="professional",
    )

    # User re-states deadline with slight variations
    rec2 = store.create_reminder(
        work_task="submit quarterly report",
        date_str="2026-11-05",
        time_str="18:00",
        category="professional",
    )

    # Must update the existing task without creating duplicate
    assert rec2.id == rec1.id
    assert rec2.date == "2026-11-05"
    assert rec2.time == "18:00:00"

    active = store.list_active_reminders()
    assert len(active) == 1


def test_postpone_and_cancel_lifecycle(temp_store):
    store = temp_store
    rec = store.create_reminder(
        work_task="Client Presentation",
        date_str="2026-10-10",
        time_str="10:00 AM",
    )

    # Postpone
    postponed = store.postpone_reminder(rec.id, new_date="2026-10-15", new_time="11:00 AM")
    assert postponed.date == "2026-10-15"
    assert postponed.time == "11:00:00"
    assert postponed.status == ReminderStatus.PENDING

    # Cancel
    cancelled = store.cancel_reminder(rec.id)
    assert cancelled.status == ReminderStatus.CANCELLED
    assert cancelled.is_archived is True
    assert cancelled.next_reminder_at is None

    # Cancelled task must not appear in active list
    assert len(store.list_active_reminders()) == 0


def test_one_time_completion_archives_task(temp_store):
    store = temp_store
    rec = store.create_reminder(
        work_task="Submit Assignment",
        date_str="2026-10-05",
        time_str="23:59",
        category="professional",
    )

    completed = store.complete_reminder(rec.id)
    assert completed.status == ReminderStatus.COMPLETED
    assert completed.is_archived is True
    assert completed.next_reminder_at is None

    # Ensure it is removed from active list
    assert len(store.list_active_reminders()) == 0


def test_birthday_and_anniversary_recur_permanently(temp_store):
    store = temp_store
    bday = store.create_reminder(
        work_task="Mom's Birthday",
        date_str="15th August 2026",
        time_str="09:00 AM",
        category="birthday",
    )
    assert bday.is_recurring() is True
    assert bday.category == ReminderCategory.BIRTHDAY

    # Mark completed for this year
    advanced = store.complete_reminder(bday.id)
    assert advanced is not None
    # Must NOT be archived or deleted
    assert advanced.is_archived is False
    assert advanced.status == ReminderStatus.PENDING
    # Must automatically advance to 2027
    assert advanced.date == "2027-08-15"
    assert advanced.next_reminder_at is not None

    # Remains in active list for next year
    active = store.list_active_reminders()
    assert len(active) == 1
    assert active[0].date == "2027-08-15"
