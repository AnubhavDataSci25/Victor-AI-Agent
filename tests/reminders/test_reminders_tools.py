"""
Unit tests for Victor's Reminder BaseTools:
ReminderCreateTool, ReminderListTool, ReminderCompleteTool,
ReminderPostponeTool, ReminderUpdateTool, and ReminderDeleteTool.
"""

from pathlib import Path
import pytest

from app.reminders.models import ReminderCategory, ReminderStatus
from app.reminders.scheduler import ReminderScheduler
from app.reminders.store import ReminderStore
from app.tools.reminders.tool import (
    ReminderCompleteTool,
    ReminderCreateTool,
    ReminderDeleteTool,
    ReminderListTool,
    ReminderPostponeTool,
    ReminderUpdateTool,
)


@pytest.fixture
def setup_tools(tmp_path: Path):
    db_file = tmp_path / "reminders_tools.db"
    store = ReminderStore(db_path=str(db_file))
    scheduler = ReminderScheduler(store=store, max_idle_sleep=0.1)

    create_tool = ReminderCreateTool(store=store, scheduler=scheduler)
    list_tool = ReminderListTool(store=store)
    complete_tool = ReminderCompleteTool(store=store, scheduler=scheduler)
    postpone_tool = ReminderPostponeTool(store=store, scheduler=scheduler)
    update_tool = ReminderUpdateTool(store=store, scheduler=scheduler)
    delete_tool = ReminderDeleteTool(store=store, scheduler=scheduler)

    return store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool


@pytest.mark.asyncio
async def test_reminder_create_tool_success_and_validation(setup_tools):
    store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool = setup_tools

    # 1. Successful professional task creation
    res1 = await create_tool.execute({
        "work_task": "Machine Learning Project Submission",
        "date": "2nd October 2026",
        "time": "before 11:59 PM",
        "category": "professional",
    })
    assert "I have scheduled your reminder" in res1
    assert "2026-10-02" in res1
    assert "23:59:00" in res1

    # 2. Validation: missing task
    res_err_task = await create_tool.execute({
        "work_task": "",
        "date": "2026-10-02",
    })
    assert "Error:" in res_err_task

    # 3. Validation: missing date
    res_err_date = await create_tool.execute({
        "work_task": "Do homework",
        "date": "",
    })
    assert "Error:" in res_err_date

    # 4. Validation: invalid date (e.g. Feb 31)
    res_err_invalid = await create_tool.execute({
        "work_task": "Invalid Day",
        "date": "31st February 2026",
    })
    assert "Error:" in res_err_invalid


@pytest.mark.asyncio
async def test_reminder_create_birthday_annual_recurrence(setup_tools):
    store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool = setup_tools

    res = await create_tool.execute({
        "work_task": "Dad's Birthday",
        "date": "10th December 2026",
        "time": "09:00 AM",
        "category": "birthday",
    })
    assert "I have scheduled your reminder" in res
    assert "recurring annually" in res

    recs = store.list_active_reminders(category="birthday")
    assert len(recs) == 1
    assert recs[0].is_recurring() is True


@pytest.mark.asyncio
async def test_reminder_list_tool(setup_tools):
    store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool = setup_tools

    # Empty list
    empty_res = await list_tool.execute({"timeframe": "upcoming"})
    assert "no pending reminders" in empty_res

    # Populate
    await create_tool.execute({"work_task": "Task Alpha", "date": "today", "time": "12:00 PM"})
    await create_tool.execute({"work_task": "Task Beta", "date": "tomorrow", "time": "15:00"})

    list_all = await list_tool.execute({"timeframe": "all"})
    assert "Task Alpha" in list_all
    assert "Task Beta" in list_all

    list_today = await list_tool.execute({"timeframe": "today"})
    assert "Task Alpha" in list_today


@pytest.mark.asyncio
async def test_reminder_complete_tool_by_name_and_context(setup_tools):
    store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool = setup_tools

    await create_tool.execute({"work_task": "Submit Tax Return", "date": "2026-10-15"})
    active = store.list_active_reminders()
    assert len(active) == 1
    target = active[0]

    # Complete by keyword
    comp_res = await complete_tool.execute({"task_query": "tax return"})
    assert "marked 'Submit Tax Return' as completed" in comp_res

    # Verify task is no longer active
    assert len(store.list_active_reminders()) == 0

    # Test complete via recently delivered context
    rec2 = store.create_reminder("Review Architecture Draft", "2026-10-20")
    scheduler.last_delivered_reminder_id = rec2.id
    scheduler.last_delivered_at = 1000.0
    import time
    scheduler.last_delivered_at = time.time()

    comp_context = await complete_tool.execute({"task_query": "this task"})
    assert "marked 'Review Architecture Draft' as completed" in comp_context
    assert len(store.list_active_reminders()) == 0


@pytest.mark.asyncio
async def test_reminder_postpone_and_update_tools(setup_tools):
    store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool = setup_tools

    await create_tool.execute({
        "work_task": "Project Deadline",
        "date": "2nd October 2026",
        "time": "11:59 PM",
    })

    # Postpone to 5th October
    post_res = await postpone_tool.execute({
        "task_query": "project deadline",
        "new_date": "5th October 2026",
    })
    assert "postponed to 2026-10-05" in post_res

    rec = store.find_reminders_by_query("project deadline")[0]
    assert rec.date == "2026-10-05"

    # Update task name and category
    up_res = await update_tool.execute({
        "task_query": "project deadline",
        "new_task": "Final Project Deliverable",
        "new_category": "professional",
    })
    assert "Final Project Deliverable" in up_res

    rec_updated = store.find_reminders_by_query("Final Project Deliverable")[0]
    assert rec_updated.work_task == "Final Project Deliverable"


@pytest.mark.asyncio
async def test_reminder_delete_tool(setup_tools):
    store, scheduler, create_tool, list_tool, complete_tool, postpone_tool, update_tool, delete_tool = setup_tools

    await create_tool.execute({"work_task": "Temporary Task", "date": "2026-12-01"})
    assert len(store.list_active_reminders()) == 1

    del_res = await delete_tool.execute({"task_query": "Temporary Task"})
    assert "cancelled the reminder" in del_res
    assert len(store.list_active_reminders()) == 0
