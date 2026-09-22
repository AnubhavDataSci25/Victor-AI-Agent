"""
Base architecture for Google Services Automation in Victor 2.0.

Provides an extensible foundation for controlling Google web applications
(Google Keep, Calendar, Meet, and future services such as Gmail, Drive, Docs, etc.)
using a shared, persistent Playwright browser session without storing Google credentials.
"""

from __future__ import annotations

import abc
import asyncio
import logging
from typing import Optional
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)


class GoogleServiceError(Exception):
    """Raised when an operation on a Google service fails."""
    pass


class BaseGoogleService(abc.ABC):
    """
    Abstract base class for all Victor Google Services.

    Subclasses implement service-specific automation flows (e.g. creating notes,
    events, or meeting rooms) while sharing persistent browser context and common
    helper utilities.
    """

    name: str
    display_name: str
    base_url: str

    def __init__(self, driver: Optional[PlaywrightBrowserDriver] = None) -> None:
        self._driver = driver or PlaywrightBrowserDriver()

    @property
    def driver(self) -> PlaywrightBrowserDriver:
        return self._driver

    async def get_or_create_page(self, url_keyword: Optional[str] = None, target_url: Optional[str] = None) -> Page:
        """
        Reuses an existing open tab matching url_keyword if available,
        or opens/navigates to target_url to avoid creating dozens of duplicate tabs.
        """
        target = target_url or self.base_url
        keyword = (url_keyword or self.name).lower()

        pages = await self._driver.get_pages()
        for page in pages:
            if not page.is_closed():
                try:
                    if keyword in page.url.lower():
                        await page.bring_to_front()
                        self._driver.page = page
                        # If the existing page has a hash (like #NOTE/... or #search/...) or different path, navigate to clean target
                        if target_url and page.url.rstrip("/") != target_url.rstrip("/"):
                            try:
                                await page.goto(target_url, wait_until="domcontentloaded", timeout=12000)
                            except Exception:
                                pass
                        return page
                except Exception:
                    pass

        # If not already open, open a new page
        page = await self._driver.new_page(target)
        return page

    async def check_login_status(self, page: Page) -> tuple[bool, str]:
        """
        Checks if the page was redirected to Google Accounts sign-in.
        Does NOT attempt to capture or bypass Google login credentials.
        """
        try:
            current_url = page.url.lower()
            if "accounts.google.com" in current_url and ("signin" in current_url or "serviceLogin" in current_url.lower()):
                msg = (
                    f"Please sign into your Google account in Victor's Chrome browser window. "
                    f"Once signed in, your session is saved permanently in your profile."
                )
                logger.warning(f"[{self.display_name}] Redirected to Google sign-in.")
                return False, msg
            return True, "Authenticated"
        except Exception as e:
            logger.debug(f"Login check exception: {e}")
            return True, "OK"

    async def wait_for_ready(self, page: Page, timeout_ms: int = 8000) -> bool:
        """Waits for DOM content and general network stability."""
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
            return True
        except PlaywrightTimeoutError:
            logger.debug(f"[{self.display_name}] domcontentloaded timeout reached.")
            return False
        except Exception as e:
            logger.debug(f"[{self.display_name}] wait_for_ready note: {e}")
            return False
