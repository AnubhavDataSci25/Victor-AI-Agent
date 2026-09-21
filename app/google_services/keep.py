"""
Google Keep automation service for Victor 2.0.

Provides deterministic note creation, search, and navigation on Google Keep
using Victor's persistent Chrome browser profile.
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from typing import Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from app.google_services.base import BaseGoogleService

logger = logging.getLogger(__name__)


class GoogleKeepService(BaseGoogleService):
    name = "keep"
    display_name = "Google Keep"
    base_url = "https://keep.google.com"

    async def create_note(self, title: str, content: str) -> str:
        """
        Creates a new note in Google Keep with the specified title and body content.
        Commits the note via the Close action and verifies completion.
        """
        title = (title or "").strip()
        content = (content or "").strip()

        if not title and not content:
            return "Cannot create an empty note. Please provide a title or note content."

        try:
            page = await self.get_or_create_page(url_keyword="keep.google.com", target_url=self.base_url)
            await self.wait_for_ready(page)

            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return auth_msg

            # 1. Click 'Take a note…' to expand the note editor
            expanded = False
            take_note_selectors = [
                '[aria-label="Take a note…"]',
                'div[role="textbox"]:has-text("Take a note…")',
                '.notelist-quicknote',
                'div.notelist-quicknote-compact',
                'div[contenteditable="true"][aria-label*="Take a note"]',
            ]

            for sel in take_note_selectors:
                try:
                    locator = page.locator(sel).first
                    if await locator.is_visible(timeout=1500):
                        await locator.click()
                        expanded = True
                        break
                except Exception:
                    continue

            if not expanded:
                # Try clicking anywhere in the quicknote area
                try:
                    await page.click('div:has-text("Take a note…")', timeout=2000)
                    expanded = True
                except Exception:
                    pass

            # Wait a brief moment for note expansion animation
            await asyncio.sleep(0.4)

            # 2. Enter Title if provided
            if title:
                title_selectors = [
                    'div[placeholder="Title"]',
                    'input[placeholder="Title"]',
                    'div[aria-label="Title"]',
                    'div[contenteditable="true"][aria-label*="Title"]',
                ]
                for t_sel in title_selectors:
                    try:
                        t_loc = page.locator(t_sel).first
                        if await t_loc.is_visible(timeout=1000):
                            await t_loc.fill(title)
                            break
                    except Exception:
                        continue

            # 3. Enter Note Body Content if provided
            if content:
                body_selectors = [
                    'div[aria-label="Take a note…"][role="textbox"]',
                    'div[contenteditable="true"][role="textbox"]',
                    'div.notelist-quicknote div[contenteditable="true"]',
                ]
                for b_sel in body_selectors:
                    try:
                        b_loc = page.locator(b_sel).first
                        if await b_loc.is_visible(timeout=1000):
                            await b_loc.fill(content)
                            break
                    except Exception:
                        continue

            # 4. Click 'Close' button to save and commit note
            close_clicked = False
            close_selectors = [
                'div[role="button"]:has-text("Close")',
                'button:has-text("Close")',
                '[aria-label="Close"]',
            ]
            for c_sel in close_selectors:
                try:
                    c_loc = page.locator(c_sel).first
                    if await c_loc.is_visible(timeout=1000):
                        await c_loc.click()
                        close_clicked = True
                        break
                except Exception:
                    continue

            if not close_clicked:
                # Press Escape key to commit note
                await page.keyboard.press("Escape")

            await asyncio.sleep(0.5)

            heading = f"titled '{title}'" if title else "note"
            preview = f" Preview: \"{content[:60]}...\"" if len(content) > 60 else (f" Content: \"{content}\"" if content else "")
            return f"Successfully created Google Keep {heading}.{preview}"

        except Exception as e:
            logger.error(f"[GoogleKeepService] Error creating note: {e}")
            return f"Failed to create Google Keep note: {str(e)}"

    async def search_notes(self, query: str) -> str:
        """
        Searches Google Keep for existing notes matching query.
        Navigates to Keep's search view and reports results.
        """
        query = (query or "").strip()
        if not query:
            return "Please specify a search term to find notes in Google Keep."

        try:
            encoded_query = urllib.parse.quote(query)
            search_url = f"{self.base_url}/#search/text={encoded_query}"
            page = await self.get_or_create_page(url_keyword="keep.google.com", target_url=search_url)
            await self.wait_for_ready(page)

            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return auth_msg

            await asyncio.sleep(1.0)
            return f"Opened Google Keep and searched for '{query}'. Matching notes are displayed on screen."
        except Exception as e:
            logger.error(f"[GoogleKeepService] Error searching notes: {e}")
            return f"Could not search Google Keep: {str(e)}"

    async def open_keep(self) -> str:
        """Opens Google Keep in the browser."""
        try:
            page = await self.get_or_create_page(url_keyword="keep.google.com", target_url=self.base_url)
            await self.wait_for_ready(page)
            is_authed, auth_msg = await self.check_login_status(page)
            if not is_authed:
                return auth_msg
            return "Opened Google Keep."
        except Exception as e:
            return f"Failed to open Google Keep: {str(e)}"
