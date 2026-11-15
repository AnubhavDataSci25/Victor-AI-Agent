"""
Victor Conversational Document Intelligence & RAG Agent — SQLite Metadata Store.

Stores document records, collections, chunks, file hashes, and metadata in data/documents.db
with WAL mode and foreign key constraints.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Dict, List, Optional

from app.rag.models import Document, DocumentChunk, DocumentCollection, DocumentType, IngestionStatus

logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("data/documents.db")


class DocumentStore:
    """Thread-safe SQLite storage for document metadata, chunks, and collections."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    @contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), check_same_thread=False, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        try:
            yield conn
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _init_db(self) -> None:
        with self._lock, self._get_connection() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS collections (
                    collection_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    collection_id TEXT NOT NULL DEFAULT 'default',
                    file_path TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_size_bytes INTEGER NOT NULL,
                    file_hash TEXT NOT NULL,
                    doc_type TEXT NOT NULL,
                    status TEXT NOT NULL,
                    total_pages INTEGER,
                    total_chunks INTEGER DEFAULT 0,
                    error_message TEXT,
                    metadata_json TEXT DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents (file_hash);
                CREATE INDEX IF NOT EXISTS idx_documents_collection ON documents (collection_id);

                CREATE TABLE IF NOT EXISTS chunks (
                    chunk_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    page_number INTEGER,
                    section_title TEXT,
                    sheet_name TEXT,
                    cell_range TEXT,
                    slide_number INTEGER,
                    metadata_json TEXT DEFAULT '{}',
                    token_count INTEGER DEFAULT 0,
                    embedding_index INTEGER,
                    FOREIGN KEY (document_id) REFERENCES documents (document_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks (document_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding ON chunks (embedding_index);

                -- Default collection
                INSERT OR IGNORE INTO collections (collection_id, name, description, created_at, updated_at)
                VALUES ('default', 'Default Collection', 'Default document repository', strftime('%s', 'now'), strftime('%s', 'now'));
                """
            )
            conn.commit()

    # --- Collection Operations ---

    def create_collection(self, collection_id: str, name: str, description: str = "") -> DocumentCollection:
        now = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO collections (collection_id, name, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(collection_id) DO UPDATE SET
                    name = excluded.name,
                    description = excluded.description,
                    updated_at = excluded.updated_at
                """,
                (collection_id, name, description, now, now),
            )
            conn.commit()
        return DocumentCollection(
            collection_id=collection_id,
            name=name,
            description=description,
            created_at=now,
            updated_at=now,
        )

    def get_collection(self, collection_id: str) -> Optional[DocumentCollection]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.*, COUNT(d.document_id) as document_count
                FROM collections c
                LEFT JOIN documents d ON c.collection_id = d.collection_id
                WHERE c.collection_id = ?
                GROUP BY c.collection_id
                """,
                (collection_id,),
            )
            row = cur.fetchone()
            if not row:
                return None
            return DocumentCollection(
                collection_id=row["collection_id"],
                name=row["name"],
                description=row["description"],
                document_count=row["document_count"],
                created_at=row["created_at"],
                updated_at=row["updated_at"],
            )

    def list_collections(self) -> List[DocumentCollection]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                """
                SELECT c.*, COUNT(d.document_id) as document_count
                FROM collections c
                LEFT JOIN documents d ON c.collection_id = d.collection_id
                GROUP BY c.collection_id
                ORDER BY c.name ASC
                """
            )
            return [
                DocumentCollection(
                    collection_id=row["collection_id"],
                    name=row["name"],
                    description=row["description"],
                    document_count=row["document_count"],
                    created_at=row["created_at"],
                    updated_at=row["updated_at"],
                )
                for row in cur.fetchall()
            ]

    # --- Document Operations ---

    def upsert_document(self, document: Document) -> None:
        document.updated_at = time.time()
        with self._lock, self._get_connection() as conn:
            conn.execute(
                """
                INSERT INTO documents (
                    document_id, collection_id, file_path, file_name, file_size_bytes,
                    file_hash, doc_type, status, total_pages, total_chunks,
                    error_message, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    collection_id = excluded.collection_id,
                    file_path = excluded.file_path,
                    file_name = excluded.file_name,
                    file_size_bytes = excluded.file_size_bytes,
                    file_hash = excluded.file_hash,
                    doc_type = excluded.doc_type,
                    status = excluded.status,
                    total_pages = excluded.total_pages,
                    total_chunks = excluded.total_chunks,
                    error_message = excluded.error_message,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    document.document_id,
                    document.collection_id,
                    document.file_path,
                    document.file_name,
                    document.file_size_bytes,
                    document.file_hash,
                    document.doc_type.value,
                    document.status.value,
                    document.total_pages,
                    document.total_chunks,
                    document.error_message,
                    json.dumps(document.metadata),
                    document.created_at,
                    document.updated_at,
                ),
            )
            conn.commit()

    def get_document(self, document_id: str) -> Optional[Document]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM documents WHERE document_id = ?", (document_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_document(row)

    def find_by_hash(self, file_hash: str) -> Optional[Document]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM documents WHERE file_hash = ?", (file_hash,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_document(row)

    def find_by_path(self, file_path: str) -> Optional[Document]:
        resolved = str(Path(file_path).resolve())
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM documents WHERE file_path = ?", (resolved,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_document(row)

    def list_documents(self, collection_id: Optional[str] = None) -> List[Document]:
        with self._lock, self._get_connection() as conn:
            if collection_id:
                cur = conn.execute(
                    "SELECT * FROM documents WHERE collection_id = ? ORDER BY created_at DESC",
                    (collection_id,),
                )
            else:
                cur = conn.execute("SELECT * FROM documents ORDER BY created_at DESC")
            return [self._row_to_document(row) for row in cur.fetchall()]

    def delete_document(self, document_id: str) -> bool:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("DELETE FROM documents WHERE document_id = ?", (document_id,))
            conn.commit()
            return cur.rowcount > 0

    def _row_to_document(self, row: sqlite3.Row) -> Document:
        meta = json.loads(row["metadata_json"] or "{}")
        return Document(
            document_id=row["document_id"],
            collection_id=row["collection_id"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            file_size_bytes=row["file_size_bytes"],
            file_hash=row["file_hash"],
            doc_type=DocumentType(row["doc_type"]),
            status=IngestionStatus(row["status"]),
            total_pages=row["total_pages"],
            total_chunks=row["total_chunks"],
            error_message=row["error_message"],
            metadata=meta,
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # --- Chunk Operations ---

    def insert_chunks(self, chunks: List[DocumentChunk]) -> None:
        if not chunks:
            return
        with self._lock, self._get_connection() as conn:
            # First remove existing chunks for this document
            doc_id = chunks[0].document_id
            conn.execute("DELETE FROM chunks WHERE document_id = ?", (doc_id,))

            conn.executemany(
                """
                INSERT INTO chunks (
                    chunk_id, document_id, chunk_index, content, page_number,
                    section_title, sheet_name, cell_range, slide_number,
                    metadata_json, token_count, embedding_index
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        c.chunk_id,
                        c.document_id,
                        c.chunk_index,
                        c.content,
                        c.page_number,
                        c.section_title,
                        c.sheet_name,
                        c.cell_range,
                        c.slide_number,
                        json.dumps(c.metadata),
                        c.token_count,
                        c.embedding_index,
                    )
                    for c in chunks
                ],
            )
            # Update total_chunks in document
            conn.execute(
                "UPDATE documents SET total_chunks = ?, updated_at = ? WHERE document_id = ?",
                (len(chunks), time.time(), doc_id),
            )
            conn.commit()

    def get_chunks_for_document(self, document_id: str) -> List[DocumentChunk]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute(
                "SELECT * FROM chunks WHERE document_id = ? ORDER BY chunk_index ASC",
                (document_id,),
            )
            return [self._row_to_chunk(row) for row in cur.fetchall()]

    def get_chunks_by_embedding_indices(self, indices: List[int]) -> List[DocumentChunk]:
        if not indices:
            return []
        with self._lock, self._get_connection() as conn:
            placeholders = ",".join("?" for _ in indices)
            cur = conn.execute(
                f"SELECT * FROM chunks WHERE embedding_index IN ({placeholders})",
                indices,
            )
            return [self._row_to_chunk(row) for row in cur.fetchall()]

    def get_chunk(self, chunk_id: str) -> Optional[DocumentChunk]:
        with self._lock, self._get_connection() as conn:
            cur = conn.execute("SELECT * FROM chunks WHERE chunk_id = ?", (chunk_id,))
            row = cur.fetchone()
            if not row:
                return None
            return self._row_to_chunk(row)

    def _row_to_chunk(self, row: sqlite3.Row) -> DocumentChunk:
        meta = json.loads(row["metadata_json"] or "{}")
        return DocumentChunk(
            chunk_id=row["chunk_id"],
            document_id=row["document_id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            page_number=row["page_number"],
            section_title=row["section_title"],
            sheet_name=row["sheet_name"],
            cell_range=row["cell_range"],
            slide_number=row["slide_number"],
            metadata=meta,
            token_count=row["token_count"],
            embedding_index=row["embedding_index"],
        )
