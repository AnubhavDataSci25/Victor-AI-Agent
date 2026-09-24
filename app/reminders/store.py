"""
Persistent SQLite store for Victor's Real-Time Date & Reminder System.
Ensures zero memory loss across Victor restarts, crashes, and normal memory cleanup.
Provides deterministic atomic state transitions, duplicate prevention, and index-backed queries.
"""

from __future__ import annotations

from datetime import date, datetime, time as dtime, timedelta
import json
import logging
from pathlib import Path
import re
import sqlite3
import time
from typing import Any, Dict, List, Optional

from app.reminders.datetime_utils import (
    advance_annual_event,
    calculate_next_milestone_schedule,
    combine_date_time_to_epoch,
    parse_date_str,
    parse_time_str,
    resolve_timezone,
)
from app.reminders.models import (
    ReminderCategory,
    ReminderRecord,
    ReminderRecurrence,
    ReminderStatus,
    generate_reminder_id,
)

logger = logging.getLogger(__name__)


def _normalize_task_text(text: str) -> str:
    """Normalize task description for similarity and duplicate matching."""
    lower = text.lower().strip()
    return re.sub(r"[^\w\s]", "", lower)


class ReminderStore:
    """
    Dedicated persistent SQLite store for Victor reminders with ACID compliance,
    WAL mode, and dedicated indexes for status, category, date, and next_reminder_at.
    """

    def __init__(self, db_path: str = "config/memory.db") -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self) -> None:
        """Create tables and indexes if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id TEXT PRIMARY KEY,
                    work_task TEXT NOT NULL,
                    category TEXT NOT NULL,
                    date TEXT NOT NULL,
                    time TEXT NOT NULL,
                    timezone TEXT NOT NULL,
                    due_datetime REAL NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    recurrence TEXT NOT NULL DEFAULT 'none',
                    notification_schedule TEXT NOT NULL DEFAULT '[]',
                    delivered_milestones TEXT NOT NULL DEFAULT '[]',
                    last_reminded_at REAL,
                    next_reminder_at REAL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    is_archived INTEGER NOT NULL DEFAULT 0
                );
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminder_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reminder_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    details TEXT,
                    created_at REAL NOT NULL
                );
            """)

            # Database Indexes for rapid retrieval
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status ON reminders(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_category ON reminders(category);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_due_datetime ON reminders(due_datetime);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_next_reminder_at ON reminders(next_reminder_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_is_archived ON reminders(is_archived);")
            conn.commit()

    def _row_to_record(self, row: sqlite3.Row) -> ReminderRecord:
        """Convert a SQLite row to a ReminderRecord."""
        sched = json.loads(row["notification_schedule"]) if row["notification_schedule"] else []
        deliv = json.loads(row["delivered_milestones"]) if row["delivered_milestones"] else []
        return ReminderRecord(
            id=row["id"],
            work_task=row["work_task"],
            category=ReminderCategory(row["category"]),
            date=row["date"],
            time=row["time"],
            timezone=row["timezone"],
            due_datetime=row["due_datetime"],
            status=ReminderStatus(row["status"]),
            recurrence=ReminderRecurrence(row["recurrence"]),
            notification_schedule=sched,
            delivered_milestones=deliv,
            last_reminded_at=row["last_reminded_at"],
            next_reminder_at=row["next_reminder_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            is_archived=bool(row["is_archived"]),
        )

    def create_reminder(
        self,
        work_task: str,
        date_str: str,
        time_str: str = "",
        category: str = "professional",
        timezone_str: Optional[str] = None,
        recurrence: str = "none",
    ) -> ReminderRecord:
        """
        Creates or updates a reminder.
        Enforces duplicate detection: if an active task with the same normalized description
        already exists, updates its deadline/schedule rather than creating a duplicate.
        """
        tz = resolve_timezone(timezone_str)
        tz_name = getattr(tz, "key", None) or timezone_str or "Asia/Kolkata"

        cat_enum = ReminderCategory.PROFESSIONAL
        try:
            cat_enum = ReminderCategory(category.lower())
        except Exception:
            pass

        # Annual recurrence auto-classification for birthdays and anniversaries
        rec_enum = ReminderRecurrence.NONE
        try:
            rec_enum = ReminderRecurrence(recurrence.lower())
        except Exception:
            pass
        if cat_enum in (ReminderCategory.BIRTHDAY, ReminderCategory.ANNIVERSARY):
            rec_enum = ReminderRecurrence.ANNUALLY

        # Parse date & time accurately
        is_deadline = "deadline" in work_task.lower() or "due" in work_task.lower()
        d = parse_date_str(date_str, tz)
        t = parse_time_str(time_str, default_for_deadline=is_deadline)

        due_epoch = combine_date_time_to_epoch(d, t, tz)
        iso_date = d.isoformat()
        iso_time = t.isoformat()

        # Calculate initial milestone schedule
        next_rem, plan = calculate_next_milestone_schedule(due_epoch, tz, [])

        now = time.time()

        # Check for existing duplicate active task
        existing = self.find_duplicate_task(work_task)
        if existing:
            logger.info(f"Duplicate/similar task found ('{existing.work_task}', ID: {existing.id}). Updating existing task.")
            return self.update_reminder(
                reminder_id=existing.id,
                new_date=iso_date,
                new_time=iso_time,
                new_task=work_task,
                new_category=cat_enum.value,
            )

        new_id = generate_reminder_id()
        record = ReminderRecord(
            id=new_id,
            work_task=work_task,
            category=cat_enum,
            date=iso_date,
            time=iso_time,
            timezone=str(tz_name),
            due_datetime=due_epoch,
            status=ReminderStatus.PENDING,
            recurrence=rec_enum,
            notification_schedule=plan,
            delivered_milestones=[],
            last_reminded_at=None,
            next_reminder_at=next_rem,
            created_at=now,
            updated_at=now,
            is_archived=False,
        )

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO reminders (
                    id, work_task, category, date, time, timezone, due_datetime,
                    status, recurrence, notification_schedule, delivered_milestones,
                    last_reminded_at, next_reminder_at, created_at, updated_at, is_archived
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.id,
                record.work_task,
                record.category.value,
                record.date,
                record.time,
                record.timezone,
                record.due_datetime,
                record.status.value,
                record.recurrence.value,
                json.dumps(record.notification_schedule),
                json.dumps(record.delivered_milestones),
                record.last_reminded_at,
                record.next_reminder_at,
                record.created_at,
                record.updated_at,
                1 if record.is_archived else 0,
            ))
            conn.execute("""
                INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (record.id, "created", f"Scheduled for {record.date} at {record.time}", now))
            conn.commit()

        logger.info(f"Reminder created: [{record.category.value}] '{record.work_task}' due {record.date} {record.time}")
        return record

    def find_duplicate_task(self, work_task: str) -> Optional[ReminderRecord]:
        """Finds an existing active task matching the description to prevent duplicates."""
        norm_query = _normalize_task_text(work_task)
        if not norm_query:
            return None

        active_tasks = self.list_active_reminders()
        for r in active_tasks:
            norm_existing = _normalize_task_text(r.work_task)
            if norm_query == norm_existing or norm_query in norm_existing or norm_existing in norm_query:
                return r
        return None

    def get_reminder(self, reminder_id: str) -> Optional[ReminderRecord]:
        """Fetch reminder by ID."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
            row = cursor.fetchone()
            if row:
                return self._row_to_record(row)
        return None

    def find_reminders_by_query(
        self,
        query: str,
        status: Optional[ReminderStatus] = None,
        include_archived: bool = False,
    ) -> List[ReminderRecord]:
        """Searches reminders by keyword matching work_task or id."""
        norm_q = _normalize_task_text(query)
        results = []

        with self._get_connection() as conn:
            cursor = conn.cursor()
            sql = "SELECT * FROM reminders WHERE 1=1"
            params: List[Any] = []

            if not include_archived:
                sql += " AND is_archived = 0"

            if status is not None:
                sql += " AND status = ?"
                params.append(status.value)

            sql += " ORDER BY due_datetime ASC"
            cursor.execute(sql, params)
            rows = cursor.fetchall()

            for row in rows:
                rec = self._row_to_record(row)
                if query.lower() in rec.id.lower() or norm_q in _normalize_task_text(rec.work_task):
                    results.append(rec)
        return results

    def list_active_reminders(
        self,
        category: Optional[str] = None,
        timeframe: Optional[str] = None,
        tz: Optional[Any] = None,
    ) -> List[ReminderRecord]:
        """
        Lists active (pending/postponed) non-archived reminders.
        Can filter by timeframe: 'today', 'tomorrow', 'upcoming', 'overdue', 'all'.
        """
        resolved_tz = tz or resolve_timezone(None)
        now_dt = datetime.now(resolved_tz)
        today_date = now_dt.date()
        today_str = today_date.isoformat()
        tomorrow_str = (today_date + datetime.resolution).isoformat() if hasattr(datetime, "resolution") else ""
        from datetime import timedelta
        tomorrow_str = (today_date + timedelta(days=1)).isoformat()

        sql = "SELECT * FROM reminders WHERE is_archived = 0 AND status IN ('pending', 'postponed')"
        params: List[Any] = []

        if category and category.strip():
            sql += " AND category = ?"
            params.append(category.strip().lower())

        sql += " ORDER BY due_datetime ASC"

        records: List[ReminderRecord] = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, params)
            rows = cursor.fetchall()
            for row in rows:
                rec = self._row_to_record(row)
                records.append(rec)

        if not timeframe or timeframe.lower() == "all" or timeframe.lower() == "upcoming":
            return records

        filtered = []
        now_epoch = now_dt.timestamp()
        for r in records:
            if timeframe.lower() == "today" and r.date == today_str:
                filtered.append(r)
            elif timeframe.lower() == "tomorrow" and r.date == tomorrow_str:
                filtered.append(r)
            elif timeframe.lower() == "overdue" and r.due_datetime < now_epoch:
                filtered.append(r)

        return filtered

    def get_due_reminders(self, now: float) -> List[ReminderRecord]:
        """Returns pending reminders whose next scheduled reminder time has arrived."""
        sql = """
            SELECT * FROM reminders
            WHERE status IN ('pending', 'postponed')
              AND is_archived = 0
              AND next_reminder_at IS NOT NULL
              AND next_reminder_at <= ?
            ORDER BY next_reminder_at ASC
        """
        results: List[ReminderRecord] = []
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (now,))
            rows = cursor.fetchall()
            for row in rows:
                results.append(self._row_to_record(row))
        return results

    def get_earliest_next_reminder_time(self) -> Optional[float]:
        """Returns the earliest epoch timestamp across all pending reminders, or None."""
        sql = """
            SELECT MIN(next_reminder_at) as earliest
            FROM reminders
            WHERE status IN ('pending', 'postponed')
              AND is_archived = 0
              AND next_reminder_at IS NOT NULL
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql)
            row = cursor.fetchone()
            if row and row["earliest"] is not None:
                return float(row["earliest"])
        return None

    def mark_milestone_delivered(
        self,
        reminder_id: str,
        milestone: str,
        now: float,
    ) -> Optional[ReminderRecord]:
        """
        Records that a reminder milestone was delivered and advances to the next milestone.
        Atomically prevents duplicate notifications.
        """
        rec = self.get_reminder(reminder_id)
        if not rec:
            return None

        delivered = list(rec.delivered_milestones)
        if milestone not in delivered:
            delivered.append(milestone)

        tz = resolve_timezone(rec.timezone)
        next_ts, _ = calculate_next_milestone_schedule(
            rec.due_datetime,
            tz,
            delivered,
            reference_now=now,
        )

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE reminders
                SET delivered_milestones = ?,
                    last_reminded_at = ?,
                    next_reminder_at = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                json.dumps(delivered),
                now,
                next_ts,
                now,
                reminder_id,
            ))
            conn.execute("""
                INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (reminder_id, "milestone_delivered", f"Milestone: {milestone}", now))
            conn.commit()

        rec.delivered_milestones = delivered
        rec.last_reminded_at = now
        rec.next_reminder_at = next_ts
        rec.updated_at = now
        return rec

    def complete_reminder(self, reminder_id: str) -> Optional[ReminderRecord]:
        """
        Marks reminder as completed.
        - One-time professional tasks: status='completed', is_archived=1, next_reminder_at=None.
        - Recurring tasks (birthdays/anniversaries): advances due date by 1 year, resets milestones,
          recalculates next_reminder_at. Never archived!
        """
        rec = self.get_reminder(reminder_id)
        if not rec:
            return None

        now = time.time()
        tz = resolve_timezone(rec.timezone)

        if rec.is_recurring():
            # Permanent personal recurring event lifecycle
            d = parse_date_str(rec.date, tz)
            t = parse_time_str(rec.time)
            new_d, new_epoch = advance_annual_event(d, t, tz)
            next_rem, plan = calculate_next_milestone_schedule(new_epoch, tz, [], reference_now=now)

            with self._get_connection() as conn:
                conn.execute("""
                    UPDATE reminders
                    SET date = ?,
                        due_datetime = ?,
                        delivered_milestones = '[]',
                        next_reminder_at = ?,
                        status = 'pending',
                        updated_at = ?
                    WHERE id = ?
                """, (
                    new_d.isoformat(),
                    new_epoch,
                    next_rem,
                    now,
                    reminder_id,
                ))
                conn.execute("""
                    INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                    VALUES (?, ?, ?, ?)
                """, (reminder_id, "completed_and_advanced_annual", f"Advanced to {new_d.isoformat()}", now))
                conn.commit()

            rec.date = new_d.isoformat()
            rec.due_datetime = new_epoch
            rec.delivered_milestones = []
            rec.next_reminder_at = next_rem
            rec.updated_at = now
            logger.info(f"Recurring reminder '{rec.work_task}' completed and advanced to {rec.date}.")
            return rec
        else:
            # One-time professional/personal task lifecycle: archive and halt future reminders
            with self._get_connection() as conn:
                conn.execute("""
                    UPDATE reminders
                    SET status = 'completed',
                        is_archived = 1,
                        next_reminder_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                """, (now, reminder_id))
                conn.execute("""
                    INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                    VALUES (?, ?, ?, ?)
                """, (reminder_id, "completed", "Task completed and archived.", now))
                conn.commit()

            rec.status = ReminderStatus.COMPLETED
            rec.is_archived = True
            rec.next_reminder_at = None
            rec.updated_at = now
            logger.info(f"One-time reminder '{rec.work_task}' completed and archived.")
            return rec

    def postpone_reminder(
        self,
        reminder_id: str,
        new_date: str,
        new_time: str = "",
    ) -> Optional[ReminderRecord]:
        """
        Postpones a task deadline to a new date/time.
        Immediately stops old reminders, recalculates future schedule, and sets status='pending'.
        """
        rec = self.get_reminder(reminder_id)
        if not rec:
            return None

        tz = resolve_timezone(rec.timezone)
        d = parse_date_str(new_date, tz)
        t = parse_time_str(new_time or rec.time)
        new_due_epoch = combine_date_time_to_epoch(d, t, tz)

        now = time.time()
        # Recalculate all future reminders based on the new deadline
        next_rem, plan = calculate_next_milestone_schedule(new_due_epoch, tz, [], reference_now=now)

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE reminders
                SET date = ?,
                    time = ?,
                    due_datetime = ?,
                    status = 'pending',
                    is_archived = 0,
                    delivered_milestones = '[]',
                    notification_schedule = ?,
                    next_reminder_at = ?,
                    updated_at = ?
                WHERE id = ?
            """, (
                d.isoformat(),
                t.isoformat(),
                new_due_epoch,
                json.dumps(plan),
                next_rem,
                now,
                reminder_id,
            ))
            conn.execute("""
                INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (reminder_id, "postponed", f"Postponed to {d.isoformat()} at {t.isoformat()}", now))
            conn.commit()

        rec.date = d.isoformat()
        rec.time = t.isoformat()
        rec.due_datetime = new_due_epoch
        rec.status = ReminderStatus.PENDING
        rec.is_archived = False
        rec.delivered_milestones = []
        rec.notification_schedule = plan
        rec.next_reminder_at = next_rem
        rec.updated_at = now
        logger.info(f"Reminder '{rec.work_task}' postponed to {rec.date} {rec.time}.")
        return rec

    def update_reminder(
        self,
        reminder_id: str,
        new_date: Optional[str] = None,
        new_time: Optional[str] = None,
        new_task: Optional[str] = None,
        new_category: Optional[str] = None,
    ) -> Optional[ReminderRecord]:
        """Updates fields of an existing reminder and recalculates schedule if date/time changed."""
        rec = self.get_reminder(reminder_id)
        if not rec:
            return None

        tz = resolve_timezone(rec.timezone)
        d_val = parse_date_str(new_date, tz) if new_date else parse_date_str(rec.date, tz)
        t_val = parse_time_str(new_time) if new_time else parse_time_str(rec.time)
        new_epoch = combine_date_time_to_epoch(d_val, t_val, tz)

        cat = rec.category
        if new_category:
            try:
                cat = ReminderCategory(new_category.lower())
            except Exception:
                pass

        task_name = new_task.strip() if new_task and new_task.strip() else rec.work_task

        now = time.time()
        # If date or time changed, reset delivered milestones and recalculate schedule
        if d_val.isoformat() != rec.date or t_val.isoformat() != rec.time:
            delivered = []
            next_rem, plan = calculate_next_milestone_schedule(new_epoch, tz, [], reference_now=now)
        else:
            delivered = rec.delivered_milestones
            next_rem = rec.next_reminder_at
            plan = rec.notification_schedule

        with self._get_connection() as conn:
            conn.execute("""
                UPDATE reminders
                SET work_task = ?,
                    category = ?,
                    date = ?,
                    time = ?,
                    due_datetime = ?,
                    delivered_milestones = ?,
                    notification_schedule = ?,
                    next_reminder_at = ?,
                    status = 'pending',
                    is_archived = 0,
                    updated_at = ?
                WHERE id = ?
            """, (
                task_name,
                cat.value,
                d_val.isoformat(),
                t_val.isoformat(),
                new_epoch,
                json.dumps(delivered),
                json.dumps(plan),
                next_rem,
                now,
                reminder_id,
            ))
            conn.execute("""
                INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (reminder_id, "updated", f"Updated to {task_name}, {d_val.isoformat()} {t_val.isoformat()}", now))
            conn.commit()

        rec.work_task = task_name
        rec.category = cat
        rec.date = d_val.isoformat()
        rec.time = t_val.isoformat()
        rec.due_datetime = new_epoch
        rec.delivered_milestones = delivered
        rec.notification_schedule = plan
        rec.next_reminder_at = next_rem
        rec.status = ReminderStatus.PENDING
        rec.is_archived = False
        rec.updated_at = now
        return rec

    def cancel_reminder(self, reminder_id: str) -> Optional[ReminderRecord]:
        """Cancels a reminder and stops all future notifications."""
        rec = self.get_reminder(reminder_id)
        if not rec:
            return None

        now = time.time()
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE reminders
                SET status = 'cancelled',
                    is_archived = 1,
                    next_reminder_at = NULL,
                    updated_at = ?
                WHERE id = ?
            """, (now, reminder_id))
            conn.execute("""
                INSERT INTO reminder_history (reminder_id, event_type, details, created_at)
                VALUES (?, ?, ?, ?)
            """, (reminder_id, "cancelled", "Cancelled by user.", now))
            conn.commit()

        rec.status = ReminderStatus.CANCELLED
        rec.is_archived = True
        rec.next_reminder_at = None
        rec.updated_at = now
        return rec

    def delete_reminder(self, reminder_id: str) -> bool:
        """Permanently deletes a reminder from database."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            cursor.execute("DELETE FROM reminder_history WHERE reminder_id = ?", (reminder_id,))
            conn.commit()
            return cursor.rowcount > 0
