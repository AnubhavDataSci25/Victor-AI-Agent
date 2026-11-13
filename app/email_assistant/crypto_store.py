"""
Victor Autonomous Email Assistant — Encrypted Credential Storage.

Uses Windows DPAPI (CryptProtectData / CryptUnprotectData) to bind OAuth tokens
to the current Windows user account, with an authenticated Fernet fallback on
non-Windows platforms. Never writes plaintext tokens to disk or logs.
"""

from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
from typing import Any, Optional

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_DEFAULT_TOKEN_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "gmail_token.enc"


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _dpapi_encrypt(plaintext: bytes) -> Optional[bytes]:
    if sys.platform != "win32":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(plaintext, len(plaintext))
        blob_in = _DATA_BLOB(len(plaintext), buf)
        blob_out = _DATA_BLOB()
        if not crypt32.CryptProtectData(
            ctypes.byref(blob_in),
            "VictorGmailOAuthToken",
            None,
            None,
            None,
            0x01,  # CRYPTPROTECT_UI_FORBIDDEN
            ctypes.byref(blob_out),
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _dpapi_decrypt(ciphertext: bytes) -> Optional[bytes]:
    if sys.platform != "win32":
        return None
    try:
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        buf = ctypes.create_string_buffer(ciphertext, len(ciphertext))
        blob_in = _DATA_BLOB(len(ciphertext), buf)
        blob_out = _DATA_BLOB()
        if not crypt32.CryptUnprotectData(
            ctypes.byref(blob_in),
            None,
            None,
            None,
            None,
            0x01,
            ctypes.byref(blob_out),
        ):
            return None
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            kernel32.LocalFree(blob_out.pbData)
    except Exception:
        return None


def _fallback_fernet() -> Fernet:
    seed = f"{os.getenv('COMPUTERNAME', 'victor')}:{os.getenv('USERNAME', 'user')}:victor-email-v1".encode("utf-8")
    key = base64.urlsafe_b64encode(hashlib.sha256(seed).digest())
    return Fernet(key)


class EncryptedTokenStore:
    """Securely persists and loads OAuth token payloads."""

    def __init__(self, token_path: Path | None = None) -> None:
        self.token_path = token_path or _DEFAULT_TOKEN_PATH

    def save(self, token_data: dict[str, Any]) -> None:
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(token_data, ensure_ascii=True).encode("utf-8")
        dpapi_bytes = _dpapi_encrypt(raw)
        if dpapi_bytes is not None:
            envelope = b"DPAPI1:" + base64.b64encode(dpapi_bytes)
        else:
            envelope = b"FERNET1:" + _fallback_fernet().encrypt(raw)
        self.token_path.write_bytes(envelope)

    def load(self) -> Optional[dict[str, Any]]:
        if not self.token_path.exists():
            return None
        try:
            raw = self.token_path.read_bytes()
            if raw.startswith(b"DPAPI1:"):
                decrypted = _dpapi_decrypt(base64.b64decode(raw[7:]))
            elif raw.startswith(b"FERNET1:"):
                decrypted = _fallback_fernet().decrypt(raw[8:])
            else:
                return None
            if not decrypted:
                return None
            data = json.loads(decrypted.decode("utf-8"))
            return data if isinstance(data, dict) else None
        except Exception as e:
            logger.warning(f"[EmailCryptoStore] Failed to decrypt stored token: {type(e).__name__}")
            return None

    def clear(self) -> bool:
        if self.token_path.exists():
            self.token_path.unlink()
            return True
        return False
