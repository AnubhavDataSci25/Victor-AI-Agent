"""
Session Memory — Ephemeral in-memory context and task state bounded to the active session.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SessionTurn:
    role: str
    text: str
    timestamp: float = field(default_factory=time.time)


class SessionMemory:
    """In-memory rolling buffer for current conversation context and temporary task state."""

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self._turns: List[SessionTurn] = []
        self._state: Dict[str, Any] = {}

    def add_turn(self, role: str, text: str) -> None:
        """Appends a turn and maintains the maximum window size."""
        if not text or not text.strip():
            return
        self._turns.append(SessionTurn(role=role, text=text.strip()))
        if len(self._turns) > self.max_turns:
            self._turns.pop(0)

    def get_recent_turns(self, count: int = 5) -> List[SessionTurn]:
        """Returns the most recent N turns."""
        return self._turns[-count:]

    def set_variable(self, key: str, value: Any) -> None:
        """Stores ephemeral session state (e.g. active topic, working file)."""
        self._state[key] = value

    def get_variable(self, key: str, default: Any = None) -> Any:
        """Retrieves ephemeral session state."""
        return self._state.get(key, default)

    def delete_variable(self, key: str) -> None:
        self._state.pop(key, None)

    def clear(self) -> None:
        """Clears all in-memory context when session is locked or closed."""
        self._turns.clear()
        self._state.clear()

    def format_recent_context(self, count: int = 4) -> str:
        """Formats the last N conversation turns into a compact string."""
        recent = self.get_recent_turns(count)
        if not recent:
            return ""
        lines = [f"[{t.role.capitalize()}]: {t.text}" for t in recent]
        return "\n".join(lines)
