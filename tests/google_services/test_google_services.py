"""
Unit and integration tests for Victor 2.0 Google Services Automation
(Google Keep, Google Calendar, Google Meet) and unified command pipeline.
"""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agent.state import VictorState
from app.google_services import (
    BaseGoogleService,
    GoogleCalendarService,
    GoogleKeepService,
    GoogleMeetService,
    GoogleServiceRegistry,
    google_services,
    parse_date,
    parse_time,
    validate_meet_code,
)
from app.tools.google import (
    GoogleCalendarCreateEventTool,
    GoogleCalendarOpenTool,
    GoogleKeepCreateNoteTool,
    GoogleKeepOpenTool,
    GoogleKeepSearchNotesTool,
    GoogleMeetCreateTool,
    GoogleMeetJoinTool,
)
from app.tools.permissions import PermissionLevel
from app.tools.tool_setup import build_tool_registry


# ==============================================================================
# 1. REGISTRY & EXTENSIBILITY TESTS
# ==============================================================================
def test_google_service_registry():
    reg = GoogleServiceRegistry()

    class MockService(BaseGoogleService):
        name = "drive"
        display_name = "Google Drive"
        base_url = "https://drive.google.com"

    mock_svc = MockService()
    reg.register(mock_svc)

    assert "drive" in reg.list_services()
    assert reg.get("drive") is mock_svc
    assert reg.get("DRIVE") is mock_svc
    assert reg.get("nonexistent") is None


def test_core_services_registered():
    assert google_services.get("keep") is not None
    assert google_services.get("calendar") is not None
    assert google_services.get("meet") is not None


# ==============================================================================
# 2. GOOGLE MEET VALIDATION & SERVICE TESTS
# ==============================================================================
def test_validate_meet_code_valid_formats():
    # 1. Standard with dashes
    ok, code = validate_meet_code("abc-defg-hij")
    assert ok is True
    assert code == "abc-defg-hij"

    # 2. Without dashes
    ok, code = validate_meet_code("abcdefghij")
    assert ok is True
    assert code == "abc-defg-hij"

    # 3. Full URL
    ok, code = validate_meet_code("https://meet.google.com/xyz-pqrs-tuv")
    assert ok is True
    assert code == "xyz-pqrs-tuv"

    # 4. URL with query parameters
    ok, code = validate_meet_code("https://meet.google.com/xyz-pqrs-tuv?authuser=1&hs=179")
    assert ok is True
    assert code == "xyz-pqrs-tuv"


def test_validate_meet_code_invalid_formats():
    # Too short
    ok, err = validate_meet_code("abc")
    assert ok is False
    assert "not a valid Google Meet code" in err

    # Contains numbers (Meet codes are letters only)
    ok, err = validate_meet_code("123-4567-890")
    assert ok is False

    # Empty
    ok, err = validate_meet_code("")
    assert ok is False

    # Generic URL
    ok, err = validate_meet_code("https://google.com")
    assert ok is False


@pytest.mark.asyncio
async def test_meet_create_meeting_success():
    mock_driver = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://meet.google.com/abc-defg-hij"
    mock_driver.new_page = AsyncMock(return_value=mock_page)
    mock_driver.get_pages = AsyncMock(return_value=[])

    service = GoogleMeetService(driver=mock_driver)
    res = await service.create_meeting()

    assert res["success"] is True
    assert res["code"] == "abc-defg-hij"
    assert "https://meet.google.com/abc-defg-hij" in res["url"]
    assert "Created Google Meet" in res["message"]


@pytest.mark.asyncio
async def test_meet_join_meeting_valid():
    mock_driver = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://meet.google.com/abc-defg-hij"
    mock_driver.new_page = AsyncMock(return_value=mock_page)
    mock_driver.get_pages = AsyncMock(return_value=[])

    service = GoogleMeetService(driver=mock_driver)
    res = await service.join_meeting("abc-defg-hij")

    assert "Navigated to Google Meet 'abc-defg-hij'" in res
    assert "pre-join screen is ready" in res.lower()


