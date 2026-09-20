"""
Comprehensive test suite for Victor's Memory & Context Manager.

Tests:
- MemoryStore (SQLite persistence, FTS5/LIKE indexing, access count telemetry)
- MemorySanitizer (rejection of credentials, passwords, PINs, API keys)
- SessionMemory (short-term ephemeral buffer, rolling window, lock cleanup)
- MemoryManager (coordination, Example 1 & Example 2 workflows, context snippet generation)
- Memory Tools (memory_remember, memory_recall, memory_forget)
- Low latency (< 5ms local retrieval benchmark)
"""

import time
import pytest
from pathlib import Path

from app.memory.sanitizer import MemorySanitizer
from app.memory.session_memory import SessionMemory
from app.memory.store import MemoryRecord, MemoryStore
from app.memory.manager import MemoryManager
from app.tools.memory.tool import (
    MemoryForgetTool,
    MemoryRecallTool,
    MemoryRememberTool,
)
from app.tools.tool_setup import build_tool_registry


# ---------------------------------------------------------------------------
# 1. Sanitizer Tests (Credential & Privacy Safety)
# ---------------------------------------------------------------------------

def test_sanitizer_rejects_api_keys():
    """Verify API keys for Gemini, OpenAI, GitHub, and generic keys are rejected."""
    # Gemini API key format
    is_sens, desc = MemorySanitizer.is_sensitive("AIzaSyDummyKeyForTesting1234567890abcde")
    assert is_sens is True
    assert "API Key" in desc

    # OpenAI key format
    is_sens, desc = MemorySanitizer.is_sensitive("My key is sk-1234567890abcdef1234567890abcdef")
    assert is_sens is True

    # GitHub PAT
    is_sens, desc = MemorySanitizer.is_sensitive("ghp_123456789012345678901234567890123456")
    assert is_sens is True


def test_sanitizer_rejects_passwords_and_pins():
    """Verify passwords and PINs are rejected."""
    # Password
    is_sens, _ = MemorySanitizer.is_sensitive("My password is SuperSecretPassword123!")
    assert is_sens is True

    is_sens, _ = MemorySanitizer.is_sensitive("password: MyPassword#1")
    assert is_sens is True

    # PIN
    is_sens, _ = MemorySanitizer.is_sensitive("my pin is 5432")
    assert is_sens is True

    is_sens, _ = MemorySanitizer.is_sensitive("pin: 987654")
    assert is_sens is True


def test_sanitizer_allows_safe_preferences_and_facts():
    """Verify normal preferences and project facts are accepted."""
    safe_texts = [
        "My preferred coding language is Python.",
        "Remember that my Victor project uses Gemini 3.8 Live for voice and Gemini 3.8 Flash for screen analysis.",
        "User prefers dark mode UI and concise responses.",
        "Anubhav Yadav is 21 years old and studies MCA Data Science.",
        "The project root is at E:\\Victor AI Agent.",
    ]
    for text in safe_texts:
        is_sens, _ = MemorySanitizer.is_sensitive(text)
        assert is_sens is False, f"Expected '{text}' to be safe, but was flagged as sensitive."


# ---------------------------------------------------------------------------
# 2. SQLite MemoryStore Tests
# ---------------------------------------------------------------------------

def test_memory_store_lifecycle(tmp_path):
    """Test insert, get, update, search, delete in SQLite store."""
    db_file = tmp_path / "test_memory.db"
    store = MemoryStore(db_path=str(db_file))

    # 1. Insert record
    rec = store.add_or_update(
        key="preferred_language",
        content="Python",
        category="preference",
        tags=["coding", "python", "backend"]
    )
    assert rec.key == "preferred_language"
    assert rec.content == "Python"
    assert "python" in rec.tags
    assert store.count() == 1

    # 2. Get record and check telemetry
    fetched = store.get("preferred_language")
    assert fetched is not None
    assert fetched.access_count >= 1
    assert fetched.last_accessed_at is not None

    # 3. Update existing record
    store.add_or_update(
        key="preferred_language",
        content="Python 3.11+",
        category="preference",
        tags=["coding", "python", "modern"]
    )
    assert store.count() == 1  # Should not create duplicate
    updated = store.get("preferred_language")
    assert updated.content == "Python 3.11+"

    # 4. Search
    results = store.search("Python", limit=3)
    assert len(results) == 1
    assert results[0].key == "preferred_language"

    # 5. Delete
    deleted = store.delete("preferred_language")
    assert deleted is True
    assert store.get("preferred_language") is None
    assert store.count() == 0


