"""
Unit tests for Victor Phone BaseTool classes and ToolRegistry integration.
"""

import pytest
from app.phone.gateway import PhoneGateway
from app.phone.tools import (
    PhoneAnswerCallTool,
    PhoneClearNotificationsTool,
    PhoneGetNotificationsTool,
    PhoneGetStatusTool,
    PhoneInitiateCallTool,
    PhoneLaunchYouTubeTool,
    PhoneRejectCallTool,
    PhoneResolveContactTool,
    PhoneUnpairTool,
)
from app.tools.permissions import PermissionLevel
from app.tools.tool_setup import build_tool_registry


def test_all_phone_tools_permission_safe():
    tools = [
        PhoneGetStatusTool(),
        PhoneResolveContactTool(),
        PhoneInitiateCallTool(),
        PhoneAnswerCallTool(),
        PhoneRejectCallTool(),
        PhoneLaunchYouTubeTool(),
        PhoneUnpairTool(),
        PhoneGetNotificationsTool(),
        PhoneClearNotificationsTool(),
    ]

    for t in tools:
        assert t.permission_level == PermissionLevel.SAFE
        schema = t.get_schema()
        assert "name" in schema
        assert "description" in schema
        assert "parameters" in schema
        assert schema["name"] == t.name


def test_tool_registry_contains_phone_tools():
    registry = build_tool_registry()

    expected = [
        "phone_get_status",
        "phone_resolve_contact",
        "phone_initiate_call",
        "phone_answer_call",
        "phone_reject_call",
        "phone_launch_youtube",
        "phone_unpair",
        "phone_get_notifications",
        "phone_clear_notifications",
    ]

    for name in expected:
        tool = registry.get_tool(name)
        assert tool is not None, f"Tool '{name}' was not found in ToolRegistry"


@pytest.mark.asyncio
async def test_phone_tools_execute_with_gateway():
    class DummyGateway:
        def get_status(self):
            return {"paired": True, "status": "ONLINE", "device_name": "Pixel 8", "battery_level": 92}

        async def resolve_contact(self, contact_name):
            return {"success": True, "message": f"Found {contact_name}"}

        async def initiate_call(self, contact_name, phone_number):
            return {"success": True, "message": f"Calling {contact_name}"}

        async def answer_call(self):
            return {"success": True, "message": "Call answered."}

        async def reject_call(self):
            return {"success": True, "message": "Call rejected."}

        async def launch_youtube(self, query):
            return {"success": True, "message": f"Opened YouTube for {query}"}

        def unpair(self):
            return {"success": True, "message": "Unpaired."}

        def get_recent_notifications(self, limit=10, unread_only=False):
            return [{"source": "WhatsApp", "title": "Alice", "text": "Hey", "package": "com.whatsapp"}]

        def clear_notifications(self):
            return 1

    gw = DummyGateway()

    status_tool = PhoneGetStatusTool(gateway=gw)
    assert "Pixel 8" in await status_tool.execute({})

    resolve_tool = PhoneResolveContactTool(gateway=gw)
    assert "Found Rahul" in await resolve_tool.execute({"contact_name": "Rahul"})

    call_tool = PhoneInitiateCallTool(gateway=gw)
    assert "Calling Rahul" in await call_tool.execute({"contact_name": "Rahul", "phone_number": "+919876543210"})

    answer_tool = PhoneAnswerCallTool(gateway=gw)
    assert "Call answered" in await answer_tool.execute({})

    reject_tool = PhoneRejectCallTool(gateway=gw)
    assert "Call rejected" in await reject_tool.execute({})

    yt_tool = PhoneLaunchYouTubeTool(gateway=gw)
    assert "Opened YouTube for Python" in await yt_tool.execute({"query": "Python"})

    unpair_tool = PhoneUnpairTool(gateway=gw)
    assert "Unpaired" in await unpair_tool.execute({})

    get_notifs_tool = PhoneGetNotificationsTool(gateway=gw)
    assert "recent phone notification" in (await get_notifs_tool.execute({})).lower()

    clear_notifs_tool = PhoneClearNotificationsTool(gateway=gw)
    assert "cleared 1 notification" in (await clear_notifs_tool.execute({})).lower()


@pytest.mark.asyncio
async def test_phone_initiate_call_auto_stages_direct_number():
    """Test that PhoneInitiateCallTool auto-stages approval when a direct valid number is passed."""
    class ApprovalEnforcingGateway:
        def __init__(self):
            self.approved_number = None

        async def resolve_contact(self, query):
            self.approved_number = query
            return {"success": True, "message": f"Staged {query}"}

        async def initiate_call(self, contact_name, phone_number):
            if self.approved_number == phone_number:
                return {"success": True, "message": f"Calling {contact_name} at {phone_number}"}
            return {"success": False, "message": "No approved call request found."}

    gw = ApprovalEnforcingGateway()
    tool = PhoneInitiateCallTool(gateway=gw)

    # Calling directly without prior resolve_contact should auto-stage and succeed
    result = await tool.execute({"contact_name": "Papa", "phone_number": "9997579003"})
    assert "Calling Papa at 9997579003" in result
    assert gw.approved_number == "9997579003"


@pytest.mark.asyncio
async def test_phone_initiate_call_recovers_from_authorization_mismatch():
    """Test that PhoneInitiateCallTool recovers when previous approval was for a different number."""
    class MismatchGateway:
        def __init__(self):
            self.approved_number = "+918630327774"

        async def resolve_contact(self, query):
            self.approved_number = query
            return {"success": True, "message": f"Staged {query}"}

        async def initiate_call(self, contact_name, phone_number):
            if self.approved_number == phone_number:
                return {"success": True, "message": f"Calling {contact_name} at {phone_number}"}
            return {
                "success": False,
                "message": f"Authorization Mismatch: Approved number was {self.approved_number}, but requested {phone_number}.",
            }

    gw = MismatchGateway()
    tool = PhoneInitiateCallTool(gateway=gw)

    # Calling with a new number should auto-re-stage and succeed
    result = await tool.execute({"contact_name": "Papa", "phone_number": "9997579003"})
    assert "Calling Papa at 9997579003" in result
    assert gw.approved_number == "9997579003"