@pytest.mark.asyncio
async def test_meet_join_meeting_invalid():
    service = GoogleMeetService()
    res = await service.join_meeting("invalid_code_123")
    assert "not a valid Google Meet code" in res


# ==============================================================================
# 3. GOOGLE CALENDAR VALIDATION & SERVICE TESTS
# ==============================================================================
def test_calendar_date_parsing():
    ref_date = datetime.date(2026, 9, 21)  # Monday

    # 1. Today
    d, err = parse_date("today", ref_date=ref_date)
    assert d == datetime.date(2026, 9, 21)
    assert err is None

    # 2. Tomorrow
    d, err = parse_date("tomorrow", ref_date=ref_date)
    assert d == datetime.date(2026, 9, 22)
    assert err is None

    # 3. Weekday (Friday)
    d, err = parse_date("friday", ref_date=ref_date)
    assert d == datetime.date(2026, 9, 25)
    assert err is None

    # 4. Explicit ISO
    d, err = parse_date("2026-10-15", ref_date=ref_date)
    assert d == datetime.date(2026, 10, 15)
    assert err is None

    # 5. Written month and day
    d, err = parse_date("September 28", ref_date=ref_date)
    assert d == datetime.date(2026, 9, 28)
    assert err is None

    # 6. Ambiguous / empty
    d, err = parse_date("some day next week")
    assert d is None
    assert "ambiguous" in err


def test_calendar_time_parsing():
    # 1. Standard AM/PM
    t, err = parse_time("10:00 AM")
    assert t == datetime.time(10, 0)
    assert err is None

    t, err = parse_time("3:30 PM")
    assert t == datetime.time(15, 30)
    assert err is None

    t, err = parse_time("10am")
    assert t == datetime.time(10, 0)
    assert err is None

    # 2. 24-hour format
    t, err = parse_time("14:45")
    assert t == datetime.time(14, 45)
    assert err is None

    # 3. Invalid / Ambiguous
    t, err = parse_time("later today")
    assert t is None
    assert "ambiguous" in err

    t, err = parse_time("25:00")
    assert t is None
    assert "Invalid 24-hour format" in err


@pytest.mark.asyncio
async def test_calendar_create_event_ambiguous_date_rejected():
    service = GoogleCalendarService()
    res = await service.create_event(
        title="Sync Meeting",
        date="sometime next week",
        start_time="10:00 AM",
    )
    assert "ambiguous" in res


@pytest.mark.asyncio
async def test_calendar_create_event_ambiguous_time_rejected():
    service = GoogleCalendarService()
    res = await service.create_event(
        title="Sync Meeting",
        date="tomorrow",
        start_time="afternoon",
    )
    assert "ambiguous" in res


@pytest.mark.asyncio
async def test_calendar_create_event_success():
    mock_driver = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://calendar.google.com/calendar/render"
    mock_locator = AsyncMock()
    mock_locator.first = AsyncMock()
    mock_locator.first.is_visible = AsyncMock(return_value=True)
    mock_locator.first.click = AsyncMock()
    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_driver.new_page = AsyncMock(return_value=mock_page)
    mock_driver.get_pages = AsyncMock(return_value=[])

    service = GoogleCalendarService(driver=mock_driver)
    res = await service.create_event(
        title="Victor Architecture Review",
        date="2026-09-25",
        start_time="10:00 AM",
        end_time="11:00 AM",
        description="Review Google Services implementation",
    )

    assert "Victor Architecture Review" in res
    assert "September 25, 2026" in res
    assert "10:00 AM to 11:00 AM" in res


# ==============================================================================
# 4. GOOGLE KEEP SERVICE TESTS
# ==============================================================================
@pytest.mark.asyncio
async def test_keep_create_note_empty_rejected():
    service = GoogleKeepService()
    res = await service.create_note(title="", content="")
    assert "Cannot create an empty note" in res


