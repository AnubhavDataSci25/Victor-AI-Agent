"""
Victor 2.0 BaseTool implementations for Real-Time Date & Reminder System.
Integrates with ToolGateway, ToolRegistry, and Gemini Live API.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.reminders.datetime_utils import format_friendly_reminder_message
from app.reminders.models import ReminderCategory, ReminderStatus
from app.reminders.scheduler import ReminderScheduler, get_global_reminder_scheduler
from app.reminders.store import ReminderStore
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class ReminderCreateTool(BaseTool):
    """Schedules a new persistent task deadline, meeting, birthday, anniversary, or reminder."""

    name = "reminder_create"
    description = (
        "Create and permanently persist a date/time-based reminder or task deadline. "
        "Supports professional deadlines, assignments, meetings, personal tasks, birthdays, and anniversaries. "
        "Survives system restarts and triggers proactive notifications in advance (3d, 2d, 1d, and on due date)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "work_task": {
                "type": "string",
                "description": "The specific task, project deadline, meeting, or event name (e.g. 'Project Deadline', 'Mom's Birthday', 'Submit Tax Return').",
            },
            "date": {
                "type": "string",
                "description": "The date when the task is due or the event occurs (e.g. '2nd October 2026', '2026-10-02', 'tomorrow', '15th August').",
            },
            "time": {
                "type": "string",
                "description": "Optional exact or approximate time (e.g. '11:59 PM', 'before 11:59 PM', '5:30 PM', '09:00 AM'). Defaults to 23:59:00 for deadlines, 09:00:00 for other tasks.",
            },
            "category": {
                "type": "string",
                "enum": ["professional", "personal", "birthday", "anniversary", "other"],
                "description": "Category of the reminder. Use 'professional' for work/projects/assignments, 'birthday' for birthdays, 'anniversary' for anniversaries, 'personal' for personal commitments.",
            },
            "timezone": {
                "type": "string",
                "description": "Optional timezone identifier (e.g. 'Asia/Kolkata', 'IST', 'UTC', 'America/New_York'). Defaults to user's local timezone.",
            },
            "recurrence": {
                "type": "string",
                "enum": ["none", "annually", "monthly", "weekly", "daily"],
                "description": "Recurrence pattern. Birthdays and anniversaries automatically default to 'annually'.",
            },
        },
        "required": ["work_task", "date"],
    }

    def __init__(
        self,
        store: Optional[ReminderStore] = None,
        scheduler: Optional[ReminderScheduler] = None,
    ) -> None:
        self.store = store or ReminderStore()
        self.scheduler = scheduler or get_global_reminder_scheduler(store=self.store)

    async def execute(self, args: dict) -> str:
        work_task = args.get("work_task", "").strip()
        date_str = args.get("date", "").strip()
        time_str = args.get("time", "").strip()
        category = args.get("category", "professional").strip()
        tz_str = args.get("timezone", "").strip()
        recurrence = args.get("recurrence", "none").strip()

        if not work_task:
            return "Error: 'work_task' description is required to schedule a reminder."
        if not date_str:
            return "Error: 'date' is required to schedule a reminder."

        try:
            record = self.store.create_reminder(
                work_task=work_task,
                date_str=date_str,
                time_str=time_str,
                category=category,
                timezone_str=tz_str or None,
                recurrence=recurrence,
            )
            # Wake the background scheduler so it adjusts its sleep timer immediately
            self.scheduler.notify_store_updated()

            rec_note = " (recurring annually)" if record.is_recurring() else ""
            return (
                f"Sir, I have scheduled your reminder for '{record.work_task}' on {record.date} at {record.time} "
                f"({record.timezone}, Category: {record.category.value}){rec_note}. "
                "I will proactively remind you in advance according to the low-noise schedule."
            )
        except ValueError as ve:
            return f"Error: Could not schedule reminder: {str(ve)}"
        except Exception as e:
            logger.error(f"Failed to create reminder: {e}", exc_info=True)
            return f"Error: Database failure while creating reminder: {str(e)}"


class ReminderListTool(BaseTool):
    """Lists active, upcoming, today's, or overdue reminders."""

    name = "reminder_list"
    description = (
        "List stored reminders, task deadlines, meetings, birthdays, and anniversaries. "
        "Allows filtering by timeframe ('upcoming', 'today', 'tomorrow', 'overdue', 'all') or category."
    )
    parameters = {
        "type": "object",
        "properties": {
            "timeframe": {
                "type": "string",
                "enum": ["upcoming", "today", "tomorrow", "overdue", "all"],
                "description": "Filter by timeframe. Defaults to 'upcoming'.",
            },
            "category": {
                "type": "string",
                "enum": ["professional", "personal", "birthday", "anniversary", "other"],
                "description": "Optional category filter.",
            },
        },
    }

    def __init__(self, store: Optional[ReminderStore] = None) -> None:
        self.store = store or ReminderStore()

    async def execute(self, args: dict) -> str:
        timeframe = args.get("timeframe", "upcoming").strip()
        category = args.get("category", "").strip()

        try:
            reminders = self.store.list_active_reminders(
                category=category or None,
                timeframe=timeframe,
            )
            if not reminders:
                cat_desc = f" in category '{category}'" if category else ""
                tf_desc = f" for '{timeframe}'" if timeframe != "all" else ""
                return f"Sir, you have no pending reminders or deadlines{tf_desc}{cat_desc}."

            lines = [f"Sir, here are your {timeframe} reminders:"]
            for r in reminders:
                rec_tag = " (Annual)" if r.is_recurring() else ""
                lines.append(f"- **{r.work_task}**: Due {r.date} at {r.time} [{r.category.value.title()}]{rec_tag}")
            return "\n".join(lines)
        except Exception as e:
            logger.error(f"Failed to list reminders: {e}")
            return f"Error: Unable to retrieve reminders: {str(e)}"


