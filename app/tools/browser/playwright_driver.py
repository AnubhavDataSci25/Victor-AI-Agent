import asyncio
import logging
import os
from pathlib import Path
from typing import Any
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from app.tools.browser.driver import BrowserDriverError

logger = logging.getLogger(__name__)


def _find_chrome_executable() -> str | None:
    """Searches standard Windows installation paths for google chrome."""
    candidates = [
        os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return None


def _is_victor_ui(page: Page) -> bool:
    """Checks if the page is hosting the Victor web UI to prevent navigating away from it."""
    try:
        url = page.url.lower()
        return "localhost:8000" in url or "127.0.0.1:8000" in url
    except Exception:
        return False


class PlaywrightBrowserDriver:
    _instance = None

    def __new__(cls):
        # Enforce singleton pattern to share a single browser instance per session
        if cls._instance is None:
            cls._instance = super(PlaywrightBrowserDriver, cls).__new__(cls)
            cls._instance.playwright = None
            cls._instance.browser = None
            cls._instance.context = None
            cls._instance.page = None
            cls._instance._is_cdp = False
            cls._instance._current_loop = None
            cls._instance._current_lock = None
        return cls._instance

    @property
    def _lock(self) -> asyncio.Lock:
        """Provides a lock bound to the currently running asyncio event loop."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if getattr(self, "_current_loop", None) is not loop:
            self._current_loop = loop
            self._current_lock = asyncio.Lock()
            # Invalidate any objects bound to a previously closed loop
            self.playwright = None
            self.browser = None
            self.context = None
            self.page = None
            self._is_cdp = False

        return self._current_lock

    def _get_profile_dir(self) -> str:
        """Returns the dedicated user data directory for Victor's Chrome profile."""
        custom_dir = os.getenv("CHROME_USER_DATA_DIR")
        if custom_dir:
            return custom_dir
        local_app_data = os.environ.get("LOCALAPPDATA", str(Path.home()))
        return os.path.join(local_app_data, "Victor", "ChromeProfile")

    def _get_cdp_url(self) -> str:
        """Returns the Chrome DevTools Protocol URL to connect to an existing session."""
        custom_url = os.getenv("CDP_URL")
        if custom_url:
            return custom_url
        port = os.getenv("CHROME_DEBUGGING_PORT", "9222")
        return f"http://127.0.0.1:{port}"

    async def _is_alive(self) -> bool:
        """Checks if the browser connection and context are alive and can host pages."""
        if not self.playwright or not self.context:
            return False
        if self.browser is not None and not self.browser.is_connected():
            return False
        try:
            pages = self.context.pages
            if not any(not p.is_closed() for p in pages):
                return False
            return True
        except Exception:
            return False

    async def _ensure_browser(self):
        """Ensures that the browser engine and context are alive, reinitializing if needed."""
        if not await self._is_alive():
            await self.start()

    async def start(self):
        """
        Initializes the browser connection layer.
        Strategy 1: Connect to an existing Chrome session over CDP (if running).
        Strategy 2: Launch a dedicated Chrome instance with persistent profile & remote debugging.
        """
        await self._cleanup_references()

        headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        cdp_url = self._get_cdp_url()
        debug_port = os.getenv("CHROME_DEBUGGING_PORT", "9222")

        logger.info("Initializing Playwright Browser Driver...")
        self.playwright = await async_playwright().start()

        # 1. Attempt connection to existing Chrome session via CDP
        try:
            logger.info(f"Attempting CDP connection to existing Chrome session at {cdp_url}...")
            self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url, timeout=1500)
            if self.browser.contexts:
                self.context = self.browser.contexts[0]
            else:
                self.context = await self.browser.new_context()
            self._is_cdp = True
            logger.info("Successfully connected to existing Chrome browser session via CDP.")
        except Exception as cdp_err:
            logger.info(f"No existing Chrome CDP session found ({cdp_err}). Launching dedicated Chrome session...")
            self._is_cdp = False

        # 2. If CDP not available and not headless, launch dedicated Chrome independently and connect via CDP
        if not self.context and not headless:
            chrome_exe = _find_chrome_executable()
            if chrome_exe:
                profile_dir = self._get_profile_dir()
                os.makedirs(profile_dir, exist_ok=True)
                logger.info(f"Spawning independent Chrome instance at '{profile_dir}' with remote debugging port {debug_port}...")
                chrome_args = [
                    chrome_exe,
                    f"--remote-debugging-port={debug_port}",
                    f"--user-data-dir={profile_dir}",
                    "--no-first-run",
                    "--no-default-browser-check",
                ]
                import subprocess
                try:
                    subprocess.Popen(
                        chrome_args,
                        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                    )
                    for _ in range(10):
                        try:
                            await asyncio.sleep(0.3)
                            self.browser = await self.playwright.chromium.connect_over_cdp(cdp_url, timeout=1000)
                            if self.browser.contexts:
                                self.context = self.browser.contexts[0]
                            else:
                                self.context = await self.browser.new_context()
                            self._is_cdp = True
                            logger.info("Successfully connected to newly spawned independent Chrome session via CDP.")
                            break
                        except Exception:
                            pass
                except Exception as spawn_err:
                    logger.warning(f"Could not spawn independent Chrome: {spawn_err}")

        # 3. Fallback: If CDP still not available (e.g. headless or tests), launch persistent context
        if not self.context:
            profile_dir = self._get_profile_dir()
            os.makedirs(profile_dir, exist_ok=True)
            logger.info(f"Launching dedicated Chrome profile at '{profile_dir}' (headless={headless})...")

            chrome_args = [
                "--no-first-run",
                "--no-default-browser-check",
                f"--remote-debugging-port={debug_port}",
            ]

            chrome_exe = _find_chrome_executable()
            launched = False

            try:
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    channel="chrome",
                    headless=headless,
                    args=chrome_args,
                    viewport=None,
                )
                self.browser = self.context.browser
                launched = True
                logger.info("Successfully launched Google Chrome via channel='chrome'.")
            except Exception as ch_err:
                logger.warning(f"Could not launch via channel='chrome': {ch_err}")

            if not launched and chrome_exe:
                try:
                    logger.info(f"Launching Chrome via binary path: {chrome_exe}")
                    self.context = await self.playwright.chromium.launch_persistent_context(
                        user_data_dir=profile_dir,
                        executable_path=chrome_exe,
                        headless=headless,
                        args=chrome_args,
                        viewport=None,
                    )
                    self.browser = self.context.browser
                    launched = True
                    logger.info("Successfully launched Google Chrome via executable_path.")
                except Exception as exe_err:
                    logger.warning(f"Could not launch via executable_path: {exe_err}")

            if not launched:
                logger.info("Falling back to bundled Playwright Chromium with persistent context...")
                self.context = await self.playwright.chromium.launch_persistent_context(
                    user_data_dir=profile_dir,
                    headless=headless,
                    args=chrome_args,
                    viewport=None,
                )
                self.browser = self.context.browser
                logger.info("Launched bundled Chromium with persistent context.")

        # Ensure an active page is assigned (avoiding Victor UI tab)
        open_pages = [p for p in self.context.pages if not p.is_closed() and not _is_victor_ui(p)]
        if open_pages:
            self.page = open_pages[0]
        else:
            self.page = await self.context.new_page()

    async def get_page(self) -> Page:
        """Returns the active browser page, avoiding the Victor UI tab and initializing or recovering if necessary."""
        async with self._lock:
            await self._ensure_browser()

            if self.page is not None and not self.page.is_closed() and not _is_victor_ui(self.page):
                return self.page

            if self.context is not None:
                # Pick any open tab that is not the Victor UI
                open_pages = [p for p in self.context.pages if not p.is_closed() and not _is_victor_ui(p)]
                if open_pages:
                    self.page = open_pages[-1]
                    return self.page
                try:
                    self.page = await self.context.new_page()
                    return self.page
                except Exception as e:
                    logger.info(f"Context closed or unable to open new page ({e}). Re-starting browser session...")
                    await self.start()
                    open_pages = [p for p in self.context.pages if not p.is_closed() and not _is_victor_ui(p)]
                    self.page = open_pages[-1] if open_pages else await self.context.new_page()
                    return self.page

            raise BrowserDriverError("Browser context could not be initialized.")

    async def new_page(self, url: str | None = None) -> Page:
        """Creates a new browser tab/page, optionally navigating to a URL."""
        async with self._lock:
            await self._ensure_browser()
            try:
                page = await self.context.new_page()
            except Exception as e:
                logger.info(f"Context closed or unable to open new page ({e}). Re-starting browser session...")
                await self.start()
                page = await self.context.new_page()

            if url:
                await page.goto(url, wait_until="domcontentloaded")
            self.page = page
            return page

    async def open_tab(self, url: str | None = None) -> int:
        """Opens a new tab, optionally navigating it. Returns 0-based tab index."""
        page = await self.new_page(url)
        pages = await self.get_pages()
        return pages.index(page) if page in pages else len(pages) - 1

    async def get_pages(self) -> list[Page]:
        """Returns all open, active pages/tabs in the current browser context."""
        async with self._lock:
            await self._ensure_browser()
            return [p for p in self.context.pages if not p.is_closed()]

    async def switch_tab(self, index: int) -> Page:
        """Brings the tab at the specified index to front and sets it active."""
        async with self._lock:
            await self._ensure_browser()
            pages = [p for p in self.context.pages if not p.is_closed()]
            if not pages:
                self.page = await self.new_page()
                return self.page
            idx = max(0, min(index, len(pages) - 1))
            page = pages[idx]
            await page.bring_to_front()
            self.page = page
            return page

    async def close_tab(self, index: int | None = None) -> bool:
        """Closes a specific tab by index, or the active tab if None."""
        async with self._lock:
            await self._ensure_browser()
            if not self.context:
                return False
            pages = [p for p in self.context.pages if not p.is_closed()]
            if not pages:
                return False

            # Identify target tab
            if index is not None and 0 <= index < len(pages):
                target = pages[index]
            else:
                target = self.page if (self.page and not self.page.is_closed()) else pages[-1]

            # Protect Victor UI page from being closed
            if _is_victor_ui(target):
                logger.warning("Prevented closing Victor UI tab.")
                return False

            try:
                await target.close()
            except Exception as close_err:
                logger.debug(f"Note during tab close: {close_err}")

            remaining = [p for p in self.context.pages if not p.is_closed() and not _is_victor_ui(p)]
            self.page = remaining[-1] if remaining else None
            return True

    async def close_browser(self) -> bool:
        """Terminates the entire browser instance and resets all internal references."""
        async with self._lock:
            logger.info("Terminating Playwright Browser instance...")
            await self._cleanup_references()
            return True

    async def get_active_url(self) -> str | None:
        """Returns the URL of the currently active page."""
        page = await self.get_page()
        return page.url if page else None

    async def get_active_title(self) -> str | None:
        """Returns the title of the currently active page."""
        page = await self.get_page()
        return await page.title() if page else None

    async def _cleanup_references(self):
        """Safely cleans up internal Playwright references."""
        try:
            if self._is_cdp:
                if self.context:
                    # In CDP mode, close user tabs (except Victor UI)
                    for p in list(self.context.pages):
                        if not p.is_closed() and not _is_victor_ui(p):
                            try:
                                await p.close()
                            except Exception:
                                pass
                if self.browser:
                    await self.browser.close()
            else:
                if self.context:
                    await self.context.close()
                elif self.browser:
                    await self.browser.close()
        except Exception as e:
            logger.debug(f"Note during context cleanup: {e}")

        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as e:
                logger.debug(f"Note during playwright stop: {e}")

        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self._is_cdp = False

    async def stop(self):
        """Cleans up the browser lifecycle."""
        await self.close_browser()