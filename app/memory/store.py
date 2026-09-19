"""
Memory Store — Local SQLite persistence layer for Victor's long-term memory.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class MemoryRecord:
    key: str
    content: str
    category: str = "preference"
    tags: List[str] = field(default_factory=list)
    id: Optional[int] = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    access_count: int = 0
    last_accessed_at: Optional[float] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "key": self.key,
            "content": self.content,
            "category": self.category,
            "tags": self.tags,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "access_count": self.access_count,
            "last_accessed_at": self.last_accessed_at,
        }

    def format_snippet(self) -> str:
        """Formats a compact memory snippet for prompt context."""
        return f"{self.key}: {self.content}"


class MemoryStore:
    """SQLite-backed structured memory storage with FTS5 and keyword indexing."""

    def __init__(self, db_path: str = "config/memory.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._has_fts = False
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA synchronous = NORMAL")
        return conn

    def _init_db(self) -> None:
        """Initializes tables, indexes, and full-text search."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA journal_mode = WAL;")
            cursor.execute("PRAGMA synchronous = NORMAL;")
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL,
                    key TEXT NOT NULL UNIQUE,
                    content TEXT NOT NULL,
                    tags TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    access_count INTEGER NOT NULL DEFAULT 0,
                    last_accessed_at REAL
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key)")

            # Check FTS5 availability
            try:
                cursor.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        key,
                        content,
                        tags,
                        content=memories,
                        content_rowid=id
                    )
                """)
                # Setup triggers to keep FTS5 synchronized with memories table
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, key, content, tags)
                        VALUES (new.id, new.key, new.content, new.tags);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, key, content, tags)
                        VALUES('delete', old.id, old.key, old.content, old.tags);
                    END;
                """)
                cursor.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, key, content, tags)
                        VALUES('delete', old.id, old.key, old.content, old.tags);
                        INSERT INTO memories_fts(rowid, key, content, tags)
                        VALUES (new.id, new.key, new.content, new.tags);
                    END;
                """)
                self._has_fts = True
            except Exception as e:
                logger.debug(f"FTS5 not enabled in SQLite; falling back to LIKE index: {e}")
                self._has_fts = False

            conn.commit()

    def add_or_update(
        self,
        key: str,
        content: str,
        category: str = "preference",
        tags: Optional[List[str]] = None,
    ) -> MemoryRecord:
        """Stores or updates a memory record."""
        now = time.time()
        tags_list = [t.strip().lower() for t in (tags or []) if t.strip()]
        tags_str = ",".join(tags_list)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO memories (category, key, content, tags, created_at, updated_at, access_count, last_accessed_at)
                VALUES (?, ?, ?, ?, ?, ?, 0, NULL)
                ON CONFLICT(key) DO UPDATE SET
                    content=excluded.content,
                    category=excluded.category,
                    tags=excluded.tags,
                    updated_at=excluded.updated_at
                """,
                (category.lower(), key.strip(), content.strip(), tags_str, now, now),
            )
            conn.commit()

            return self.get(key)

    def get(self, key: str) -> Optional[MemoryRecord]:
        """Retrieves a memory record by exact key and updates its access telemetry."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories WHERE key = ?", (key.strip(),))
            row = cursor.fetchone()
            if not row:
                return None

            now = time.time()
            cursor.execute(
                "UPDATE memories SET access_count = access_count + 1, last_accessed_at = ? WHERE id = ?",
                (now, row["id"]),
            )
            conn.commit()

            return self._row_to_record(row, access_count=row["access_count"] + 1, last_accessed_at=now)

    def delete(self, key: str) -> bool:
        """Deletes a memory record by key."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories WHERE key = ?", (key.strip(),))
            conn.commit()
            return cursor.rowcount > 0

    def search(
        self,
        query: str,
        limit: int = 3,
        category: Optional[str] = None,
    ) -> List[MemoryRecord]:
        """
        Retrieves the smallest relevant subset of memories using:
        1. Exact key match
        2. Keyword / tag overlap
        3. Full-Text Search (FTS5) or LIKE fallback
        Prioritizes exact, recent, and frequently accessed items.
        """
        if not query or not query.strip():
            return []

        clean_query = query.strip()
        tokens = [t.lower() for t in clean_query.split() if len(t) > 2]

        results_dict: dict[int, tuple[float, MemoryRecord]] = {}

        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Pass 1: Exact key or substring key match (highest priority: score = 100)
            key_query = "SELECT * FROM memories WHERE key = ?"
            params: list[Any] = [clean_query]
            if category:
                key_query += " AND category = ?"
                params.append(category.lower())

            cursor.execute(key_query, tuple(params))
            for row in cursor.fetchall():
                rec = self._row_to_record(row)
                results_dict[row["id"]] = (100.0, rec)

            # Pass 2: FTS5 match (if available) or LIKE match
            if self._has_fts and tokens:
                try:
                    # Clean tokens for FTS5 syntax
                    fts_query_str = " OR ".join([f'"{t}"*' for t in tokens])
                    fts_sql = """
                        SELECT m.*, bm25(memories_fts) as rank
                        FROM memories_fts f
                        JOIN memories m ON f.rowid = m.id
                        WHERE memories_fts MATCH ?
                    """
                    fts_params: list[Any] = [fts_query_str]
                    if category:
                        fts_sql += " AND m.category = ?"
                        fts_params.append(category.lower())
                    fts_sql += " ORDER BY rank LIMIT ?"
                    fts_params.append(limit * 2)

                    cursor.execute(fts_sql, tuple(fts_params))
                    for row in cursor.fetchall():
                        rec_id = row["id"]
                        score = 50.0 - float(row["rank"])  # lower rank is better in bm25
                        if rec_id not in results_dict or results_dict[rec_id][0] < score:
                            results_dict[rec_id] = (score, self._row_to_record(row))
                except Exception as e:
                    logger.debug(f"FTS5 match failed: {e}")

            # Pass 3: Keyword / token match across tags, content, key (score = 10 per token match)
            if len(results_dict) < limit and tokens:
                like_clauses = []
                like_params = []
                for token in tokens:
                    like_clauses.append("(key LIKE ? OR content LIKE ? OR tags LIKE ?)")
                    like_params.extend([f"%{token}%", f"%{token}%", f"%{token}%"])

                sql = f"SELECT * FROM memories WHERE ({' OR '.join(like_clauses)})"
                if category:
                    sql += " AND category = ?"
                    like_params.append(category.lower())
                sql += " ORDER BY updated_at DESC LIMIT ?"
                like_params.append(limit * 2)

                cursor.execute(sql, tuple(like_params))
                for row in cursor.fetchall():
                    rec_id = row["id"]
                    # Calculate token hit score
                    row_text = f"{row['key']} {row['content']} {row['tags']}".lower()
                    hits = sum(1 for t in tokens if t in row_text)
                    score = hits * 10.0 + (1.0 if row["category"] == "preference" else 0.0)
                    if rec_id not in results_dict or results_dict[rec_id][0] < score:
                        results_dict[rec_id] = (score, self._row_to_record(row))

            # Sort results by score (descending) and updated_at
            sorted_records = sorted(
                results_dict.values(),
                key=lambda x: (x[0], x[1].updated_at),
                reverse=True
            )

            return [r for _, r in sorted_records[:limit]]

    def list_by_category(self, category: str, limit: int = 10) -> List[MemoryRecord]:
        """Lists records within a specific category."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM memories WHERE category = ? ORDER BY updated_at DESC LIMIT ?",
                (category.lower(), limit),
            )
            return [self._row_to_record(r) for r in cursor.fetchall()]

    def list_all(self, limit: int = 50) -> List[MemoryRecord]:
        """Lists all records up to limit."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM memories ORDER BY updated_at DESC LIMIT ?", (limit,))
            return [self._row_to_record(r) for r in cursor.fetchall()]

    def count(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM memories")
            return cursor.fetchone()[0]

    def clear(self) -> None:
        """Empties the memory store (primarily for testing)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM memories")
            conn.commit()

    @staticmethod
    def _row_to_record(
        row: sqlite3.Row,
        access_count: Optional[int] = None,
        last_accessed_at: Optional[float] = None
    ) -> MemoryRecord:
        tags_raw = row["tags"] or ""
        tags = [t.strip() for t in tags_raw.split(",") if t.strip()]
        return MemoryRecord(
            id=row["id"],
            category=row["category"],
            key=row["key"],
            content=row["content"],
            tags=tags,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            access_count=access_count if access_count is not None else row["access_count"],
            last_accessed_at=last_accessed_at if last_accessed_at is not None else row["last_accessed_at"],
        )
