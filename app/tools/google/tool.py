"""
Google Services Tools for Victor 2.0.

Exposes deterministic Google Keep, Google Calendar, and Google Meet tools
to Gemini Live and Victor's tool execution gateway.
"""

from __future__ import annotations

import logging
from typing import Any, Dict

from app.google_services import (
    GoogleCalendarService,
    GoogleKeepService,
    GoogleMeetService,
    google_services,
)
from app.tools.base import BaseTool
from app.tools.permissions import PermissionLevel

logger = logging.getLogger(__name__)


# ==============================================================================
# 1. GOOGLE KEEP TOOLS
# ==============================================================================
class GoogleKeepCreateNoteTool(BaseTool):
    name = "google_keep_create_note"
    description = (
        "Creates a new note with a title and/or content in Google Keep using Victor's "
        "persistent Chrome browser session."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Optional title for the note (e.g. 'Grocery List', 'Meeting Notes').",
            },
            "content": {
                "type": "string",
                "description": "The text content or body of the note.",
            },
        },
        "required": ["content"],
    }

    async def execute(self, args: dict) -> str:
        title = args.get("title", "")
        content = args.get("content", "")
        service: GoogleKeepService = google_services.get("keep")
        if not service:
            return "Google Keep service is not available."
        return await service.create_note(title=title, content=content)


class GoogleKeepSearchNotesTool(BaseTool):
    name = "google_keep_search_notes"
    description = "Searches Google Keep for existing notes matching a query term or topic."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keyword or topic to search for in Google Keep.",
            }
        },
        "required": ["query"],
    }

    async def execute(self, args: dict) -> str:
        query = args.get("query", "")
        service: GoogleKeepService = google_services.get("keep")
        if not service:
            return "Google Keep service is not available."
        return await service.search_notes(query=query)


class GoogleKeepOpenTool(BaseTool):
    name = "google_keep_open"
    description = "Opens or switches to Google Keep in the browser."
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        service: GoogleKeepService = google_services.get("keep")
        if not service:
            return "Google Keep service is not available."
        return await service.open_keep()


# ==============================================================================
# 2. GOOGLE CALENDAR TOOLS
# ==============================================================================
class GoogleCalendarCreateEventTool(BaseTool):
    name = "google_calendar_create_event"
    description = (
        "Creates a new event in Google Calendar with an explicit title, date, start time, "
        "and optional end time or description. Automatically validates ambiguous dates/times."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "The event title (e.g. 'Project Sync', 'Dentist Appointment').",
            },
            "date": {
                "type": "string",
                "description": "The date of the event (e.g. 'tomorrow', 'Friday', '2026-09-25').",
            },
            "start_time": {
                "type": "string",
                "description": "Start time of the event (e.g. '10:00 AM', '3:30 PM', '14:00').",
            },
            "end_time": {
                "type": "string",
                "description": "Optional end time (defaults to 1 hour after start time).",
            },
            "description": {
                "type": "string",
                "description": "Optional notes or description for the calendar event.",
            },
            "location": {
                "type": "string",
                "description": "Optional physical location or meeting link for the event.",
            },
        },
        "required": ["title", "date", "start_time"],
    }

    async def execute(self, args: dict) -> str:
        title = args.get("title", "")
        date = args.get("date", "")
        start_time = args.get("start_time", "")
        end_time = args.get("end_time")
        description = args.get("description", "")
        location = args.get("location", "")

        service: GoogleCalendarService = google_services.get("calendar")
        if not service:
            return "Google Calendar service is not available."

        return await service.create_event(
            title=title,
            date=date,
            start_time=start_time,
            end_time=end_time,
            description=description,
            location=location,
        )


class GoogleCalendarOpenTool(BaseTool):
    name = "google_calendar_open"
    description = "Opens Google Calendar in the browser, optionally navigating to a specific date."
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "date": {
                "type": "string",
                "description": "Optional date to display in Google Calendar (e.g. 'tomorrow', '2026-09-25').",
            }
        },
    }

    async def execute(self, args: dict) -> str:
        date = args.get("date", "")
        service: GoogleCalendarService = google_services.get("calendar")
        if not service:
            return "Google Calendar service is not available."
        return await service.open_calendar(date_str=date)


# ==============================================================================
# 3. GOOGLE MEET TOOLS
# ==============================================================================
class GoogleMeetCreateTool(BaseTool):
    name = "google_meet_create"
    description = (
        "Creates and launches a new instant Google Meet video meeting in Victor's browser "
        "and returns the generated meeting invitation URL and 10-letter meeting code."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        service: GoogleMeetService = google_services.get("meet")
        if not service:
            return "Google Meet service is not available."
        res = await service.create_meeting()
        return res.get("message", "Created Google Meet.")


class GoogleMeetJoinTool(BaseTool):
    name = "google_meet_join"
    description = (
        "Validates a Google Meet 10-letter code (or full URL) and navigates to the meeting "
        "room in Victor's browser so Anubhav Sir can join."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "meeting_code": {
                "type": "string",
                "description": "The 10-letter Google Meet code (e.g. 'abc-defg-hij') or full meeting URL.",
            }
        },
        "required": ["meeting_code"],
    }

    async def execute(self, args: dict) -> str:
        code_or_url = args.get("meeting_code", "")
        service: GoogleMeetService = google_services.get("meet")
        if not service:
            return "Google Meet service is not available."
        return await service.join_meeting(code_or_url=code_or_url)
