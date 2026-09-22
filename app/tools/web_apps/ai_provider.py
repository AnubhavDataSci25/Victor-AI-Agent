import logging
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)

class AIWebProvider:
    @staticmethod
    async def open_chatgpt() -> str:
        driver = PlaywrightBrowserDriver()
        try:
            page = await driver.get_page()
            await page.goto("https://chatgpt.com", wait_until="domcontentloaded")
            return "Successfully opened ChatGPT in the browser."
        except Exception as e:
            logger.error(f"ChatGPT open error: {e}")
            return f"Could not open ChatGPT. Error: {str(e)}"

    @staticmethod
    async def open_gemini() -> str:
        driver = PlaywrightBrowserDriver()
        try:
            page = await driver.get_page()
            await page.goto("https://gemini.google.com", wait_until="domcontentloaded")
            return "Successfully opened Gemini web interface."
        except Exception as e:
            logger.error(f"Gemini open error: {e}")
            return f"Could not open Gemini. Error: {str(e)}"

    @staticmethod
    async def open_claude() -> str:
        driver = PlaywrightBrowserDriver()
        try:
            page = await driver.get_page()
            await page.goto("https://claude.ai", wait_until="domcontentloaded")
            return "Successfully opened Claude AI in the browser."
        except Exception as e:
            logger.error(f"Claude open error: {e}")
            return f"Could not open Claude AI. Error: {str(e)}"