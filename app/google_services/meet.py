"""
Google Meet automation service for Victor 2.0.

Provides meeting creation, invite URL extraction, meeting code syntax validation,
and seamless meeting joining using Victor's persistent Chrome browser profile.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any, Dict, Optional, Tuple

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.google_services.base import BaseGoogleService

logger = logging.getLogger(__name__)

# Standard Google Meet code: 3 letters, 4 letters, 3 letters
MEET_CODE_REGEX = re.compile(r"^[a-z]{3}-?[a-z]{4}-?[a-z]{3}$", re.IGNORECASE)
MEET_URL_REGEX = re.compile(r"meet\.google\.com/([a-z]{3}-[a-z]{4}-[a-z]{3})", re.IGNORECASE)


def validate_meet_code(raw: str) -> Tuple[bool, str]:
    """
    Validates and formats a Google Meet code or URL.
    Returns (is_valid, formatted_code_or_error).
    """
    if not raw or not raw.strip():
        return False, "Please provide a Google Meet code (e.g. 'abc-defg-hij') or meeting URL."

    cleaned = raw.strip()

    # Extract code from full URL if provided
    url_match = MEET_URL_REGEX.search(cleaned)
    if url_match:
        return True, url_match.group(1).lower()

    # Clean non-alphanumeric except hyphen
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^meet\.google\.com/", "", cleaned)
    cleaned = cleaned.split("?")[0].strip().lower()

    if not MEET_CODE_REGEX.match(cleaned):
        return False, (
            f"'{raw}' is not a valid Google Meet code. "
            f"Google Meet codes consist of 10 letters in 'xxx-yyyy-zzz' format (e.g. 'abc-defg-hij')."
        )

    # Format into xxx-yyyy-zzz with dashes
    raw_letters = cleaned.replace("-", "")
    if len(raw_letters) == 10:
        formatted = f"{raw_letters[0:3]}-{raw_letters[3:7]}-{raw_letters[7:10]}"
        return True, formatted

    return False, f"Invalid code format: '{raw}'"


class GoogleMeetService(BaseGoogleService):
    name = "meet"
    display_name = "Google Meet"
    base_url = "https://meet.google.com"

    async def create_meeting(self) -> Dict[str, Any]:
        """
        Launches a new instant Google Meet and extracts the generated meeting URL and code.
        """
        try:
            # Open meet.google.com/new to instantiate a new instant meeting
            page = await self.get_or_create_page(url_keyword="meet.google.com/new", target_url=f"{self.base_url}/new")
            await self.wait_for_ready(page)

            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return {"success": False, "message": auth_msg}

            # Poll for the URL to change to meet.google.com/xxx-yyyy-zzz
            meeting_url = ""
            meeting_code = ""

            for _ in range(25):  # Wait up to 7.5 seconds
                current_url = page.url
                match = MEET_URL_REGEX.search(current_url)
                if match:
                    meeting_code = match.group(1).lower()
                    meeting_url = f"https://meet.google.com/{meeting_code}"
                    break
                await asyncio.sleep(0.3)

            if not meeting_url:
                # If still on /new or landing page, inspect page content or links
                try:
                    content = await page.content()
                    match = MEET_URL_REGEX.search(content)
                    if match:
                        meeting_code = match.group(1).lower()
                        meeting_url = f"https://meet.google.com/{meeting_code}"
                except Exception:
                    pass

            if meeting_url:
                return {
                    "success": True,
                    "url": meeting_url,
                    "code": meeting_code,
                    "message": f"Created Google Meet! Link: {meeting_url} (Meeting Code: {meeting_code}). Room is open and ready.",
                }
            else:
                return {
                    "success": True,
                    "url": page.url,
                    "code": "",
                    "message": f"Opened Google Meet at {page.url}. Pre-join screen is loading.",
                }

        except Exception as e:
            logger.error(f"[GoogleMeetService] Error creating meeting: {e}")
            return {
                "success": False,
                "message": f"Failed to create Google Meet: {str(e)}",
            }

    async def join_meeting(self, code_or_url: str) -> str:
        """
        Validates the meeting code or URL and navigates to the meeting room in the browser.
        """
        is_valid, validated_code = validate_meet_code(code_or_url)
        if not is_valid:
            return validated_code

        target_url = f"https://meet.google.com/{validated_code}"

        try:
            page = await self.get_or_create_page(url_keyword=validated_code, target_url=target_url)
            await self.wait_for_ready(page)

            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return auth_msg

            await asyncio.sleep(1.0)
            return f"Navigated to Google Meet '{validated_code}'. The pre-join screen is ready for you to join."

        except Exception as e:
            logger.error(f"[GoogleMeetService] Error joining meeting: {e}")
            return f"Failed to join Google Meet '{validated_code}': {str(e)}"
