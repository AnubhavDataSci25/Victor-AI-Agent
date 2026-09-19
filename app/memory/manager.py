"""
Memory Manager — Unified interface coordinating short-term session memory and long-term SQLite memory.
"""

from __future__ import annotations

import logging
import re
from typing import Any, List, Optional, Tuple

from app.memory.sanitizer import MemorySanitizer
from app.memory.session_memory import SessionMemory
from app.memory.store import MemoryRecord, MemoryStore

logger = logging.getLogger(__name__)


class MemoryManager:
    """Lightweight memory and context coordinator."""

    def __init__(self, db_path: str = "config/memory.db", max_recall_results: int = 3):
        self.store = MemoryStore(db_path=db_path)
        self.session = SessionMemory(max_turns=10)
        self.max_recall_results = max_recall_results

    def remember(
        self,
        key: str,
        content: str,
        category: str = "preference",
        tags: Optional[List[str]] = None,
    ) -> Tuple[bool, str]:
        """
        Stores a structured piece of knowledge or preference in long-term memory.
        Enforces strict credential sanitization to prevent storing secrets.
        """
        clean_key = MemorySanitizer.sanitize_text(key)
        clean_content = MemorySanitizer.sanitize_text(content)

        if not clean_key or not clean_content:
            return False, "Memory key and content cannot be empty."

        # Security check: Never store sensitive credentials
        is_sensitive, reason = MemorySanitizer.is_sensitive(f"{clean_key} {clean_content}")
        if is_sensitive:
            logger.warning(f"MemoryManager rejected sensitive memory write: {reason}")
            return False, f"Storage Refused: {reason}"

        # Clean tags
        clean_tags = [MemorySanitizer.sanitize_text(t) for t in (tags or []) if t.strip()]

        try:
            self.store.add_or_update(
                key=clean_key,
                content=clean_content,
                category=category,
                tags=clean_tags,
            )
            logger.info(f"Memory stored: [{category}] '{clean_key}'")
            return True, f"Successfully remembered '{clean_key}'."
        except Exception as e:
            logger.error(f"Failed to store memory: {e}")
            return False, f"Database error storing memory: {str(e)}"

    def recall(
        self,
        query: str,
        limit: Optional[int] = None,
        category: Optional[str] = None,
    ) -> List[MemoryRecord]:
        """Retrieves top relevant memories using local deterministic SQLite search (< 1ms)."""
        max_items = limit or self.max_recall_results
        return self.store.search(query=query, limit=max_items, category=category)

    def forget(self, key: str) -> bool:
        """Removes a memory item by key."""
        deleted = self.store.delete(key)
        if deleted:
            logger.info(f"Memory forgotten: '{key}'")
        return deleted

    def get_relevant_context(self, query_or_text: str, max_items: int = 2) -> str:
        """
        Returns a compact context snippet if any stored memories match the query.
        Zero Gemini calls, executes in < 1ms locally.
        """
        matches = self.recall(query=query_or_text, limit=max_items)
        if not matches:
            return ""

        lines = [
            "[USER PREFERENCES & CONTEXT (Current user instructions always override background memory):"
        ]
        for m in matches:
            lines.append(f" • {m.key}: {m.content}")
        lines.append("]")
        return "\n".join(lines)

    def get_core_profile_context(self, limit: int = 5) -> str:
        """
        Returns stable top user preferences formatted for inclusion in
        the session system instruction at connection time.
        """
        prefs = self.store.list_by_category("preference", limit=limit)
        if not prefs:
            return ""

        items = [f"{p.key}: {p.content}" for p in prefs]
        return "Known user preferences: " + "; ".join(items) + "."

    def extract_and_store_preference(self, text: str) -> Optional[str]:
        """
        Lightweight heuristic rule extractor for natural preference statements.
        Runs asynchronously / after turn without blocking or making LLM calls.
        Example: "My preferred coding language is Python."
        """
        if not text:
            return None

        clean = text.strip()

        # Pattern 1: "My preferred [thing] is [value]"
        m1 = re.search(r"\bmy\s+preferred\s+([a-zA-Z0-9_\s]{2,25})\s+is\s+([a-zA-Z0-9_\-\+\#\.\s]{1,40})\b", clean, re.IGNORECASE)
        if m1:
            thing = m1.group(1).strip().lower().replace(" ", "_")
            value = m1.group(2).strip()
            key = f"preferred_{thing}"
            success, _ = self.remember(key=key, content=value, category="preference", tags=[thing, value])
            if success:
                return key

        # Pattern 2: "Remember that [statement]"
        m2 = re.search(r"\bremember\s+that\s+(.+)$", clean, re.IGNORECASE)
        if m2:
            statement = m2.group(1).strip().rstrip(".")
            # Build key from first few words
            words = re.findall(r"\w+", statement)
            key = "_".join(words[:4]).lower() if words else "user_note"
            success, _ = self.remember(key=key, content=statement, category="project", tags=words[:5])
            if success:
                return key

        return None
