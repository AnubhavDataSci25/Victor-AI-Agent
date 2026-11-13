"""
Victor Autonomous Email Assistant — Persistent SQLite Store.

Persists drafts, scheduled emails (with approved_hash integrity), and
restricted AutoSendPolicy settings across restarts.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
from typing import Optional

from app.email_assistant.models import (
    AutoSendPolicy,
    EmailDraft,
    ScheduledEmailRecord,
    ScheduledEmailStatus,
)

_DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "email_assistant.db"


class EmailAssistantStore:
    """SQLite persistence for drafts, scheduled sends, and auto-send policy."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or _DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_drafts (
                    draft_id TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS scheduled_emails (
                    schedule_id TEXT PRIMARY KEY,
                    send_at REAL NOT NULL,
                    status TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_settings (
                    key TEXT PRIMARY KEY,
                    value_json TEXT NOT NULL
                )
                """
            )
            conn.commit()

    # --- Drafts ---
    def save_draft(self, draft: EmailDraft) -> None:
        draft.updated_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_drafts (draft_id, data_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(draft_id) DO UPDATE SET
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (draft.draft_id, draft.model_dump_json(), draft.updated_at),
            )
            conn.commit()

    def get_draft(self, draft_id: str) -> Optional[EmailDraft]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM email_drafts WHERE draft_id = ?",
                (draft_id,),
            ).fetchone()
            if not row:
                return None
            return EmailDraft.model_validate_json(row["data_json"])

    def get_latest_active_draft(self) -> Optional[EmailDraft]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data_json FROM email_drafts ORDER BY updated_at DESC LIMIT 10"
            ).fetchall()
            for r in rows:
                d = EmailDraft.model_validate_json(r["data_json"])
                if d.status in ("DRAFT", "APPROVED"):
                    return d
        return None

    # --- Scheduled Emails ---
    def save_scheduled_email(self, rec: ScheduledEmailRecord) -> None:
        rec.updated_at = time.time()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO scheduled_emails (schedule_id, send_at, status, data_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(schedule_id) DO UPDATE SET
                    send_at = excluded.send_at,
                    status = excluded.status,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at
                """,
                (rec.schedule_id, rec.send_at, rec.status.value, rec.model_dump_json(), rec.updated_at),
            )
            conn.commit()

    def get_scheduled_email(self, schedule_id: str) -> Optional[ScheduledEmailRecord]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM scheduled_emails WHERE schedule_id = ?",
                (schedule_id,),
            ).fetchone()
            if not row:
                return None
            return ScheduledEmailRecord.model_validate_json(row["data_json"])

    def list_scheduled_emails(self, status: Optional[ScheduledEmailStatus] = None) -> list[ScheduledEmailRecord]:
        with self._connect() as conn:
            if status is not None:
                rows = conn.execute(
                    "SELECT data_json FROM scheduled_emails WHERE status = ? ORDER BY send_at ASC",
                    (status.value,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT data_json FROM scheduled_emails ORDER BY send_at ASC"
                ).fetchall()
            return [ScheduledEmailRecord.model_validate_json(r["data_json"]) for r in rows]

    def get_due_scheduled_emails(self, now: float) -> list[ScheduledEmailRecord]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT data_json FROM scheduled_emails WHERE status = ? AND send_at <= ? ORDER BY send_at ASC",
                (ScheduledEmailStatus.PENDING.value, now),
            ).fetchall()
            return [ScheduledEmailRecord.model_validate_json(r["data_json"]) for r in rows]

    # --- Restricted Auto-Send Policy ---
    def get_auto_send_policy(self) -> AutoSendPolicy:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM email_settings WHERE key = 'auto_send_policy'"
            ).fetchone()
            if not row:
                return AutoSendPolicy()
            return AutoSendPolicy.model_validate_json(row["value_json"])

    def save_auto_send_policy(self, policy: AutoSendPolicy) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_settings (key, value_json)
                VALUES ('auto_send_policy', ?)
                ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
                """,
                (policy.model_dump_json(),),
            )
            conn.commit()
