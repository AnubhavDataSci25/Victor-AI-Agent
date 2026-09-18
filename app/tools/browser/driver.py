"""
BrowserDriver - the interface every browser tool talks to, never
Playwright directly. Same rationale as app/tools/computer/driver.py:
a real browser can't run in this development sandbox (no network
access to download Playwright's browser binaries), so tool logic
(argument validation, permission classification, structured results,
verification) is tested against FakeBrowserDriver, while
PlaywrightBrowserDriver is the production implementation.

Security note (spec section 25): webpage content returned by
read_page/extract_text/search_web is DATA, not instructions. Nothing
in Victor's architecture feeds a tool's output back into the router
as a new command automatically - a ToolResult only ever flows to the
responder for humanization. That's what makes "a webpage tells Victor
to delete files" structurally impossible today, not a policy that
has to be remembered and re-applied by whoever builds the future LLM
integration - there is no code path for it to plug into.
"""

from __future__ import annotations

from typing import Protocol, TypedDict


class BrowserDriverError(Exception):
    """Raised by a BrowserDriver implementation when a browser action fails."""


class SearchResult(TypedDict):
    title: str
    url: str
    snippet: str


class BrowserDriver(Protocol):
    def open_url(self, url: str) -> None: ...

    def search_web(self, query: str) -> list[SearchResult]: ...

    def read_page(self) -> dict[str, str]:
        """Returns {'url': ..., 'title': ..., 'text': ...} for the active tab."""
        ...

    def extract_text(self, selector: str) -> str | None: ...

    def click_element(self, selector: str) -> bool: ...

    def type_into_page(self, selector: str, text: str) -> bool: ...

    def scroll_page(self, direction: str, amount: int) -> None: ...

    def go_back(self) -> bool: ...

    def go_forward(self) -> bool: ...

    def open_tab(self, url: str | None) -> int:
        """Opens a new tab, optionally navigating it. Returns a tab id."""
        ...

    def close_tab(self, tab_id: int) -> bool: ...

    def screenshot_page(self) -> bytes:
        """Returns a PNG-encoded screenshot of the active tab."""
        ...

    def get_active_url(self) -> str | None: ...

    def get_active_title(self) -> str | None: ...