# ---------------------------------------------------------------------------
# 3. Short-Term Session Memory Tests
# ---------------------------------------------------------------------------

def test_session_memory_rolling_buffer():
    """Verify session memory maintains a bounded rolling window of turns."""
    session = SessionMemory(max_turns=3)

    session.add_turn("user", "Hello")
    session.add_turn("assistant", "Hi there!")
    session.add_turn("user", "Help with code")
    session.add_turn("assistant", "Sure, what code?")

    # Window was 3, oldest turn ("Hello") should be dropped
    turns = session.get_recent_turns(10)
    assert len(turns) == 3
    assert turns[0].text == "Hi there!"
    assert turns[2].text == "Sure, what code?"


def test_session_memory_state_and_clear():
    """Verify session variables and cleanup on session lock."""
    session = SessionMemory()
    session.set_variable("active_file", "main.py")
    session.set_variable("current_task", "debugging")

    assert session.get_variable("active_file") == "main.py"
    assert session.get_variable("current_task") == "debugging"

    session.clear()
    assert session.get_variable("active_file") is None
    assert len(session.get_recent_turns(5)) == 0


# ---------------------------------------------------------------------------
# 4. MemoryManager — Example 1 & Example 2 Scenarios
# ---------------------------------------------------------------------------

def test_example_1_user_preference_retrieval(tmp_path):
    """
    Example 1:
    User says: 'My preferred coding language is Python.' -> Victor stores preference
    Later user asks: 'Help me write a backend' -> Memory Manager retrieves only Python preference
    """
    db_file = tmp_path / "example1.db"
    manager = MemoryManager(db_path=str(db_file))

    # Step 1: User states preference
    success, msg = manager.remember(
        key="preferred_coding_language",
        content="Python",
        category="preference",
        tags=["coding", "language", "python", "backend"]
    )
    assert success is True

    # Also store unrelated memory to ensure it is NOT returned
    manager.remember(
        key="favorite_music_genre",
        content="Synthwave and Lo-Fi",
        category="preference",
        tags=["music", "songs"]
    )

    # Step 2: Later user asks to write a backend
    query = "Help me write a backend"
    relevant = manager.recall(query=query, limit=2)

    assert len(relevant) == 1
    assert relevant[0].key == "preferred_coding_language"
    assert "Python" in relevant[0].content
    # Ensure unrelated memory was not retrieved
    assert not any(r.key == "favorite_music_genre" for r in relevant)

    # Step 3: Check formatted context snippet
    context_snippet = manager.get_relevant_context(query)
    assert "preferred_coding_language: Python" in context_snippet
    assert "Current user instructions always override" in context_snippet
    assert "Synthwave" not in context_snippet


def test_example_2_project_context_retrieval(tmp_path):
    """
    Example 2:
    User says: 'Remember that my Victor project uses Gemini 3.8 Live for voice and Gemini 3.8 Flash for screen analysis.'
    Later user asks: 'Which model handles screen analysis?'
    Memory Manager retrieves the relevant project memory without loading unrelated memories.
    """
    db_file = tmp_path / "example2.db"
    manager = MemoryManager(db_path=str(db_file))

    # Step 1: Store structured project context
    project_fact = "Uses Gemini 3.8 Live for voice and Gemini 3.8 Flash for screen analysis."
    success, _ = manager.remember(
        key="victor_project_models",
        content=project_fact,
        category="project",
        tags=["victor", "models", "gemini", "voice", "screen_analysis", "flash"]
    )
    assert success is True

    # Add other unrelated project facts
    manager.remember(
        key="victor_auth_mode",
        content="Victor 2.0 uses Argon2id PIN-based authentication.",
        category="project",
        tags=["auth", "pin", "security"]
    )

    # Step 2: Later user asks about screen analysis model
    query = "Which model handles screen analysis?"
    relevant = manager.recall(query=query, limit=2)

    assert len(relevant) >= 1
    assert relevant[0].key == "victor_project_models"
    assert "Gemini 3.8 Flash for screen analysis" in relevant[0].content

    # Step 3: Context snippet contains only the relevant project memory
    context_snippet = manager.get_relevant_context(query)
    assert "victor_project_models" in context_snippet
    assert "Gemini 3.8 Flash for screen analysis" in context_snippet
    assert "Argon2id" not in context_snippet  # Unrelated memory omitted


