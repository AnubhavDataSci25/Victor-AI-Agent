"""
Integration tests for Victor's Real-Time Date & Reminder System:
End-to-end execution through ToolGateway, conversational response handling
in VictorSessionManager ('Completed', 'No, not yet'), restart resilience, and overdue policies.
"""

import asyncio
from pathlib import Path
import time
from unittest.mock import AsyncMock, MagicMock
from google.genai import types
import pytest

from app.agent.session_manager import VictorSessionManager
from app.agent.state import VictorState
from app.gateway.tool_gateway import ToolGateway
from app.reminders.datetime_utils import calculate_next_milestone_schedule, resolve_timezone
from app.reminders.models import ReminderRecord, ReminderStatus
from app.reminders.scheduler import ReminderScheduler
from app.reminders.store import ReminderStore
from app.tools.registry import ToolRegistry
from app.tools.reminders.tool import (
    ReminderCompleteTool,
    ReminderCreateTool,
    ReminderListTool,
    ReminderPostponeTool,
)


@pytest.fixture
def integration_env(tmp_path: Path):
    db_file = tmp_path / "reminders_integration.db"
    store = ReminderStore(db_path=str(db_file))
    scheduler = ReminderScheduler(store=store, max_idle_sleep=0.1)

    registry = ToolRegistry()
    registry.register(ReminderCreateTool(store=store, scheduler=scheduler))
    registry.register(ReminderListTool(store=store))
    registry.register(ReminderCompleteTool(store=store, scheduler=scheduler))
    registry.register(ReminderPostponeTool(store=store, scheduler=scheduler))

    gateway = ToolGateway(registry=registry)

    mock_ws = AsyncMock()
    session_manager = VictorSessionManager(websocket_send_callback=mock_ws)
    session_manager.state = VictorState.ACTIVE
    session_manager.is_authenticated = MagicMock(return_value=True)
    session_manager.reminder_scheduler = scheduler

    return store, scheduler, gateway, session_manager, mock_ws


@pytest.mark.asyncio
async def test_tool_gateway_reminder_execution_flow(integration_env):
    """Verify ToolGateway routes and executes reminder tools with verified results."""
    store, scheduler, gateway, session_manager, mock_ws = integration_env

    # 1. Execute reminder_create via gateway
    fc_create = types.FunctionCall(
        name="reminder_create",
        args={
            "work_task": "Project Deadline",
            "date": "2nd October 2026",
            "time": "before 11:59 PM",
            "category": "professional",
        },
        id="call-rem-1",
    )
    resp1 = await gateway.execute_function_call(fc_create, session_manager=session_manager)
    assert resp1.response["status"] == "success"
    assert "2026-10-02" in resp1.response["result"]
    assert "23:59:00" in resp1.response["result"]

    # 2. Execute reminder_list via gateway
    fc_list = types.FunctionCall(
        name="reminder_list",
        args={"timeframe": "all"},
        id="call-rem-2",
    )
    resp2 = await gateway.execute_function_call(fc_list, session_manager=session_manager)
    assert resp2.response["status"] == "success"
    assert "Project Deadline" in resp2.response["result"]

    # 3. Execute reminder_complete via gateway
    fc_comp = types.FunctionCall(
        name="reminder_complete",
        args={"task_query": "project deadline"},
        id="call-rem-3",
    )
    resp3 = await gateway.execute_function_call(fc_comp, session_manager=session_manager)
    assert resp3.response["status"] == "success"
    assert "marked 'Project Deadline' as completed" in resp3.response["result"]

    # Check store shows completed & archived
    active = store.list_active_reminders()
    assert len(active) == 0


@pytest.mark.asyncio
async def test_conversational_response_completed_and_pending(integration_env):
    """
    Verify that saying 'Completed' or 'No, not yet' after Victor issues a reminder
    deterministically updates the task without requiring an LLM call.
    """
    store, scheduler, gateway, session_manager, mock_ws = integration_env

    # Create a task in the store
    rec = store.create_reminder(
        work_task="Submit Physics Assignment",
        date_str="today",
        time_str="23:59",
    )

    # Deliver a proactive reminder
    now = time.time()
    await scheduler._deliver_reminder(rec, now)
    assert scheduler.last_delivered_reminder_id == rec.id

    # 1. User says "No, not yet"
    res_pending = await session_manager.handle_command("No, not yet")
    assert res_pending is True

    # Check task is still pending in store
    loaded_pending = store.get_reminder(rec.id)
    assert loaded_pending.status == ReminderStatus.PENDING

    # 2. Simulate next reminder delivery
    await scheduler._deliver_reminder(rec, now + 10.0)

    # User says "Completed"
    res_completed = await session_manager.handle_command("Completed")
    assert res_completed is True

    # Check task is completed and archived
    loaded_done = store.get_reminder(rec.id)
    assert loaded_done.status == ReminderStatus.COMPLETED
    assert loaded_done.is_archived is True


@pytest.mark.asyncio
async def test_restart_resilience_and_overdue_scheduling(tmp_path: Path):
    """
    Simulate full Victor shutdown and restart:
    Ensure pending schedules survive restart, indexes work, and overdue tasks trigger.
    """
    db_file = tmp_path / "reminders_restart.db"

    # --- Session 1: Create reminders and terminate ---
    store1 = ReminderStore(db_path=str(db_file))
    r1 = store1.create_reminder("Annual Review", "2026-10-02", "11:59 PM", "professional")
    r2 = store1.create_reminder("Friend's Wedding Anniversary", "15th August 2026", "10:00 AM", "anniversary")

    due_r1 = r1.due_datetime
    id_r1 = r1.id
    id_r2 = r2.id

    # Simulate shutdown
    del store1

    # --- Session 2: Victor restarts ---
    store2 = ReminderStore(db_path=str(db_file))
    reloaded_r1 = store2.get_reminder(id_r1)
    reloaded_r2 = store2.get_reminder(id_r2)

    assert reloaded_r1 is not None
    assert reloaded_r1.work_task == "Annual Review"
    assert reloaded_r1.due_datetime == due_r1
    assert reloaded_r1.status == ReminderStatus.PENDING

    assert reloaded_r2 is not None
    assert reloaded_r2.is_recurring() is True

    # Test overdue behavior: if time is past due_datetime and task pending
    now_past_due = due_r1 + 86400.0  # 1 day after due date
    tz = resolve_timezone(reloaded_r1.timezone)
    next_ts, plan = calculate_next_milestone_schedule(
        reloaded_r1.due_datetime,
        tz,
        delivered_milestones=["3_days_before", "2_days_before", "1_day_before", "same_day_due"],
        reference_now=now_past_due,
    )
    # Next milestone must be overdue
    assert "overdue_1_day" in plan
    assert next_ts is not None
