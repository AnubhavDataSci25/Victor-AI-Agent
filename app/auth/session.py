"""
Session - tracks whether an unlocked session is still within its
inactivity timeout (spec section 10). Deliberately separate from
AuthManager: this class only knows about time, not about phrases,
attempts, or lockouts.

A `clock` callable is injectable so tests can control time
deterministically instead of sleeping in real time.
"""

from __future__ import annotations

import time
from typing import Callable


class Session:
    def __init__(
        self,
        timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._expires_at: float | None = None

    def start(self) -> None:
        """Begin (or restart) the session's inactivity window."""
        self._expires_at = self._clock() + self._timeout_seconds

    def extend(self) -> None:
        """Reset the inactivity window from now, e.g. on tool use."""
        self.start()

    def end(self) -> None:
        self._expires_at = None

    def is_active(self) -> bool:
        return self._expires_at is not None and self._clock() < self._expires_at

    def remaining_seconds(self) -> float:
        if self._expires_at is None:
            return 0.0
        return max(0.0, self._expires_at - self._clock())