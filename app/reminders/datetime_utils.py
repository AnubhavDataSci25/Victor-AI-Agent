"""
Date and Time utilities for Victor's Real-Time Date & Reminder System.
Accurate timezone-aware calculations, leap-year handling, deterministic scheduling,
and robust natural-language date/time parsing without external dependencies.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time as dtime, timedelta, timezone, tzinfo
import logging
import re
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Common timezone offset fallbacks for systems without tzdata package
OFFSET_FALLBACKS: Dict[str, timezone] = {
    "asia/kolkata": timezone(timedelta(hours=5, minutes=30), name="IST"),
    "ist": timezone(timedelta(hours=5, minutes=30), name="IST"),
    "india": timezone(timedelta(hours=5, minutes=30), name="IST"),
    "utc": timezone.utc,
    "gmt": timezone.utc,
    "america/new_york": timezone(timedelta(hours=-5), name="EST"),
    "est": timezone(timedelta(hours=-5), name="EST"),
    "edt": timezone(timedelta(hours=-4), name="EDT"),
    "america/chicago": timezone(timedelta(hours=-6), name="CST"),
    "cst": timezone(timedelta(hours=-6), name="CST"),
    "cdt": timezone(timedelta(hours=-5), name="CDT"),
    "america/denver": timezone(timedelta(hours=-7), name="MST"),
    "mst": timezone(timedelta(hours=-7), name="MST"),
    "mdt": timezone(timedelta(hours=-6), name="MDT"),
    "america/los_angeles": timezone(timedelta(hours=-8), name="PST"),
    "pst": timezone(timedelta(hours=-8), name="PST"),
    "pdt": timezone(timedelta(hours=-7), name="PDT"),
    "europe/london": timezone.utc,
    "bst": timezone(timedelta(hours=1), name="BST"),
    "europe/paris": timezone(timedelta(hours=1), name="CET"),
    "cet": timezone(timedelta(hours=1), name="CET"),
    "cest": timezone(timedelta(hours=2), name="CEST"),
    "asia/tokyo": timezone(timedelta(hours=9), name="JST"),
    "jst": timezone(timedelta(hours=9), name="JST"),
    "australia/sydney": timezone(timedelta(hours=10), name="AEST"),
    "aest": timezone(timedelta(hours=10), name="AEST"),
}

MONTH_MAP: Dict[str, int] = {
    "jan": 1, "january": 1,
    "feb": 2, "february": 2,
    "mar": 3, "march": 3,
    "apr": 4, "april": 4,
    "may": 5,
    "jun": 6, "june": 6,
    "jul": 7, "july": 7,
    "aug": 8, "august": 8,
    "sep": 9, "september": 9, "sept": 9,
    "oct": 10, "october": 10,
    "nov": 11, "november": 11,
    "dec": 12, "december": 12,
}


def get_default_timezone() -> tzinfo:
    """Return default timezone (system local timezone or Asia/Kolkata fallback)."""
    try:
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is not None:
            return local_tz
    except Exception:
        pass
    return OFFSET_FALLBACKS["asia/kolkata"]


def resolve_timezone(tz_name: Optional[str]) -> tzinfo:
    """Resolve a timezone string or alias to a valid tzinfo instance."""
    if not tz_name or not tz_name.strip():
        return get_default_timezone()

    cleaned = tz_name.strip().lower()

    # Try ZoneInfo first if tzdata is present
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tz_name.strip())
    except Exception:
        pass

    # Check offset fallbacks
    if cleaned in OFFSET_FALLBACKS:
        return OFFSET_FALLBACKS[cleaned]

    # Check system local timezone
    local_tz = get_default_timezone()
    local_name = str(local_tz).lower()
    if cleaned in local_name or local_name in cleaned:
        return local_tz

    logger.warning(f"Unrecognized timezone '{tz_name}', defaulting to local timezone.")
    return local_tz


def parse_time_str(time_str: Optional[str], default_for_deadline: bool = False) -> dtime:
    """
    Parses a time string like '11:59 PM', 'before 11:59 PM', 'at 5:30 PM', '14:00', 'noon'.
    Returns datetime.time object.
    """
    if not time_str or not time_str.strip():
        return dtime(23, 59, 0) if default_for_deadline else dtime(9, 0, 0)

    clean = time_str.lower().strip()
    clean = re.sub(r"^(before|by|at|around)\s+", "", clean).strip()

    if clean in ("noon", "midday"):
        return dtime(12, 0, 0)
    if clean in ("midnight", "end of day"):
        return dtime(23, 59, 0)

    # 12-hour format with AM/PM (e.g. 11:59 pm, 9am, 5:30 pm)
    m12 = re.match(r"^(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)$", clean)
    if m12:
        hour = int(m12.group(1))
        minute = int(m12.group(2) or 0)
        second = int(m12.group(3) or 0)
        meridiem = m12.group(4)

        if hour < 1 or hour > 12 or minute > 59 or second > 59:
            raise ValueError(f"Invalid time format: {time_str}")

        if meridiem == "pm" and hour != 12:
            hour += 12
        elif meridiem == "am" and hour == 12:
            hour = 0
        return dtime(hour, minute, second)

    # 24-hour format (e.g. 23:59, 09:00:00, 14:30)
    m24 = re.match(r"^(\d{1,2}):(\d{2})(?::(\d{2}))?$", clean)
    if m24:
        hour = int(m24.group(1))
        minute = int(m24.group(2))
        second = int(m24.group(3) or 0)
        if hour > 23 or minute > 59 or second > 59:
            raise ValueError(f"Invalid 24-hour time: {time_str}")
        return dtime(hour, minute, second)

    # Simple hour only (e.g. "9", "18")
    if clean.isdigit():
        h = int(clean)
        if 0 <= h <= 23:
            return dtime(h, 0, 0)

    raise ValueError(f"Could not parse time: '{time_str}'. Please provide in format HH:MM AM/PM or HH:MM.")


def parse_date_str(date_str: str, tz: tzinfo, reference_now: Optional[datetime] = None) -> date:
    """
    Parses natural language or ISO date strings.
    Examples:
    - '2026-10-02'
    - '2nd October 2026', 'October 2, 2026', '2 Oct 2026'
    - '5th October' (uses current or next year)
    - 'today', 'tomorrow', 'day after tomorrow'
    - 'in 3 days', 'in 2 weeks'
    """
    now = reference_now or datetime.now(tz)
    today = now.date()
    clean = (date_str or "").strip().lower()

    if not clean:
        raise ValueError("Date string cannot be empty.")

    # 1. Relative keywords
    if clean == "today":
        return today
    if clean == "tomorrow":
        return today + timedelta(days=1)
    if clean in ("day after tomorrow", "day after tmrw"):
        return today + timedelta(days=2)

    # 2. Relative offsets: "in X days" / "in X weeks"
    rel_match = re.match(r"^in\s+(\d+)\s+(day|days|week|weeks|month|months)$", clean)
    if rel_match:
        count = int(rel_match.group(1))
        unit = rel_match.group(2)
        if "day" in unit:
            return today + timedelta(days=count)
        if "week" in unit:
            return today + timedelta(weeks=count)
        if "month" in unit:
            return today + timedelta(days=count * 30)

    # 3. ISO format: YYYY-MM-DD
    if re.match(r"^\d{4}-\d{2}-\d{2}$", clean):
        parts = clean.split("-")
        return date(int(parts[0]), int(parts[1]), int(parts[2]))

    # 4. Formats like "2nd October 2026", "2 October 2026", "October 2, 2026", "2nd October"
    normalized = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", clean)
    normalized = normalized.replace(",", " ").strip()

    tokens = [t for t in re.split(r"[\s/-]+", normalized) if t]

    day_val: Optional[int] = None
    month_val: Optional[int] = None
    year_val: Optional[int] = None

    for token in tokens:
        if token in MONTH_MAP:
            month_val = MONTH_MAP[token]
        elif token.isdigit():
            val = int(token)
            if val > 1900 and year_val is None:
                year_val = val
            elif 1 <= val <= 31 and day_val is None:
                day_val = val
            elif year_val is None:
                if val < 100:
                    year_val = 2000 + val

    if day_val is not None and month_val is not None:
        if year_val is None:
            cand = date(today.year, month_val, day_val)
            year_val = today.year if cand >= today else today.year + 1
        return date(year_val, month_val, day_val)

    # 5. DD/MM/YYYY or MM/DD/YYYY
    slash_match = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})$", clean)
    if slash_match:
        p1, p2, p3 = int(slash_match.group(1)), int(slash_match.group(2)), int(slash_match.group(3))
        y = p3 if p3 > 100 else 2000 + p3
        if 1 <= p2 <= 12 and 1 <= p1 <= 31:
            return date(y, p2, p1)

    raise ValueError(
        f"Could not parse date: '{date_str}'. Please provide in format 'YYYY-MM-DD' or '2nd October 2026'."
    )


def combine_date_time_to_epoch(
    d: date,
    t: dtime,
    tz: tzinfo,
) -> float:
    """Combines a date and time in a specific timezone to a UTC Unix epoch timestamp."""
    dt = datetime.combine(d, t, tzinfo=tz)
    return dt.timestamp()


def calculate_next_milestone_schedule(
    due_datetime: float,
    tz: tzinfo,
    delivered_milestones: List[str],
    reference_now: Optional[float] = None,
) -> Tuple[Optional[float], List[str]]:
    """
    Calculates the proactive low-noise reminder schedule:
    - 3 days before (09:00:00 local time)
    - 2 days before (09:00:00 local time)
    - 1 day before (09:00:00 local time)
    - Same day morning (09:00:00 local time, if due time is after 10:00 AM)
    - Due time (exact due_datetime)
    - Overdue (1 day after due date at 10:00:00 local time)

    Returns:
    - next_reminder_at: Unix epoch timestamp for the earliest upcoming milestone, or None
    - full_milestone_plan: List of milestone identifiers
    """
    now = reference_now if reference_now is not None else datetime.now(tz).timestamp()
    due_dt = datetime.fromtimestamp(due_datetime, tz=tz)

    milestones: List[Tuple[str, float]] = []

    # 1. 3 days before
    m3 = (due_dt - timedelta(days=3)).replace(hour=9, minute=0, second=0, microsecond=0)
    if m3 < due_dt:
        milestones.append(("3_days_before", m3.timestamp()))

    # 2. 2 days before
    m2 = (due_dt - timedelta(days=2)).replace(hour=9, minute=0, second=0, microsecond=0)
    if m2 < due_dt:
        milestones.append(("2_days_before", m2.timestamp()))

    # 3. 1 day before
    m1 = (due_dt - timedelta(days=1)).replace(hour=9, minute=0, second=0, microsecond=0)
    if m1 < due_dt:
        milestones.append(("1_day_before", m1.timestamp()))

    # 4. Same day morning (if due time is later than 10:00 AM)
    if due_dt.hour >= 10:
        m_morning = due_dt.replace(hour=9, minute=0, second=0, microsecond=0)
        milestones.append(("same_day_morning", m_morning.timestamp()))

    # 5. Exact due time
    milestones.append(("same_day_due", due_datetime))

    # 6. Overdue (1 day after due date at 10:00 AM)
    m_overdue = (due_dt + timedelta(days=1)).replace(hour=10, minute=0, second=0, microsecond=0)
    milestones.append(("overdue_1_day", m_overdue.timestamp()))

    # Sort milestones chronologically
    milestones.sort(key=lambda x: x[1])

    full_plan = [name for name, _ in milestones]

    for name, ts in milestones:
        if name in delivered_milestones:
            continue
        if ts >= (now - 60.0):
            return ts, full_plan

    # If all regular milestones are in the past, but overdue has not fired
    if "overdue_1_day" not in delivered_milestones and now > due_datetime:
        overdue_ts = m_overdue.timestamp()
        if overdue_ts <= now:
            return now, full_plan
        return overdue_ts, full_plan

    # If already past overdue milestone and still not delivered
    if now > due_datetime and "overdue_1_day" not in delivered_milestones:
        return now, full_plan

    return None, full_plan


def advance_annual_event(
    d: date,
    t: dtime,
    tz: tzinfo,
) -> Tuple[date, float]:
    """
    Advances an annual event (e.g. birthday, anniversary) by one year,
    safely handling February 29 on leap years.
    Returns:
    - new_date (date object for next year)
    - new_due_datetime (Unix epoch timestamp)
    """
    next_year = d.year + 1
    if d.month == 2 and d.day == 29:
        if not calendar.isleap(next_year):
            new_d = date(next_year, 2, 28)
        else:
            new_d = date(next_year, 2, 29)
    else:
        new_d = date(next_year, d.month, d.day)

    new_epoch = combine_date_time_to_epoch(new_d, t, tz)
    return new_d, new_epoch


def format_friendly_reminder_message(
    task: str,
    date_str: str,
    time_str: str,
    is_overdue: bool = False,
    milestone: str = "",
) -> str:
    """Generate professional, courteous natural-language reminder text for Victor."""
    if is_overdue or milestone.startswith("overdue"):
        return f"Sir, your task '{task}' was due on {date_str} at {time_str} and is currently pending."

    if milestone == "3_days_before":
        prefix = "Sir, as an advance notice, your task"
        timing_note = f"is due in 3 days on {date_str} at {time_str}"
    elif milestone == "2_days_before":
        prefix = "Sir, your task"
        timing_note = f"is due in 2 days on {date_str} at {time_str}"
    elif milestone == "1_day_before":
        prefix = "Sir, urgent reminder: your task"
        timing_note = f"is due tomorrow on {date_str} at {time_str}"
    elif milestone == "same_day_morning":
        prefix = "Sir, your task"
        timing_note = f"is pending and the deadline is today, {date_str} at {time_str}"
    elif milestone == "same_day_due":
        prefix = "Sir, your task"
        timing_note = f"has reached its deadline: {date_str} at {time_str}"
    else:
        prefix = "Sir, your task"
        timing_note = f"is pending and the last date is {date_str} at {time_str}"

    return f"{prefix} '{task}' {timing_note}. Would you like me to mark it completed or postpone it?"