@pytest.mark.asyncio
async def test_keep_create_note_success():
    mock_driver = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://keep.google.com"
    mock_locator = AsyncMock()
    mock_locator.first = AsyncMock()
    mock_locator.first.is_visible = AsyncMock(return_value=True)
    mock_locator.first.click = AsyncMock()
    mock_locator.first.fill = AsyncMock()
    mock_page.locator = MagicMock(return_value=mock_locator)
    mock_driver.new_page = AsyncMock(return_value=mock_page)
    mock_driver.get_pages = AsyncMock(return_value=[])

    service = GoogleKeepService(driver=mock_driver)
    res = await service.create_note(
        title="Grocery List",
        content="Milk, Bread, Butter, Eggs",
    )

    assert "Successfully created Google Keep titled 'Grocery List'" in res
    assert "Milk, Bread" in res


@pytest.mark.asyncio
async def test_keep_search_notes():
    mock_driver = MagicMock()
    mock_page = AsyncMock()
    mock_page.url = "https://keep.google.com/#search/text=project%20roadmap"
    mock_driver.new_page = AsyncMock(return_value=mock_page)
    mock_driver.get_pages = AsyncMock(return_value=[])

    service = GoogleKeepService(driver=mock_driver)
    res = await service.search_notes("project roadmap")
    assert "searched for 'project roadmap'" in res


# ==============================================================================
# 5. GOOGLE TOOLS SCHEMAS & PERMISSIONS
# ==============================================================================
def test_all_google_tools_safe_permission():
    tools = [
        GoogleKeepCreateNoteTool(),
        GoogleKeepSearchNotesTool(),
        GoogleKeepOpenTool(),
        GoogleCalendarCreateEventTool(),
        GoogleCalendarOpenTool(),
        GoogleMeetCreateTool(),
        GoogleMeetJoinTool(),
    ]
    for tool in tools:
        assert tool.permission_level == PermissionLevel.SAFE
        schema = tool.get_schema()
        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema


def test_tool_registry_contains_google_tools():
    reg = build_tool_registry()
    expected = [
        "google_keep_create_note",
        "google_keep_search_notes",
        "google_keep_open",
        "google_calendar_create_event",
        "google_calendar_open",
        "google_meet_create",
        "google_meet_join",
    ]
    for name in expected:
        tool = reg.get_tool(name)
        assert tool is not None, f"Tool '{name}' was not found in ToolRegistry."


# ==============================================================================
# 6. UNIFIED COMMAND PIPELINE & SESSION MANAGER TEXT INPUT
# ==============================================================================
@pytest.mark.asyncio
async def test_session_manager_text_command_active_state():
    from app.agent.session_manager import VictorSessionManager

    ws_callback = AsyncMock()
    manager = VictorSessionManager(websocket_send_callback=ws_callback)
    manager.state = VictorState.ACTIVE
    manager._auth_manager.is_unlocked = MagicMock(return_value=True)

    manager.live_session.is_connected = True
    manager.live_session.send_text = AsyncMock()

    ok = await manager.handle_command("Create a Google Meet")
    assert ok is True
    # Verify echo to transcript
    ws_callback.assert_any_call({"type": "transcript", "role": "user", "text": "Create a Google Meet"})
    # Verify dispatched to live_session
    manager.live_session.send_text.assert_called_once_with("Create a Google Meet")


@pytest.mark.asyncio
async def test_session_manager_text_command_biometric_pending():
    from app.agent.session_manager import VictorSessionManager

    ws_callback = AsyncMock()
    manager = VictorSessionManager(websocket_send_callback=ws_callback)
    manager.state = VictorState.BIOMETRIC_PENDING
    manager.trigger_biometric_verification = AsyncMock(return_value=True)

    ok = await manager.handle_command("Join meet abc-defg-hij")
    assert ok is False
    manager.trigger_biometric_verification.assert_called_once_with(command_text="Join meet abc-defg-hij")
