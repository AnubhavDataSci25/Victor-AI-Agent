import asyncio
import urllib.parse
import logging
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)


class YouTubeMusicProvider:
    # Cookie/consent selectors for YouTube
    _COOKIE_SELECTORS = [
        "button[aria-label*='Accept' i]",
        "button:has-text('Accept all')",
        "button:has-text('I agree')",
        "button:has-text('Reject all')",
    ]

    # Selectors to detect that search results have rendered
    _SEARCH_READY_SELECTORS = [
        "ytmusic-shelf-renderer",
        "ytmusic-responsive-list-item-renderer",
        "ytmusic-play-button-renderer",
    ]

    # Prioritized candidate selectors for playable items
    _PLAY_CANDIDATES = [
        "ytmusic-responsive-list-item-renderer ytmusic-play-button-renderer",
        "ytmusic-play-button-renderer #button",
        "ytmusic-play-button-renderer",
        "ytmusic-responsive-list-item-renderer .title a",
        "ytmusic-responsive-list-item-renderer",
    ]

    @staticmethod
    async def play(query: str) -> str:
        driver = PlaywrightBrowserDriver()
        try:
            page = await driver.get_page()
            url = f"https://music.youtube.com/search?q={urllib.parse.quote(query)}"
            logger.info(f"YouTube Music: navigating to {url}")

            await page.goto(url, wait_until="domcontentloaded")

            # --- 1. Dismiss cookie consent if present ---
            await YouTubeMusicProvider._dismiss_cookie_banner(page)

            # --- 2. Wait for search results to appear ---
            await YouTubeMusicProvider._wait_for_search_results(page)

            # Brief pause for component hydration
            await asyncio.sleep(0.5)

            # --- 3. Find and click a play button ---
            clicked = await YouTubeMusicProvider._click_play_button(page)

            if not clicked:
                raise RuntimeError(
                    f"Could not locate a playable track for '{query}' in YouTube Music search results."
                )

            logger.info(f"YouTube Music: successfully started playback for '{query}'")
            return f"Playing '{query}' on YouTube Music."

        except Exception as e:
            logger.error(f"YouTube Music playback error: {e}")
            return f"Could not start playback on YouTube Music. Error: {str(e)}"

    @staticmethod
    async def _dismiss_cookie_banner(page) -> None:
        """Dismiss any cookie consent overlay that might block interaction."""
        for sel in YouTubeMusicProvider._COOKIE_SELECTORS:
            try:
                btn = page.locator(sel)
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    logger.info(f"YouTube Music: dismissed cookie banner via '{sel}'")
                    return
            except Exception:
                pass

    @staticmethod
    async def _wait_for_search_results(page) -> None:
        """Wait for at least one search result container to appear."""
        for sel in YouTubeMusicProvider._SEARCH_READY_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                logger.info(f"YouTube Music: search results ready (matched '{sel}')")
                return
            except Exception:
                continue
        logger.warning("YouTube Music: no search result container detected within timeout")

    @staticmethod
    async def _click_play_button(page) -> bool:
        """Try each candidate selector to find and click a play button."""
        for sel in YouTubeMusicProvider._PLAY_CANDIDATES:
            loc = page.locator(sel)
            count = await loc.count()
            if count == 0:
                continue

            target = loc.first
            logger.info(f"YouTube Music: trying candidate '{sel}' ({count} match(es))")

            # Step A: hover to reveal hidden play overlays
            try:
                await target.hover(timeout=1500)
            except Exception:
                pass

            # Step B: standard Playwright click
            try:
                await target.click(timeout=3000)
                logger.info(f"YouTube Music: clicked via standard click on '{sel}'")
                return True
            except Exception as e:
                logger.debug(f"YouTube Music: standard click failed on '{sel}': {e}")

            # Step C: force click (bypasses actionability checks)
            try:
                await target.click(timeout=2000, force=True)
                logger.info(f"YouTube Music: clicked via force click on '{sel}'")
                return True
            except Exception as e:
                logger.debug(f"YouTube Music: force click failed on '{sel}': {e}")

            # Step D: JavaScript dispatchEvent (bypasses overlay interception)
            try:
                await target.evaluate("el => el.click()")
                logger.info(f"YouTube Music: clicked via JS click on '{sel}'")
                return True
            except Exception as e:
                logger.debug(f"YouTube Music: JS click failed on '{sel}': {e}")

        return False