class ReminderCompleteTool(BaseTool):
    """Marks a task deadline or reminder as completed."""

    name = "reminder_complete"
    description = (
        "Mark a task, project deadline, or reminder as completed. "
        "Halts all future scheduled notifications for one-time tasks and archives them. "
        "For recurring birthdays and anniversaries, advances the schedule to next year."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_query": {
                "type": "string",
                "description": "The name or keywords of the task to complete (e.g. 'project deadline', 'assignment'). If empty or 'this', completes the last proactively reminded task.",
            },
            "reminder_id": {
                "type": "string",
                "description": "Optional direct reminder ID (e.g. 'rem_12345').",
            },
        },
    }

    def __init__(
        self,
        store: Optional[ReminderStore] = None,
        scheduler: Optional[ReminderScheduler] = None,
    ) -> None:
        self.store = store or ReminderStore()
        self.scheduler = scheduler or get_global_reminder_scheduler(store=self.store)

    async def execute(self, args: dict) -> str:
        task_query = args.get("task_query", "").strip()
        reminder_id = args.get("reminder_id", "").strip()

        target_id: Optional[str] = None

        if reminder_id:
            target_id = reminder_id
        elif not task_query or task_query.lower() in ("this", "this task", "last", "last reminder", "it"):
            last_rec = self.scheduler.get_last_delivered_reminder()
            if last_rec:
                target_id = last_rec.id

        if not target_id and task_query:
            matches = self.store.find_reminders_by_query(task_query)
            if not matches:
                return f"Sir, I could not find any active reminder matching '{task_query}'."
            if len(matches) > 1:
                options = ", ".join([f"'{m.work_task}' ({m.date})" for m in matches[:3]])
                return f"Sir, multiple tasks match '{task_query}': {options}. Please specify which one you completed."
            target_id = matches[0].id

        if not target_id:
            return "Error: Please specify the task name or reminder ID you would like to mark as completed."

        try:
            completed_rec = self.store.complete_reminder(target_id)
            if not completed_rec:
                return f"Error: Reminder '{target_id}' could not be found or was already completed."

            self.scheduler.notify_store_updated()
            self.scheduler.clear_last_delivered_context()

            if completed_rec.is_recurring():
                return f"Sir, I have recorded '{completed_rec.work_task}' as completed for this year. The next occurrence is scheduled for {completed_rec.date}."
            return f"Sir, I have marked '{completed_rec.work_task}' as completed and stopped future notifications."
        except Exception as e:
            logger.error(f"Failed to complete reminder: {e}")
            return f"Error: Database failure completing reminder: {str(e)}"


