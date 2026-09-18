"""
SecretStore - local, file-based storage for the Argon2id hash of
Victor's security phrase (spec section 9).

Stores exactly one field: phrase_hash. Never the phrase itself. The
file is git-ignored by default (see .gitignore: config/secrets.yaml)
and is written with owner-only permissions on POSIX systems as
defense in depth.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml


class SecretStore:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def get_phrase_hash(self) -> str | None:
        if not self._path.exists():
            return None
        with self._path.open("r", encoding="utf-8") as f:
            data: dict[str, Any] = yaml.safe_load(f) or {}
        value = data.get("phrase_hash")
        return value if isinstance(value, str) and value else None

    def set_phrase_hash(self, phrase_hash: str) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._path.open("w", encoding="utf-8") as f:
            yaml.safe_dump({"phrase_hash": phrase_hash}, f)
        self._restrict_permissions()

    def is_configured(self) -> bool:
        return self.get_phrase_hash() is not None

    def ensure_configured(self, default_phrase: str | None = None) -> str:
        """Ensure a phrase hash is stored; if unconfigured, hash and persist default_phrase."""
        current = self.get_phrase_hash()
        if current is not None:
            return current

        fallback = default_phrase or os.getenv("VICTOR_DEFAULT_PIN", "1234")
        from app.auth.hashing import hash_phrase

        new_hash = hash_phrase(fallback)
        self.set_phrase_hash(new_hash)
        return new_hash

    def _restrict_permissions(self) -> None:
        # Owner read/write only. No-op on platforms where chmod semantics
        # differ (e.g. Windows); NTFS ACLs are a future hardening item.
        try:
            os.chmod(self._path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass