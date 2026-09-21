"""
Cryptographic security module for Victor Phone Integration V1.
Implements AES-256-GCM symmetric payload encryption, HMAC-SHA256 message signing,
cryptographic pairing token generation, sliding-window nonce deduplication, and
timestamp-based replay defense.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Optional
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.phone.models import PhoneMessage


class PhoneCryptoError(Exception):
    """Raised when encryption, decryption, or verification fails."""


class PhoneCrypto:
    TIMESTAMP_TOLERANCE_SECONDS = 30.0
    NONCE_CACHE_TTL_SECONDS = 120.0

    def __init__(self) -> None:
        # Nonce cache: maps nonce string to timestamp when recorded
        self._seen_nonces: dict[str, float] = {}

    @staticmethod
    def generate_shared_secret() -> str:
        """Generates a secure 32-byte (256-bit) shared secret hex string."""
        return secrets.token_hex(32)

    @staticmethod
    def generate_pairing_token() -> str:
        """Generates a cryptographically random pairing token."""
        return secrets.token_hex(16)

    @staticmethod
    def generate_pairing_pin() -> str:
        """Generates a 6-digit numeric pairing PIN."""
        return f"{secrets.randbelow(900000) + 100000}"

    def clean_nonce_cache(self, current_time: Optional[float] = None) -> None:
        """Evicts expired nonces older than NONCE_CACHE_TTL_SECONDS."""
        now = current_time if current_time is not None else time.time()
        cutoff = now - self.NONCE_CACHE_TTL_SECONDS
        expired = [n for n, ts in self._seen_nonces.items() if ts < cutoff]
        for n in expired:
            self._seen_nonces.pop(n, None)

    def verify_replay_protection(self, nonce: str, timestamp: float, current_time: Optional[float] = None) -> bool:
        """
        Validates that:
        1. Timestamp is within [-30s, +30s] of current time.
        2. Nonce has not been seen before in the active window.
        """
        now = current_time if current_time is not None else time.time()
        self.clean_nonce_cache(now)

        # Check timestamp drift
        drift = abs(now - timestamp)
        if drift > self.TIMESTAMP_TOLERANCE_SECONDS:
            return False

        # Check nonce uniqueness
        if nonce in self._seen_nonces:
            return False

        # Record nonce
        self._seen_nonces[nonce] = now
        return True

    @staticmethod
    def canonical_bytes(msg_id: str, timestamp: float, nonce: str, msg_type: str, action: str, payload: dict[str, Any]) -> bytes:
        """Produces canonical deterministic byte sequence for signing."""
        serialized_payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        raw = f"{msg_id}:{timestamp:.3f}:{nonce}:{msg_type}:{action}:{serialized_payload}"
        return raw.encode("utf-8")

    def sign_message(self, message: PhoneMessage, shared_secret_hex: str) -> str:
        """Computes HMAC-SHA256 signature for a PhoneMessage."""
        secret_bytes = bytes.fromhex(shared_secret_hex)
        data = self.canonical_bytes(
            message.id,
            message.timestamp,
            message.nonce,
            message.type.value,
            message.action,
            message.payload,
        )
        return hmac.new(secret_bytes, data, hashlib.sha256).hexdigest()

    def verify_signature(self, message: PhoneMessage, shared_secret_hex: str) -> bool:
        """Verifies HMAC-SHA256 signature of a PhoneMessage."""
        if not message.signature:
            return False
        expected_sig = self.sign_message(message, shared_secret_hex)
        return hmac.compare_digest(message.signature, expected_sig)

    @staticmethod
    def encrypt_payload(payload: dict[str, Any], shared_secret_hex: str) -> str:
        """
        Encrypts a payload dictionary using AES-256-GCM.
        Returns a base64 encoded string containing: 12-byte IV + ciphertext + 16-byte tag.
        """
        try:
            key = bytes.fromhex(shared_secret_hex)
            aesgcm = AESGCM(key)
            iv = secrets.token_bytes(12)
            data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ciphertext = aesgcm.encrypt(iv, data, None)
            combined = iv + ciphertext
            return base64.b64encode(combined).decode("utf-8")
        except Exception as e:
            raise PhoneCryptoError(f"Encryption failed: {e}") from e

    @staticmethod
    def decrypt_payload(encrypted_b64: str, shared_secret_hex: str) -> dict[str, Any]:
        """
        Decrypts an AES-256-GCM base64 encoded payload.
        """
        try:
            key = bytes.fromhex(shared_secret_hex)
            aesgcm = AESGCM(key)
            combined = base64.b64decode(encrypted_b64)
            if len(combined) < 28:  # 12-byte IV + 16-byte tag minimum
                raise PhoneCryptoError("Encrypted payload too short")
            iv = combined[:12]
            ciphertext = combined[12:]
            decrypted = aesgcm.decrypt(iv, ciphertext, None)
            return json.loads(decrypted.decode("utf-8"))
        except Exception as e:
            raise PhoneCryptoError(f"Decryption failed: {e}") from e