class ReminderPostponeTool(BaseTool):
    """Postpones a task deadline to a new date and time."""

    name = "reminder_postpone"
    description = (
        "Postpone an existing task or deadline to a new date and time. "
        "Immediately cancels old scheduled reminders and recalculates future notification times from the new deadline."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task_query": {
                "type": "string",
                "description": "The name or keywords of the task to postpone (e.g. 'project deadline').",
            },
            "new_date": {
                "type": "string",
                "description": "The new deadline date (e.g. '5th October 2026', '2026-10-05', 'tomorrow').",
            },
            "new_time": {
                "type": "string",
                "description": "Optional new time (e.g. '11:59 PM', '18:00'). If omitted, keeps previous time.",
            },
            "reminder_id": {
                "type": "string",
                "description": "Optional direct reminder ID.",
            },
        },
        "required": ["new_date"],
    }

    def __init__(
        self,
        store: Optional[ReminderStore] = None,
        scheduler: Optional[ReminderScheduler] = None,
    ) -> None:
        self.store = store or ReminderStore()
        self.scheduler = scheduler or get_global_reminder_scheduler(store=self.store)

    async def execute(self, args: dict) -> str:
        task_query = args.get("task_query", "").strip()
        new_date = args.get("new_date", "").strip()
        new_time = args.get("new_time", "").strip()
        reminder_id = args.get("reminder_id", "").strip()

        if not new_date:
            return "Error: 'new_date' is required to postpone a deadline."

        target_id: Optional[str] = None
        if reminder_id:
            target_id = reminder_id
        elif not task_query or task_query.lower() in ("this", "this task", "last", "last reminder", "it"):
            last_rec = self.scheduler.get_last_delivered_reminder()
            if last_rec:
                target_id = last_rec.id

        if not target_id and task_query:
            matches = self.store.find_reminders_by_query(task_query)
            if not matches:
                return f"Sir, I could not find any active reminder matching '{task_query}'."
            if len(matches) > 1:
                options = ", ".join([f"'{m.work_task}' ({m.date})" for m in matches[:3]])
                return f"Sir, multiple tasks match '{task_query}': {options}. Please clarify which one to postpone."
            target_id = matches[0].id

        if not target_id:
            return "Error: Please specify which task you would like to postpone."

        try:
            postponed = self.store.postpone_reminder(
                reminder_id=target_id,
                new_date=new_date,
                new_time=new_time,
            )
            if not postponed:
                return f"Error: Reminder '{target_id}' could not be found."

            self.scheduler.notify_store_updated()
            self.scheduler.clear_last_delivered_context()

            return (
                f"Sir, your deadline for '{postponed.work_task}' has been postponed to {postponed.date} at {postponed.time}. "
                "I have recalculated your future notifications and stopped reminders for the old deadline."
            )
        except ValueError as ve:
            return f"Error: Could not postpone reminder: {str(ve)}"
        except Exception as e:
            logger.error(f"Failed to postpone reminder: {e}")
            return f"Error: Database failure postponing reminder: {str(e)}"


