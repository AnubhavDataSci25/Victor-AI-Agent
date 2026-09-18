import asyncio
import urllib.parse
import logging
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)


class SpotifyProvider:
    # Selectors for cookie/consent banners that may block interactions
    _COOKIE_SELECTORS = [
        "#onetrust-accept-btn-handler",
        "button[id='onetrust-accept-btn-handler']",
        "button:has-text('Accept Cookies')",
        "button:has-text('Accept all')",
    ]

    # Selectors to detect that search results have rendered inside <main>
    _SEARCH_READY_SELECTORS = [
        "main button[data-testid='play-button']",
        "main [data-testid='top-result-card']",
        "main [data-testid='tracklist-row']",
        "main [role='grid']",
        "main section",
    ]

    # Prioritized play button candidates, strictly scoped to <main>
    # to avoid hitting sidebar playlist buttons (e.g. "Play Liked Songs")
    _PLAY_CANDIDATES = [
        "main [data-testid='top-result-card'] button[data-testid='play-button']",
        "main [data-testid='top-result-card'] button[aria-label*='Play' i]",
        "main [data-testid='heropod-card'] button[data-testid='play-button']",
        "main button[data-testid='play-button']",
        "main [data-testid='tracklist-row'] button[aria-label*='Play' i]",
        "main [data-testid='tracklist-row'] [data-testid='play-button']",
        "main button[aria-label*='Play' i]",
        "main [data-testid='tracklist-row']",
        "main [data-testid='top-result-card']",
    ]

    @staticmethod
    async def play(query: str) -> str:
        driver = PlaywrightBrowserDriver()
        try:
            page = await driver.get_page()
            url = f"https://open.spotify.com/search/{urllib.parse.quote(query)}"
            logger.info(f"Spotify: navigating to {url}")

            # Use networkidle to ensure Spotify's SPA has finished fetching data
            await page.goto(url, wait_until="networkidle", timeout=25000)

            # --- 1. Dismiss cookie consent if present ---
            await SpotifyProvider._dismiss_cookie_banner(page)

            # --- 2. Wait for search results to render inside <main> ---
            await SpotifyProvider._wait_for_search_results(page)

            # Brief pause for SPA hydration & button event binding
            await asyncio.sleep(0.5)

            # --- 3. Find and click a play button ---
            clicked = await SpotifyProvider._click_play_button(page)

            if not clicked:
                raise RuntimeError(
                    f"Could not locate a playable track for '{query}' in Spotify search results."
                )

            logger.info(f"Spotify: successfully started playback for '{query}'")
            return f"Playing '{query}' on Spotify."

        except Exception as e:
            logger.error(f"Spotify playback error: {e}")
            return (
                f"Could not start playback on Spotify "
                f"(Note: Spotify Web requires an active login session in the automated browser). "
                f"Error: {str(e)}"
            )

    @staticmethod
    async def _dismiss_cookie_banner(page) -> None:
        """Dismiss any cookie consent overlay that might block interaction."""
        for sel in SpotifyProvider._COOKIE_SELECTORS:
            try:
                btn = page.locator(sel)
                if await btn.is_visible(timeout=800):
                    await btn.click()
                    logger.info(f"Spotify: dismissed cookie banner via '{sel}'")
                    return
            except Exception:
                pass

    @staticmethod
    async def _wait_for_search_results(page) -> None:
        """Wait for at least one search result container to appear in <main>."""
        for sel in SpotifyProvider._SEARCH_READY_SELECTORS:
            try:
                await page.wait_for_selector(sel, timeout=8000)
                logger.info(f"Spotify: search results ready (matched '{sel}')")
                return
            except Exception:
                continue
        logger.warning("Spotify: no search result container detected within timeout")

    @staticmethod
    async def _click_play_button(page) -> bool:
        """Try each candidate selector to find and click a play button."""
        for sel in SpotifyProvider._PLAY_CANDIDATES:
            loc = page.locator(sel)
            count = await loc.count()
            if count == 0:
                continue

            target = loc.first
            logger.info(f"Spotify: trying candidate '{sel}' ({count} match(es))")

            # Step A: hover to reveal hidden play overlays
            try:
                await target.hover(timeout=1500)
            except Exception:
                pass

            # Step B: standard Playwright click
            try:
                await target.click(timeout=3000)
                logger.info(f"Spotify: clicked via standard click on '{sel}'")
                return True
            except Exception as e:
                logger.debug(f"Spotify: standard click failed on '{sel}': {e}")

            # Step C: force click (bypasses actionability checks)
            try:
                await target.click(timeout=2000, force=True)
                logger.info(f"Spotify: clicked via force click on '{sel}'")
                return True
            except Exception as e:
                logger.debug(f"Spotify: force click failed on '{sel}': {e}")

            # Step D: JavaScript dispatchEvent (bypasses overlay interception)
            try:
                await target.evaluate("el => el.click()")
                logger.info(f"Spotify: clicked via JS click on '{sel}'")
                return True
            except Exception as e:
                logger.debug(f"Spotify: JS click failed on '{sel}': {e}")

        return False