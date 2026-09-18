import urllib.parse
import logging
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)

class YouTubeVideoProvider:
    @staticmethod
    async def play_video(query: str) -> str:
        driver = PlaywrightBrowserDriver()
        try:
            page = await driver.get_page()
            url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            await page.goto(url, wait_until="domcontentloaded")
            
            # Target the first video thumbnail in the search results
            video_link = page.locator('ytd-video-renderer a#thumbnail').first
            await video_link.click(timeout=10000)
            
            return f"Playing '{query}' on YouTube."
        except Exception as e:
            logger.error(f"YouTube playback error: {e}")
            return f"Could not start video on YouTube. Error: {str(e)}"