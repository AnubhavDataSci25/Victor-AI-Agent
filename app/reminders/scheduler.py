"""
Lightweight, Event-Driven Background Scheduler for Victor's Real-Time Reminder System.
Zero LLM calls for routine delivery, minimal CPU/RAM usage, restart-safe recovery,
idempotent delivery, and strict adherence to security and authentication policies.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from app.reminders.datetime_utils import (
    format_friendly_reminder_message,
    resolve_timezone,
)
from app.reminders.models import ReminderRecord, ReminderStatus
from app.reminders.store import ReminderStore

logger = logging.getLogger(__name__)


class ReminderScheduler:
    """
    Background worker that sleeps until the earliest pending reminder is due,
    waking early when new reminders are scheduled or updated via asyncio.Event.
    """

    def __init__(
        self,
        store: Optional[ReminderStore] = None,
        notification_dispatcher: Optional[Callable[[Dict[str, Any]], Any]] = None,
        session_auth_checker: Optional[Callable[[], bool]] = None,
        max_idle_sleep: float = 60.0,
    ) -> None:
        self.store = store or ReminderStore()
        self.notification_dispatcher = notification_dispatcher
        self.session_auth_checker = session_auth_checker
        self.max_idle_sleep = max_idle_sleep

        self._task: Optional[asyncio.Task] = None
        self._running: bool = False
        self._wake_event: asyncio.Event = asyncio.Event()

        # Track the ID of the last proactive reminder delivered to the active session
        self.last_delivered_reminder_id: Optional[str] = None
        self.last_delivered_at: Optional[float] = None

        # Queue of reminders that triggered while session was locked / unauthenticated
        self._pending_auth_queue: List[ReminderRecord] = []

    def set_notification_dispatcher(self, dispatcher: Callable[[Dict[str, Any]], Any]) -> None:
        """Sets or updates the notification callback (e.g. WebSocket or TTS output)."""
        self.notification_dispatcher = dispatcher

    def set_session_auth_checker(self, checker: Callable[[], bool]) -> None:
        """Sets the callback to check if the current user session is unlocked & authenticated."""
        self.session_auth_checker = checker

    def notify_store_updated(self) -> None:
        """Signal the scheduler to wake up immediately and recalculate next sleep."""
        self._wake_event.set()

    async def start(self) -> None:
        """Start the background scheduler loop."""
        if self._running:
            return
        self._running = True
        self._wake_event.clear()
        self._task = asyncio.create_task(self._scheduler_loop(), name="victor-reminder-scheduler")
        logger.info("Victor Real-Time Reminder Scheduler started.")

    async def stop(self) -> None:
        """Stop the background scheduler loop gracefully."""
        self._running = False
        self._wake_event.set()
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self._task = None
        logger.info("Victor Real-Time Reminder Scheduler stopped.")

    async def _scheduler_loop(self) -> None:
        """Core event-driven loop. Sleeps until next reminder or wake event."""
        while self._running:
            try:
                now = time.time()

                # 1. Process any due reminders
                await self._process_due_reminders(now)

                # 2. Check pending auth queue if session became authenticated
                await self._flush_pending_auth_queue()

                # 3. Calculate sleep duration until earliest pending reminder
                earliest_next = self.store.get_earliest_next_reminder_time()
                if earliest_next is not None:
                    time_until = max(0.0, earliest_next - time.time())
                    sleep_duration = min(time_until, self.max_idle_sleep)
                else:
                    sleep_duration = self.max_idle_sleep

                # 4. Sleep or wait for wake_event signal
                try:
                    await asyncio.wait_for(self._wake_event.wait(), timeout=max(0.1, sleep_duration))
                    self._wake_event.clear()
                except asyncio.TimeoutError:
                    pass

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ReminderScheduler] Unexpected loop error: {e}", exc_info=True)
                await asyncio.sleep(5.0)

    async def _process_due_reminders(self, now: float) -> None:
        """Fetches and delivers all reminders whose scheduled time <= now."""
        due_reminders = self.store.get_due_reminders(now)
        for rec in due_reminders:
            try:
                await self._deliver_reminder(rec, now)
            except Exception as e:
                logger.error(f"[ReminderScheduler] Error delivering reminder {rec.id}: {e}")

    async def _deliver_reminder(self, rec: ReminderRecord, now: float) -> None:
        """
        Idempotently delivers a reminder milestone and advances to the next milestone.
        Adheres to Victor's zero-leak security policy: if session is locked/unauthenticated,
        holds private reminder until user unlocks.
        """
        # Determine which milestone is firing
        tz = resolve_timezone(rec.timezone)
        due_dt = datetime.fromtimestamp(rec.due_datetime, tz=tz)
        is_overdue = now > rec.due_datetime

        milestone = "same_day_due"
        if is_overdue:
            milestone = "overdue_1_day"
        else:
            diff_days = (due_dt.date() - datetime.fromtimestamp(now, tz=tz).date()).days
            if diff_days >= 3:
                milestone = "3_days_before"
            elif diff_days == 2:
                milestone = "2_days_before"
            elif diff_days == 1:
                milestone = "1_day_before"
            elif due_dt.hour >= 10 and datetime.fromtimestamp(now, tz=tz).hour < 10:
                milestone = "same_day_morning"
            else:
                milestone = "same_day_due"

        # Check authentication status
        is_auth = True
        if self.session_auth_checker is not None:
            try:
                is_auth = self.session_auth_checker()
            except Exception:
                is_auth = False

        if not is_auth:
            # Privacy protection: Do not announce or display private reminder on locked screen!
            # Queue for catch-up once authenticated
            if rec.id not in [q.id for q in self._pending_auth_queue]:
                self._pending_auth_queue.append(rec)
                logger.info(f"[ReminderScheduler] Session locked. Queued reminder '{rec.work_task}' until unlock.")
            return

        # Atomically mark milestone delivered in persistent store
        self.store.mark_milestone_delivered(rec.id, milestone, now)

        # Track last delivered reminder for conversational context ("Completed", "Postpone", etc.)
        self.last_delivered_reminder_id = rec.id
        self.last_delivered_at = now

        friendly_msg = format_friendly_reminder_message(
            task=rec.work_task,
            date_str=rec.date,
            time_str=rec.time,
            is_overdue=is_overdue,
            milestone=milestone,
        )

        payload = {
            "type": "proactive_reminder",
            "reminder_id": rec.id,
            "task": rec.work_task,
            "category": rec.category.value,
            "date": rec.date,
            "time": rec.time,
            "timezone": rec.timezone,
            "is_overdue": is_overdue,
            "milestone": milestone,
            "message": friendly_msg,
        }

        logger.info(f"[ReminderScheduler] Proactive reminder dispatched: [{rec.category.value}] '{rec.work_task}'")

        if self.notification_dispatcher:
            try:
                res = self.notification_dispatcher(payload)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"[ReminderScheduler] Notification dispatcher failed: {e}")

    async def _flush_pending_auth_queue(self) -> None:
        """Delivers any reminders that were queued while Victor was locked, once unlocked."""
        if not self._pending_auth_queue:
            return

        is_auth = True
        if self.session_auth_checker is not None:
            try:
                is_auth = self.session_auth_checker()
            except Exception:
                is_auth = False

        if is_auth and self._pending_auth_queue:
            queue = list(self._pending_auth_queue)
            self._pending_auth_queue.clear()
            now = time.time()
            for rec in queue:
                await self._deliver_reminder(rec, now)

    def get_last_delivered_reminder(self) -> Optional[ReminderRecord]:
        """Returns the most recent proactively reminded record if delivered within last 15 minutes."""
        if not self.last_delivered_reminder_id or not self.last_delivered_at:
            return None
        if (time.time() - self.last_delivered_at) > 900.0:  # 15 minutes context window
            return None
        return self.store.get_reminder(self.last_delivered_reminder_id)

    def clear_last_delivered_context(self) -> None:
        """Clear conversational context after user has responded."""
        self.last_delivered_reminder_id = None
        self.last_delivered_at = None


# Global scheduler singleton
_global_scheduler: Optional[ReminderScheduler] = None


def get_global_reminder_scheduler(
    store: Optional[ReminderStore] = None,
    notification_dispatcher: Optional[Callable] = None,
    session_auth_checker: Optional[Callable] = None,
) -> ReminderScheduler:
    """Provides the singleton instance of the ReminderScheduler."""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = ReminderScheduler(
            store=store,
            notification_dispatcher=notification_dispatcher,
            session_auth_checker=session_auth_checker,
        )
    else:
        if notification_dispatcher:
            _global_scheduler.set_notification_dispatcher(notification_dispatcher)
        if session_auth_checker:
            _global_scheduler.set_session_auth_checker(session_auth_checker)
    return _global_scheduler
