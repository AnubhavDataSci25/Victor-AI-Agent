"""
Memory Tools for Victor 2.0.

Exposes memory_remember, memory_recall, and memory_forget to Gemini Live.
"""

from __future__ import annotations

import logging
from typing import Optional

from app.memory.manager import MemoryManager
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Shared memory manager singleton for tools
_memory_manager: Optional[MemoryManager] = None


def get_shared_memory_manager() -> MemoryManager:
    global _memory_manager
    if _memory_manager is None:
        from app.config import load_config
        config = load_config()
        _memory_manager = MemoryManager(
            db_path=config.memory.db_path,
            max_recall_results=config.memory.max_recall_results,
        )
    return _memory_manager


class MemoryRememberTool(BaseTool):
    name = "memory_remember"
    description = (
        "Saves a useful fact, user preference, project detail, or stable context to long-term memory. "
        "Use when the user explicitly says 'Remember that...', 'Note that...', 'My preference is...', "
        "or shares important stable information. Do NOT store passwords, PINs, or API keys."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "Short identifier/topic for this memory (e.g., 'preferred_language', 'victor_project_models')."
            },
            "content": {
                "type": "string",
                "description": "The exact fact, preference, or detail to remember."
            },
            "category": {
                "type": "string",
                "enum": ["preference", "project", "user_fact", "system"],
                "default": "preference",
                "description": "The category of the memory."
            },
            "tags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional search keywords or tags to make recall fast and accurate."
            }
        },
        "required": ["key", "content"]
    }

    def __init__(self, manager: Optional[MemoryManager] = None):
        self.manager = manager or get_shared_memory_manager()

    async def execute(self, args: dict) -> str:
        key = args.get("key", "")
        content = args.get("content", "")
        category = args.get("category", "preference")
        tags = args.get("tags") or []

        success, message = self.manager.remember(
            key=key,
            content=content,
            category=category,
            tags=tags,
        )
        return message


class MemoryRecallTool(BaseTool):
    name = "memory_recall"
    description = (
        "Searches long-term memory for relevant facts, preferences, or past project details. "
        "Use when the user asks about previously shared information, preferences, or project settings."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search term, question, or keywords to find relevant memories for."
            },
            "category": {
                "type": "string",
                "description": "Optional category filter (e.g. 'preference', 'project')."
            }
        },
        "required": ["query"]
    }

    def __init__(self, manager: Optional[MemoryManager] = None):
        self.manager = manager or get_shared_memory_manager()

    async def execute(self, args: dict) -> str:
        query = args.get("query", "")
        category = args.get("category")

        records = self.manager.recall(query=query, category=category)
        if not records:
            return f"No memories found matching '{query}'."

        lines = [f"Found {len(records)} relevant memory item(s):"]
        for r in records:
            lines.append(f"• [{r.category}] {r.key}: {r.content}")
        return "\n".join(lines)


class MemoryForgetTool(BaseTool):
    name = "memory_forget"
    description = (
        "Removes a specific memory item from long-term memory by its key when the user explicitly asks to forget or remove it."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {
                "type": "string",
                "description": "The key of the memory to remove."
            }
        },
        "required": ["key"]
    }

    def __init__(self, manager: Optional[MemoryManager] = None):
        self.manager = manager or get_shared_memory_manager()

    async def execute(self, args: dict) -> str:
        key = args.get("key", "")
        deleted = self.manager.forget(key)
        if deleted:
            return f"Successfully removed '{key}' from memory."
        return f"No memory found with key '{key}'."