def test_memory_manager_rejects_credentials(tmp_path):
    """Verify MemoryManager strictly refuses to store sensitive credentials."""
    db_file = tmp_path / "sensitive.db"
    manager = MemoryManager(db_path=str(db_file))

    # Attempt to store API key
    ok, msg = manager.remember(
        key="my_gemini_key",
        content="AIzaSyDummyKeyForTesting1234567890abcde",
        category="system"
    )
    assert ok is False
    assert "Storage Refused" in msg
    assert manager.store.count() == 0

    # Attempt to store PIN
    ok_pin, msg_pin = manager.remember(
        key="my_pin",
        content="my pin is 1234",
        category="preference"
    )
    assert ok_pin is False
    assert "Storage Refused" in msg_pin


def test_heuristic_preference_extraction(tmp_path):
    """Verify asynchronous heuristic preference extraction without LLM calls."""
    db_file = tmp_path / "heuristic.db"
    manager = MemoryManager(db_path=str(db_file))

    # Test "My preferred [thing] is [val]"
    key1 = manager.extract_and_store_preference("My preferred coding language is Python")
    assert key1 == "preferred_coding_language"
    rec1 = manager.store.get("preferred_coding_language")
    assert rec1 is not None
    assert rec1.content == "Python"

    # Test "Remember that [statement]"
    key2 = manager.extract_and_store_preference("Remember that we use FastAPI for the backend server")
    assert key2 is not None
    rec2 = manager.store.get(key2)
    assert rec2 is not None
    assert "FastAPI" in rec2.content


# ---------------------------------------------------------------------------
# 5. Memory Tools & Registry Integration
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_memory_tools_execution(tmp_path):
    """Test MemoryRememberTool, MemoryRecallTool, and MemoryForgetTool."""
    db_file = tmp_path / "tools.db"
    manager = MemoryManager(db_path=str(db_file))

    remember_tool = MemoryRememberTool(manager=manager)
    recall_tool = MemoryRecallTool(manager=manager)
    forget_tool = MemoryForgetTool(manager=manager)

    # 1. Test remember tool
    rem_res = await remember_tool.execute({
        "key": "test_preference",
        "content": "Prefers concise voice responses",
        "category": "preference",
        "tags": ["voice", "responses"]
    })
    assert "Successfully remembered" in rem_res

    # 2. Test recall tool
    rec_res = await recall_tool.execute({"query": "voice responses"})
    assert "Found 1 relevant memory" in rec_res
    assert "test_preference" in rec_res

    # 3. Test forget tool
    forg_res = await forget_tool.execute({"key": "test_preference"})
    assert "Successfully removed" in forg_res

    # Verify gone
    rec_after = await recall_tool.execute({"query": "voice responses"})
    assert "No memories found" in rec_after


def test_tool_registry_contains_memory_tools():
    """Verify memory tools are registered in the global ToolRegistry."""
    registry = build_tool_registry()
    names = [t["name"] for t in registry.list_tools()]

    assert "memory_remember" in names
    assert "memory_recall" in names
    assert "memory_forget" in names


# ---------------------------------------------------------------------------
# 6. Performance Benchmark Test
# ---------------------------------------------------------------------------

def test_local_retrieval_latency_benchmark(tmp_path):
    """Verify local SQLite retrieval executes in under 5 milliseconds."""
    db_file = tmp_path / "perf.db"
    manager = MemoryManager(db_path=str(db_file))

    # Populate 25 memories
    for i in range(25):
        manager.remember(
            key=f"setting_{i}",
            content=f"Configuration value for setting {i} with tags and info",
            category="project" if i % 2 == 0 else "preference",
            tags=[f"tag_{i}", "common", "config"]
        )

    # Benchmark 20 recall searches
    start = time.perf_counter()
    for _ in range(20):
        manager.recall("setting 15 config")
    elapsed = time.perf_counter() - start

    avg_ms = (elapsed / 20) * 1000
    assert avg_ms < 5.0, f"Average recall latency was {avg_ms:.2f}ms, expected < 5.0ms"
