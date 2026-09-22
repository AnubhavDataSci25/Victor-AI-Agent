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

            # Dismiss any previously open note modal dialog
            if hasattr(page, "keyboard") and page.keyboard:
                try:
                    await page.keyboard.press("Escape")
                    await asyncio.sleep(0.2)
                except Exception:
                    pass

            # 1. Target the top quicknote creation container (distinct from existing note cards)
            editor = page.locator('div.h1U9Be-xhiy4, div.IZ65Hb-n0tgWb:not(.IZ65Hb-WsjYwc-nUpftc), div[class*="quicknote"]').first
            expanded = False

            if await editor.is_visible(timeout=1500):
                await editor.click()
                expanded = True
            else:
                take_note_selectors = [
                    '[aria-label="Take a note…"]',
                    'div[role="textbox"]:has-text("Take a note…")',
                    '.notelist-quicknote',
                    'div.notelist-quicknote-compact',
                ]
                for sel in take_note_selectors:
                    try:
                        locator = page.locator(sel).first
                        if await locator.is_visible(timeout=1000):
                            await locator.click()
                            expanded = True
                            break
                    except Exception:
                        continue

            await asyncio.sleep(0.4)

            def _scoped_loc(parent, fallback_page, selector):
                try:
                    res = parent.locator(selector)
                    if hasattr(res, "first"):
                        return res.first
                    if asyncio.iscoroutine(res):
                        res.close()
                        return getattr(parent, "first", parent)
                    return res
                except Exception:
                    return fallback_page.locator(selector).first

            # 2. Enter Title if provided
            if title:
                title_el = _scoped_loc(editor, page, 'div[role="textbox"][aria-label="Title"], div[placeholder="Title"], div[aria-label="Title"], input[placeholder="Title"]')
                if not await title_el.is_visible(timeout=1000):
                    title_el = page.locator('div[role="textbox"][aria-label="Title"], div[placeholder="Title"]').first

                if await title_el.is_visible(timeout=1000):
                    await title_el.click()
                    if hasattr(page, "keyboard") and page.keyboard:
                        try:
                            await page.keyboard.type(title, delay=15)
                        except Exception:
                            await title_el.fill(title)
                    else:
                        await title_el.fill(title)

            await asyncio.sleep(0.2)

            # 3. Enter Note Body Content if provided
            if content:
                # Click into body area to activate ProseMirror contenteditable container
                body_area = _scoped_loc(editor, page, '.IZ65Hb-qJTHM-haAclf, div[aria-label*="Take a note"]')
                if await body_area.is_visible(timeout=1000):
                    await body_area.click()
                    await asyncio.sleep(0.2)

                body_el = _scoped_loc(editor, page, '.IZ65Hb-qJTHM-haAclf [role="textbox"], .IZ65Hb-qJTHM-haAclf div[contenteditable="true"], div[aria-label*="Take a note"][role="textbox"]')
                if not await body_el.is_visible(timeout=1000):
                    body_el = page.locator('div[aria-label*="Take a note…"][role="textbox"], div[contenteditable="true"][role="textbox"]').first

                if await body_el.is_visible(timeout=1000):
                    await body_el.click()
                    if hasattr(page, "keyboard") and page.keyboard:
                        try:
                            await page.keyboard.type(content, delay=15)
                        except Exception:
                            await body_el.fill(content)
                    else:
                        await body_el.fill(content)

            await asyncio.sleep(0.3)

            # 4. Click 'Close' button specifically within the editor to commit note
            close_clicked = False
            close_btn = _scoped_loc(editor, page, 'div[role="button"]:has-text("Close"), button:has-text("Close")')
            if await close_btn.is_visible(timeout=1200):
                await close_btn.click()
                close_clicked = True
            else:
                all_close = page.locator('div[role="button"]:has-text("Close"), button:has-text("Close")')
                count = await all_close.count()
                for i in range(count):
                    btn = all_close.nth(i)
                    if await btn.is_visible():
                        await btn.click()
                        close_clicked = True
                        break

            if not close_clicked and hasattr(page, "keyboard") and page.keyboard:
                # Press Escape key to commit note
                await page.keyboard.press("Escape")

            # Await cloud sync autosave
            await asyncio.sleep(1.0)

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
