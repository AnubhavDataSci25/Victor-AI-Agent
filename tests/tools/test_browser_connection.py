"""
Tests for Victor's browser access and connection layer (PlaywrightBrowserDriver)
and verification that existing browser tools work seamlessly with it.
"""

import pytest
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver
from app.tools.browser.tool import (
    BrowserClickElementTool,
    BrowserOpenUrlTool,
    BrowserSearchWebTool,
)
from app.tools.music.spotify_provider import SpotifyProvider
from app.tools.music.youtube_provider import YouTubeMusicProvider


@pytest.mark.asyncio
async def test_playwright_browser_driver_lifecycle():
    driver = PlaywrightBrowserDriver()
    assert driver is PlaywrightBrowserDriver(), "PlaywrightBrowserDriver should be a singleton"

    # Get page initializes the browser session
    page = await driver.get_page()
    assert page is not None
    assert not page.is_closed()

    # Verify navigating and reading title
    await page.goto("about:blank")
    title = await driver.get_active_title()
    assert title == ""

    # Test tab creation
    tab_index = await driver.open_tab("about:blank")
    pages = await driver.get_pages()
    assert len(pages) >= 2
    assert tab_index >= 0

    # Test tab switching
    switched_page = await driver.switch_tab(0)
    assert switched_page is not None

    # Test closing tab
    closed = await driver.close_tab(tab_index)
    assert closed is True

    # Test closed-page recovery: close current page manually and verify get_page recovers
    current_page = await driver.get_page()
    await current_page.close()
    recovered_page = await driver.get_page()
    assert recovered_page is not None
    assert not recovered_page.is_closed()

    # Clean up lifecycle
    await driver.stop()
    assert driver.page is None
    assert driver.context is None


@pytest.mark.asyncio
async def test_browser_tools_execution():
    driver = PlaywrightBrowserDriver()

    # 1. Test BrowserOpenUrlTool
    open_tool = BrowserOpenUrlTool()
    open_res = await open_tool.execute({"url": "about:blank"})
    assert "[SYSTEM SECURITY WARNING" in open_res

    # 2. Test BrowserClickElementTool
    # Prepare a page with a clickable button
    page = await driver.get_page()
    await page.set_content("<button id='test-btn'>Click Me</button>")
    click_tool = BrowserClickElementTool()
    click_res = await click_tool.execute({"text": "Click Me"})
    assert "Successfully clicked element containing 'Click Me'" in click_res

    # 3. Test BrowserSearchWebTool
    search_tool = BrowserSearchWebTool()
    search_res = await search_tool.execute({"query": "python"})
    assert "[SYSTEM SECURITY WARNING" in search_res

    await driver.stop()


@pytest.mark.asyncio
async def test_music_providers_with_driver():
    """Verify Spotify and YouTube Music providers interact with driver without crashing."""
    driver = PlaywrightBrowserDriver()

    # YouTube Music provider execution
    yt_res = await YouTubeMusicProvider.play("test")
    assert isinstance(yt_res, str)
    assert "YouTube Music" in yt_res

    # Spotify provider execution (handles unauthenticated state gracefully)
    spotify_res = await SpotifyProvider.play("test")
    assert isinstance(spotify_res, str)
    assert "Spotify" in spotify_res

    await driver.stop()
