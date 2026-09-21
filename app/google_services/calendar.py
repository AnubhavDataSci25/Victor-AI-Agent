"""
Google Calendar automation service for Victor 2.0.

Provides deterministic event creation, strict date/time ambiguity validation,
and calendar navigation using Victor's persistent Chrome browser profile.
"""

from __future__ import annotations

import asyncio
import datetime
import logging
import re
import urllib.parse
from typing import Any, Dict, Optional, Tuple

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.google_services.base import BaseGoogleService

logger = logging.getLogger(__name__)

# Days of the week mapping
WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

MONTHS = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def parse_date(date_raw: str, ref_date: Optional[datetime.date] = None) -> Tuple[Optional[datetime.date], Optional[str]]:
    """
    Parses a user-supplied date string into a concrete datetime.date.
    Rejects ambiguous dates and returns an explicit clarification message.
    """
    if not date_raw or not date_raw.strip():
        return None, "Date is missing. Please specify a date (e.g. 'tomorrow', 'next Monday', or '2026-09-25')."

    text = date_raw.strip().lower()
    today = ref_date or datetime.date.today()

    if text in ("today", "tod"):
        return today, None
    elif text in ("tomorrow", "tmrw", "tom"):
        return today + datetime.timedelta(days=1), None
    elif text in ("yesterday", "yest"):
        return today - datetime.timedelta(days=1), None

    # Handle relative weekdays (e.g. "monday", "next monday", "this friday")
    clean_text = re.sub(r"^(next|this)\s+", "", text)
    if clean_text in WEEKDAYS:
        target_wd = WEEKDAYS[clean_text]
        days_ahead = (target_wd - today.weekday()) % 7
        if days_ahead == 0 and "next" in text:
            days_ahead = 7
        elif days_ahead == 0:
            days_ahead = 7  # default to next occurrence if today is that day
        return today + datetime.timedelta(days=days_ahead), None

    # Explicit ISO: YYYY-MM-DD
    iso_match = re.match(r"^(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})$", text)
    if iso_match:
        try:
            year, month, day = int(iso_match.group(1)), int(iso_match.group(2)), int(iso_match.group(3))
            return datetime.date(year, month, day), None
        except ValueError:
            return None, f"Invalid calendar date '{date_raw}'."

    # DD/MM/YYYY or DD-MM-YYYY
    dmy_match = re.match(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", text)
    if dmy_match:
        try:
            day, month, year = int(dmy_match.group(1)), int(dmy_match.group(2)), int(dmy_match.group(3))
            return datetime.date(year, month, day), None
        except ValueError:
            return None, f"Invalid calendar date '{date_raw}'."

    # "25 September", "September 25", "Sep 25, 2026"
    words = re.findall(r"[a-z]+|\d+", text)
    if len(words) >= 2:
        month_val = None
        day_val = None
        year_val = today.year

        for w in words:
            if w in MONTHS:
                month_val = MONTHS[w]
            elif w.isdigit():
                val = int(w)
                if val > 1900:
                    year_val = val
                elif day_val is None and 1 <= val <= 31:
                    day_val = val

        if month_val and day_val:
            try:
                candidate = datetime.date(year_val, month_val, day_val)
                if candidate < today and year_val == today.year and "year" not in text:
                    candidate = datetime.date(year_val + 1, month_val, day_val)
                return candidate, None
            except ValueError:
                return None, f"Invalid date values in '{date_raw}'."

    return None, (
        f"The date '{date_raw}' is ambiguous. Please provide a specific date, "
        f"such as 'tomorrow', 'Friday', or in 'YYYY-MM-DD' format."
    )


def parse_time(time_raw: str) -> Tuple[Optional[datetime.time], Optional[str]]:
    """
    Parses a user-supplied time string into a concrete datetime.time.
    Rejects ambiguous times and returns an explicit clarification message.
    """
    if not time_raw or not time_raw.strip():
        return None, "Start time is missing. Please specify a time (e.g. '10:00 AM' or '3:30 PM')."

    text = time_raw.strip().lower()

    # Match standard patterns: "10:30am", "10:30 am", "10am", "10:30", "15:00"
    m = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm)?$", text)
    if not m:
        return None, f"The time '{time_raw}' is ambiguous. Please use formats like '10:00 AM', '3:30 PM', or '15:00'."

    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    meridiem = m.group(3)

    if minute < 0 or minute > 59:
        return None, f"Invalid minutes in time '{time_raw}'."

    if meridiem:
        if hour < 1 or hour > 12:
            return None, f"Invalid 12-hour format in time '{time_raw}'."
        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
    else:
        if hour < 0 or hour > 23:
            return None, f"Invalid 24-hour format in time '{time_raw}'."

    return datetime.time(hour, minute), None


