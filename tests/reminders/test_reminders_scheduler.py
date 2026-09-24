"""
Unit tests for Victor's ReminderScheduler:
Proactive background delivery, low-noise schedule, security lock policy,
idempotent milestone transitions, and wake event signaling.
"""

import asyncio
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock
import pytest

from app.reminders.datetime_utils import combine_date_time_to_epoch, parse_date_str, parse_time_str, resolve_timezone
from app.reminders.models import ReminderRecord, ReminderStatus
from app.reminders.scheduler import ReminderScheduler
from app.reminders.store import ReminderStore


@pytest.fixture
def temp_store(tmp_path: Path):
    db_file = tmp_path / "reminders_sched.db"
    return ReminderStore(db_path=str(db_file))


@pytest.mark.asyncio
async def test_scheduler_delivers_due_reminder(temp_store):
    store = temp_store
    mock_dispatcher = AsyncMock()

    scheduler = ReminderScheduler(
        store=store,
        notification_dispatcher=mock_dispatcher,
        session_auth_checker=lambda: True,
        max_idle_sleep=0.1,
    )

    # Create a reminder due today and set its next_reminder_at to right now
    now = time.time()
    rec = store.create_reminder(
        work_task="Project Presentation",
        date_str="today",
        time_str="23:59",
        category="professional",
    )
    # Manually adjust next_reminder_at to past/now to simulate due time
    with store._get_connection() as conn:
        conn.execute("UPDATE reminders SET next_reminder_at = ? WHERE id = ?", (now - 1.0, rec.id))
        conn.commit()

    # Process due reminders
    await scheduler._process_due_reminders(now)

    # Verify notification dispatched
    mock_dispatcher.assert_awaited_once()
    payload = mock_dispatcher.await_args.args[0]
    assert payload["type"] == "proactive_reminder"
    assert payload["reminder_id"] == rec.id
    assert payload["task"] == "Project Presentation"
    assert "Sir, your task" in payload["message"]

    # Verify last delivered context
    assert scheduler.last_delivered_reminder_id == rec.id
    context_rec = scheduler.get_last_delivered_reminder()
    assert context_rec is not None
    assert context_rec.id == rec.id


@pytest.mark.asyncio
async def test_scheduler_respects_lock_security_and_flushes_on_unlock(temp_store):
    """Zero-leak policy: Reminders are held while locked, delivered once unlocked."""
    store = temp_store
    mock_dispatcher = AsyncMock()

    is_unlocked = False

    scheduler = ReminderScheduler(
        store=store,
        notification_dispatcher=mock_dispatcher,
        session_auth_checker=lambda: is_unlocked,
        max_idle_sleep=0.1,
    )

    now = time.time()
    rec = store.create_reminder(
        work_task="Confidential Board Meeting",
        date_str="today",
        time_str="14:00",
        category="professional",
    )
    with store._get_connection() as conn:
        conn.execute("UPDATE reminders SET next_reminder_at = ? WHERE id = ?", (now - 1.0, rec.id))
        conn.commit()

    # 1. While locked: must NOT dispatch private task
    await scheduler._process_due_reminders(now)
    assert mock_dispatcher.await_count == 0
    assert len(scheduler._pending_auth_queue) == 1

    # 2. When unlocked: flush queue and deliver
    is_unlocked = True
    await scheduler._flush_pending_auth_queue()
    assert mock_dispatcher.await_count == 1
    payload = mock_dispatcher.await_args.args[0]
    assert payload["task"] == "Confidential Board Meeting"


@pytest.mark.asyncio
async def test_idempotent_delivery_prevents_duplicate_notifications(temp_store):
    store = temp_store
    mock_dispatcher = AsyncMock()

    scheduler = ReminderScheduler(
        store=store,
        notification_dispatcher=mock_dispatcher,
        session_auth_checker=lambda: True,
        max_idle_sleep=0.1,
    )

    now = time.time()
    rec = store.create_reminder(
        work_task="Gym Workout",
        date_str="tomorrow",
        time_str="08:00 AM",
        category="personal",
    )
    with store._get_connection() as conn:
        conn.execute("UPDATE reminders SET next_reminder_at = ? WHERE id = ?", (now - 1.0, rec.id))
        conn.commit()

    # Deliver once
    await scheduler._process_due_reminders(now)
    assert mock_dispatcher.await_count == 1

    # Immediate second pass at same timestamp should NOT re-deliver
    await scheduler._process_due_reminders(now)
    assert mock_dispatcher.await_count == 1


@pytest.mark.asyncio
async def test_scheduler_lifecycle_start_and_stop(temp_store):
    store = temp_store
    scheduler = ReminderScheduler(store=store, max_idle_sleep=0.05)

    await scheduler.start()
    assert scheduler._running is True
    assert scheduler._task is not None

    # Trigger wake event
    scheduler.notify_store_updated()
    await asyncio.sleep(0.08)

    await scheduler.stop()
    assert scheduler._running is False
    assert scheduler._task is None
