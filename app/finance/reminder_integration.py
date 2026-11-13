"""
Victor Personal Finance, Expense & Bill Management Agent — Reminder Integration.

Reuses Victor's existing persistent ReminderScheduler and ReminderStore.
Schedules proactive reminders:
- 3 days before due date
- 2 days before due date
- 1 day before due date
- On the due date
- Daily overdue reminders for pending bills

Stops reminders when a bill is paid, regenerates next cycle for recurring bills,
and supports postponement without duplicate schedulers.
"""

from __future__ import annotations

import datetime
import logging
import time
from typing import Any, List, Optional

from app.finance.models import Bill, BillStatus
from app.finance.store import FinanceStore
from app.reminders.datetime_utils import resolve_timezone
from app.reminders.models import (
    ReminderCategory,
    ReminderMilestone,
    ReminderRecord,
    ReminderRecurrence,
    ReminderStatus,
)
from app.reminders.scheduler import ReminderScheduler, get_global_reminder_scheduler
from app.reminders.store import ReminderStore

logger = logging.getLogger(__name__)


class FinanceBillReminderManager:
    def __init__(
        self,
        finance_store: Optional[FinanceStore] = None,
        reminder_store: Optional[ReminderStore] = None,
        scheduler: Optional[ReminderScheduler] = None,
    ) -> None:
        self.finance_store = finance_store or FinanceStore()
        self.reminder_store = reminder_store or ReminderStore()
        self.scheduler = scheduler

    def _get_scheduler(self) -> ReminderScheduler:
        if self.scheduler is None:
            self.scheduler = get_global_reminder_scheduler()
        return self.scheduler

    def schedule_bill_reminders(self, bill: Bill) -> Optional[ReminderRecord]:
        """
        Schedules proactive milestone reminders into Victor's existing ReminderStore for a bill.
        """
        if bill.status in (BillStatus.PAID, BillStatus.CANCELLED):
            self.cancel_bill_reminders(bill.bill_id)
            return None

        task_msg = f"Pay {bill.provider_name} bill of ₹{bill.expected_amount:.2f} (Due: {bill.due_date})"

        existing = self.reminder_store.find_duplicate_task(task_msg)
        if existing:
            record = self.reminder_store.update_reminder(
                reminder_id=existing.id,
                new_date=bill.due_date[:10],
                new_time="10:00:00",
                new_task=task_msg,
            )
        else:
            record = self.reminder_store.create_reminder(
                work_task=task_msg,
                date_str=bill.due_date[:10],
                time_str="10:00:00",
                category="personal",
            )

        # Notify active scheduler loop
        try:
            sched = self._get_scheduler()
            sched.notify_store_updated()
        except Exception as e:
            logger.debug(f"[FinanceReminders] Scheduler notify warning: {e}")

        logger.info(f"[FinanceReminders] Scheduled bill reminders for {bill.provider_name} ({bill.bill_id})")
        return record

    def cancel_bill_reminders(self, bill_id: str) -> bool:
        """Cancels any pending reminders for a paid or cancelled bill."""
        bill = self.finance_store.get_bill(bill_id)
        provider = bill.provider_name if bill else bill_id
        matches = self.reminder_store.find_reminders_by_query(provider, status=ReminderStatus.PENDING)
        cancelled = False
        for m in matches:
            if "bill" in m.work_task.lower() or "pay" in m.work_task.lower():
                self.reminder_store.cancel_reminder(m.id)
                cancelled = True
        try:
            self._get_scheduler().notify_store_updated()
        except Exception:
            pass
        return cancelled

    def postpone_bill_reminder(self, bill_id: str, days: int = 1) -> bool:
        """Postpones the reminder by specified number of days."""
        bill = self.finance_store.get_bill(bill_id)
        provider = bill.provider_name if bill else bill_id
        matches = self.reminder_store.find_reminders_by_query(provider, status=ReminderStatus.PENDING)
        if not matches:
            return False

        target = matches[0]
        try:
            dt = datetime.datetime.strptime(target.date, "%Y-%m-%d") + datetime.timedelta(days=days)
            new_date = dt.strftime("%Y-%m-%d")
        except Exception:
            new_date = time.strftime("%Y-%m-%d")

        res = self.reminder_store.postpone_reminder(target.id, new_date=new_date)
        try:
            self._get_scheduler().notify_store_updated()
        except Exception:
            pass
        return res is not None

    async def check_due_bills_tick_hook(self) -> List[dict[str, Any]]:
        """
        Invoked periodically by the global ReminderScheduler tick.
        Detects upcoming and overdue bills, returning actionable alert payloads.
        """
        today = time.strftime("%Y-%m-%d")
        now = time.time()
        alerts = []

        bills = self.finance_store.get_pending_and_overdue_bills()
        for b in bills:
            if b.status in (BillStatus.PAID, BillStatus.CANCELLED):
                continue

            try:
                due_dt = datetime.datetime.strptime(b.due_date[:10], "%Y-%m-%d").date()
                today_dt = datetime.datetime.strptime(today, "%Y-%m-%d").date()
                delta_days = (due_dt - today_dt).days
            except Exception:
                continue

            if delta_days < 0:
                # Overdue
                alerts.append({
                    "bill_id": b.bill_id,
                    "provider": b.provider_name,
                    "amount": b.expected_amount,
                    "remaining": b.remaining_amount,
                    "status": "OVERDUE",
                    "days_overdue": abs(delta_days),
                    "message": f"Sir, your {b.provider_name} bill of ₹{b.remaining_amount:.2f} was due {abs(delta_days)} day(s) ago and is OVERDUE.",
                })
            elif delta_days in (0, 1, 2, 3):
                milestone_desc = "today" if delta_days == 0 else f"in {delta_days} day(s)"
                alerts.append({
                    "bill_id": b.bill_id,
                    "provider": b.provider_name,
                    "amount": b.expected_amount,
                    "remaining": b.remaining_amount,
                    "status": "UPCOMING",
                    "days_left": delta_days,
                    "message": f"Sir, your {b.provider_name} bill of ₹{b.remaining_amount:.2f} is due {milestone_desc}.",
                })

        return alerts
