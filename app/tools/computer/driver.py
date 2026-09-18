"""
ComputerDriver - the interface every computer-control tool talks to,
never the OS directly.

Why this exists: PyAutoGUI, psutil, and Windows-specific launch logic
all need a real display and a real OS to run against, which makes
them impossible to unit test in CI or on a developer's Linux/Mac
machine. By putting a Protocol between the tools and the OS, tool
logic (argument validation, permission classification, structured
results, verification) can be fully tested against a FakeComputerDriver,
while the real WindowsComputerDriver is exercised manually / in
integration testing on an actual Windows machine.

This mirrors the same principle as the tool/registry split: the thing
that decides *whether* an action is safe should be testable
independently of the thing that actually *performs* it.
"""

from __future__ import annotations

from typing import Protocol


class DriverError(Exception):
    """Raised by a ComputerDriver implementation when an OS-level
    action fails. Tools catch this and turn it into a failed
    ToolResult rather than letting it propagate as a raw exception."""


class ComputerDriver(Protocol):
    def open_application(self, command: str) -> None:
        """Launch an application given a whitelisted launch command."""
        ...

    def close_application(self, process_name: str) -> bool:
        """Terminate all processes matching process_name. Returns True
        if at least one process was found and asked to terminate."""
        ...

    def is_process_running(self, process_name: str) -> bool:
        ...

    def focus_window(self, title: str) -> bool:
        """Bring the first window whose title contains `title` to the
        foreground. Returns True if a matching window was found."""
        ...

    def switch_window(self, title: str) -> bool:
        """Switch focus to a window by title. Distinct from
        focus_window at the tool/permission level even though the
        underlying action is often the same."""
        ...

    def get_active_window_title(self) -> str | None:
        ...

    def type_text(self, text: str) -> None:
        ...

    def press_key(self, key: str) -> None:
        ...

    def hotkey(self, keys: list[str]) -> None:
        ...

    def take_screenshot(self) -> bytes:
        """Return a PNG-encoded screenshot of the current screen."""
        ...