class ReminderUpdateTool(BaseTool):
    """Updates fields (task name, date, time, category) of an existing reminder."""

    name = "reminder_update"
    description = "Update an existing reminder or deadline with new task details, date, time, or category."
    parameters = {
        "type": "object",
        "properties": {
            "task_query": {
                "type": "string",
                "description": "Keywords or name of the task to update.",
            },
            "new_date": {
                "type": "string",
                "description": "Optional new date (e.g. '2026-10-05').",
            },
            "new_time": {
                "type": "string",
                "description": "Optional new time (e.g. '18:00').",
            },
            "new_task": {
                "type": "string",
                "description": "Optional updated task description.",
            },
            "new_category": {
                "type": "string",
                "enum": ["professional", "personal", "birthday", "anniversary", "other"],
                "description": "Optional new category.",
            },
            "reminder_id": {
                "type": "string",
                "description": "Optional direct reminder ID.",
            },
        },
    }

    def __init__(
        self,
        store: Optional[ReminderStore] = None,
        scheduler: Optional[ReminderScheduler] = None,
    ) -> None:
        self.store = store or ReminderStore()
        self.scheduler = scheduler or get_global_reminder_scheduler(store=self.store)

    async def execute(self, args: dict) -> str:
        task_query = args.get("task_query", "").strip()
        reminder_id = args.get("reminder_id", "").strip()

        target_id: Optional[str] = None
        if reminder_id:
            target_id = reminder_id
        elif not task_query or task_query.lower() in ("this", "this task", "last", "last reminder", "it"):
            last_rec = self.scheduler.get_last_delivered_reminder()
            if last_rec:
                target_id = last_rec.id

        if not target_id and task_query:
            matches = self.store.find_reminders_by_query(task_query)
            if not matches:
                return f"Sir, I could not find any active reminder matching '{task_query}'."
            if len(matches) > 1:
                options = ", ".join([f"'{m.work_task}' ({m.date})" for m in matches[:3]])
                return f"Sir, multiple tasks match '{task_query}': {options}. Please clarify which one to update."
            target_id = matches[0].id

        if not target_id:
            return "Error: Please specify which task you would like to update."

        try:
            updated = self.store.update_reminder(
                reminder_id=target_id,
                new_date=args.get("new_date"),
                new_time=args.get("new_time"),
                new_task=args.get("new_task"),
                new_category=args.get("new_category"),
            )
            if not updated:
                return f"Error: Reminder '{target_id}' could not be found."

            self.scheduler.notify_store_updated()
            return f"Sir, I have updated your reminder: '{updated.work_task}' due {updated.date} at {updated.time} [{updated.category.value}]."
        except ValueError as ve:
            return f"Error: Could not update reminder: {str(ve)}"
        except Exception as e:
            logger.error(f"Failed to update reminder: {e}")
            return f"Error: Database failure updating reminder: {str(e)}"


class ReminderDeleteTool(BaseTool):
    """Deletes or cancels a task deadline or reminder."""

    name = "reminder_delete"
    description = "Delete or cancel a task deadline or reminder, stopping all future scheduled notifications."
    parameters = {
        "type": "object",
        "properties": {
            "task_query": {
                "type": "string",
                "description": "The name or keywords of the task to delete/cancel.",
            },
            "reminder_id": {
                "type": "string",
                "description": "Optional direct reminder ID.",
            },
        },
    }

    def __init__(
        self,
        store: Optional[ReminderStore] = None,
        scheduler: Optional[ReminderScheduler] = None,
    ) -> None:
        self.store = store or ReminderStore()
        self.scheduler = scheduler or get_global_reminder_scheduler(store=self.store)

    async def execute(self, args: dict) -> str:
        task_query = args.get("task_query", "").strip()
        reminder_id = args.get("reminder_id", "").strip()

        target_id: Optional[str] = None
        if reminder_id:
            target_id = reminder_id
        elif not task_query or task_query.lower() in ("this", "this task", "last", "last reminder", "it"):
            last_rec = self.scheduler.get_last_delivered_reminder()
            if last_rec:
                target_id = last_rec.id

        if not target_id and task_query:
            matches = self.store.find_reminders_by_query(task_query)
            if not matches:
                return f"Sir, I could not find any active reminder matching '{task_query}'."
            if len(matches) > 1:
                options = ", ".join([f"'{m.work_task}' ({m.date})" for m in matches[:3]])
                return f"Sir, multiple tasks match '{task_query}': {options}. Please clarify which one to delete."
            target_id = matches[0].id

        if not target_id:
            return "Error: Please specify which task you would like to delete."

        try:
            cancelled = self.store.cancel_reminder(target_id)
            if not cancelled:
                return f"Error: Reminder '{target_id}' could not be found."

            self.scheduler.notify_store_updated()
            self.scheduler.clear_last_delivered_context()
            return f"Sir, I have cancelled the reminder for '{cancelled.work_task}' and removed it from your schedule."
        except Exception as e:
            logger.error(f"Failed to delete reminder: {e}")
            return f"Error: Database failure deleting reminder: {str(e)}"
