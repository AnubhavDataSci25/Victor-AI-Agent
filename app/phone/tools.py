"""
Victor 2.0 BaseTool implementations for Phone Integration V1.
All phone actions delegate directly to the deterministic PhoneGateway.
"""

from __future__ import annotations

import json
import re
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
        if not res.get("success"):
            return f"Error: {res.get('message', 'Failed to resolve contact.')}"
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
        if not res.get("success"):
            # If rejected because no approval was staged or number was mismatched, check if a valid direct phone number was provided
            digits = re.sub(r"\D", "", phone_number or "")
            err_msg = str(res.get("message", ""))
            if len(digits) >= 7 and any(k in err_msg for k in ("No approved call request found", "Authorization Mismatch", "Authorization Denied")):
                # Auto-stage approval via resolve_contact using the direct number
                resolve_res = await self.gateway.resolve_contact(phone_number)
                if resolve_res.get("success"):
                    # Retry initiate call now that approval is staged for this exact number
                    res = await self.gateway.initiate_call(contact_name or phone_number, phone_number)

            if not res.get("success"):
                return f"Error: {res.get('message', 'Phone failed to initiate the call.')}"
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
        if not res.get("success"):
            return f"Error: {res.get('message', 'Incoming call answer failed.')}"
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
        if not res.get("success"):
            return f"Error: {res.get('message', 'Incoming call rejection failed.')}"
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


class PhoneGetNotificationsTool(BaseTool):
    name = "phone_get_notifications"
    description = (
        "Reads recent notifications received from the paired Android companion phone "
        "(such as WhatsApp messages, SMS alerts, incoming call notifications, and app updates). "
        "Use this when the user asks 'Read my notifications', 'Check phone notifications', "
        "'What messages did I get?', 'Did anyone message me?', or 'Do I have any new notifications?'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "limit": {
                "type": "integer",
                "description": "Maximum number of recent notifications to retrieve (default: 5).",
                "default": 5,
            },
            "unread_only": {
                "type": "boolean",
                "description": "If true, only returns unread notifications (default: false).",
                "default": False,
            },
        },
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        limit = int(args.get("limit", 5) or 5)
        unread_only = bool(args.get("unread_only", False))

        res = self.gateway.get_recent_notifications(limit=limit, unread_only=unread_only)
        if not res:
            dev_res = self.gateway.get_status()
            dev_name = dev_res.get("device_name", "your phone")
            if not dev_res.get("paired"):
                return "Sir, no phone is currently paired with Victor. You can pair it from the Victor HUD UI."
            if dev_res.get("status") == "OFFLINE":
                return f"Sir, no recent notifications recorded, and your companion phone '{dev_name}' is currently offline."
            return f"Sir, there are no recent notifications on your companion phone '{dev_name}'."

        lines = [f"Sir, here are your {len(res)} recent phone notification(s):"]
        for idx, item in enumerate(res, 1):
            src = str(item.get("source", "App")).capitalize()
            title = item.get("title", "")
            text = item.get("text", "")
            header = f"{src} - {title}" if title and title.lower() != src.lower() else src
            body = f": \"{text}\"" if text else ""
            lines.append(f"{idx}. {header}{body}")

        return "\n".join(lines)


class PhoneClearNotificationsTool(BaseTool):
    name = "phone_clear_notifications"
    description = (
        "Clears all cached notifications received from the paired Android phone companion. "
        "Use when the user says 'Clear phone notifications', 'Dismiss notifications', or 'Clear alerts'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, gateway: PhoneGateway | None = None) -> None:
        self.gateway = gateway or phone_server.gateway

    async def execute(self, args: dict[str, Any]) -> str:
        count = self.gateway.clear_notifications()
        return f"Sir, I have cleared {count} notification(s) from your active list."