class GoogleCalendarService(BaseGoogleService):
    name = "calendar"
    display_name = "Google Calendar"
    base_url = "https://calendar.google.com"

    async def create_event(
        self,
        title: str,
        date: str,
        start_time: str,
        end_time: Optional[str] = None,
        description: str = "",
        location: str = "",
    ) -> str:
        """
        Creates an event in Google Calendar with strict validation of dates and times.
        Uses Google Calendar's official TEMPLATE render URL scheme to prefill fields,
        then commits the event securely.
        """
        title = (title or "").strip()
        if not title:
            return "Please provide an event title (e.g. 'Team Sync' or 'Doctor Appointment')."

        # 1. Parse and validate date
        parsed_date, date_err = parse_date(date)
        if date_err:
            return date_err

        # 2. Parse and validate start time
        parsed_start, start_err = parse_time(start_time)
        if start_err:
            return start_err

        # 3. Parse and validate end time (defaults to 1 hour after start)
        start_dt = datetime.datetime.combine(parsed_date, parsed_start)
        if end_time and end_time.strip():
            parsed_end, end_err = parse_time(end_time)
            if end_err:
                return end_err
            end_dt = datetime.datetime.combine(parsed_date, parsed_end)
            if end_dt <= start_dt:
                # If end time is earlier, assume it ends next day or prompt
                end_dt += datetime.timedelta(days=1)
        else:
            end_dt = start_dt + datetime.timedelta(hours=1)

        # 4. Construct official Google Calendar ISO date format: YYYYMMDDTHHmmSS
        start_iso = start_dt.strftime("%Y%m%dT%H%M%S")
        end_iso = end_dt.strftime("%Y%m%dT%H%M%S")
        dates_param = f"{start_iso}/{end_iso}"

        # 5. Build official Google Calendar template URL
        params = {
            "action": "TEMPLATE",
            "text": title,
            "dates": dates_param,
        }
        if description:
            params["details"] = description
        if location:
            params["location"] = location

        template_url = f"{self.base_url}/calendar/render?{urllib.parse.urlencode(params)}"

        try:
            page = await self.get_or_create_page(url_keyword="calendar.google.com", target_url=template_url)
            await self.wait_for_ready(page)

            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return auth_msg

            # Wait for event edit interface to load
            await asyncio.sleep(1.2)

            # 6. Automate clicking the 'Save' button
            save_selectors = [
                '#xSaveBu',
                'button:has-text("Save")',
                'div[role="button"]:has-text("Save")',
                '[aria-label="Save"]',
                '[aria-label*="Save"]',
            ]
            saved = False
            for s_sel in save_selectors:
                try:
                    s_loc = page.locator(s_sel).first
                    if await s_loc.is_visible(timeout=1500):
                        await s_loc.click()
                        saved = True
                        break
                except Exception:
                    continue

            await asyncio.sleep(1.0)

            formatted_date_str = start_dt.strftime("%A, %B %d, %Y")
            formatted_time_range = f"{start_dt.strftime('%I:%M %p').lstrip('0')} to {end_dt.strftime('%I:%M %p').lstrip('0')}"

            status_note = "saved and added to your calendar" if saved else "pre-filled on screen for confirmation"
            return (
                f"Successfully {status_note}: '{title}' on {formatted_date_str} from {formatted_time_range}."
            )

        except Exception as e:
            logger.error(f"[GoogleCalendarService] Error creating event: {e}")
            return f"Failed to create Google Calendar event: {str(e)}"

    async def open_calendar(self, date_str: str = "") -> str:
        """Opens Google Calendar in the browser."""
        try:
            target_url = self.base_url
            if date_str:
                p_date, _ = parse_date(date_str)
                if p_date:
                    target_url = f"{self.base_url}/calendar/r/day/{p_date.year}/{p_date.month}/{p_date.day}"

            page = await self.get_or_create_page(url_keyword="calendar.google.com", target_url=target_url)
            await self.wait_for_ready(page)
            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return auth_msg
            return "Opened Google Calendar."
        except Exception as e:
            return f"Failed to open Google Calendar: {str(e)}"
