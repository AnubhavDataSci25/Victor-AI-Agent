"""
Victor 2.0 BaseTool implementations for Phone Integration V1.
All phone actions delegate directly to the deterministic PhoneGateway.
"""

from __future__ import annotations

import json
from typing import Any

from app.phone.gateway import PhoneGateway
from app.phone.server import phone_server
from app.tools.base import BaseTool
from app.tools.permissions import PermissionLevel


class PhoneGetStatusTool(BaseTool):
    name = "phone_get_status"
    description = (
        "Checks the connection status, paired device name, battery level, and charging status "
        "of the paired Android phone companion."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        res = self.gateway.get_status()
        if not res.get("paired"):
            return "Sir, no phone is currently paired with Victor. You can initiate pairing from the Victor HUD UI."

        status = res.get("status")
        device_name = res.get("device_name", "Android Phone")
        battery = res.get("battery_level")
        charging = res.get("is_charging")

        battery_info = f", battery is at {battery}%" if battery is not None else ""
        charging_info = " (charging)" if charging else ""

        if status == "ONLINE":
            return f"Sir, your companion phone '{device_name}' is connected and online{battery_info}{charging_info}."
        else:
            return f"Sir, your paired phone '{device_name}' is currently offline."


class PhoneResolveContactTool(BaseTool):
    name = "phone_resolve_contact"
    description = (
        "Queries contacts on the paired Android phone to find a contact by name before making a call. "
        "Returns matched phone numbers or ambiguity details. Always use this first when the user asks "
        "to call someone by name."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "contact_name": {
                "type": "string",
                "description": "The name or partial name of the contact to look up (e.g. 'Rahul', 'Dad', 'John').",
            }
        },
        "required": ["contact_name"],
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        contact_name = args.get("contact_name", "")
        res = await self.gateway.resolve_contact(contact_name)
        return res.get("message", "Contact lookup complete.")


class PhoneInitiateCallTool(BaseTool):
    name = "phone_initiate_call"
    description = (
        "Initiates an outgoing phone call on the paired Android phone after resolving the contact "
        "and obtaining the user's explicit verbal or typed confirmation. "
        "NEVER call this tool without asking the user for confirmation first!"
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "contact_name": {
                "type": "string",
                "description": "The name of the contact being called.",
            },
            "phone_number": {
                "type": "string",
                "description": "The exact phone number to dial (e.g. '+919876543210').",
            },
        },
        "required": ["contact_name", "phone_number"],
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        contact_name = args.get("contact_name", "")
        phone_number = args.get("phone_number", "")
        res = await self.gateway.initiate_call(contact_name, phone_number)
        return res.get("message", "Call initiation complete.")


class PhoneAnswerCallTool(BaseTool):
    name = "phone_answer_call"
    description = (
        "Answers an actively ringing incoming phone call on the paired Android phone. "
        "Use this when the user says 'Pick the call', 'Answer the phone', or 'Pick up'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        res = await self.gateway.answer_call()
        return res.get("message", "Incoming call answered.")


class PhoneRejectCallTool(BaseTool):
    name = "phone_reject_call"
    description = (
        "Rejects or dismisses an actively ringing incoming phone call on the paired Android phone. "
        "Use this when the user says 'Reject the call', 'Decline', 'Drop the call', or 'Ignore the call'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        res = await self.gateway.reject_call()
        return res.get("message", "Incoming call rejected.")


class PhoneLaunchYouTubeTool(BaseTool):
    name = "phone_launch_youtube"
    description = (
        "Launches the YouTube app on the paired Android phone, optionally searching for a video or topic. "
        "Use when the user asks to open YouTube or search for videos on their phone."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Optional search term to search on YouTube (e.g. 'Python tutorials', 'lo-fi beats').",
            }
        },
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        query = args.get("query", "")
        res = await self.gateway.launch_youtube(query)
        return res.get("message", "YouTube launch complete.")


class PhoneUnpairTool(BaseTool):
    name = "phone_unpair"
    description = (
        "Immediately unpairs and revokes access for the paired Android companion phone."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        res = self.gateway.unpair()
        return res.get("message", "Phone unpairing complete.")
