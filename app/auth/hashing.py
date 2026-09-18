"""
Argon2id hashing for Victor's security phrase (spec section 9).

This is the only module allowed to touch a raw phrase string. It
never logs, prints, or returns the phrase itself - only a hash (on
hash_phrase) or a boolean (on verify_phrase). Callers must not log
the phrase either; see app/logging.py's redaction filter for the
defense-in-depth backstop, but that filter only catches named fields,
not text embedded in an f-string, so this module's callers must never
interpolate the phrase into a log message (rule 9, and the Phase 3
note in project memory: redaction covers field names, not free text).

Argon2id (not Argon2i or Argon2d) is used explicitly: it's the
mode recommended by the Argon2 authors and OWASP for password
hashing, combining resistance to both side-channel and GPU
cracking attacks.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHash, VerifyMismatchError
from argon2.low_level import Type

# Parameters chosen for a responsive desktop app while remaining well
# above OWASP's minimum recommendations for Argon2id. Adjust only with
# an understanding of the time/memory tradeoff - lowering these
# weakens brute-force resistance.
_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,  # 64 MiB
    parallelism=2,
    hash_len=32,
    type=Type.ID,  # Argon2id
)


def hash_phrase(phrase: str) -> str:
    """Hash a security phrase. The returned string embeds the salt and
    parameters and is safe to store; the phrase itself is not recoverable
    from it."""
    if not phrase or not phrase.strip():
        raise ValueError("Security phrase must not be empty")
    return _HASHER.hash(phrase)


def verify_phrase(phrase: str, stored_hash: str) -> bool:
    """
    Verify a candidate phrase against a stored Argon2id hash.
    Never raises - any failure (mismatch, corrupt hash, wrong
    algorithm) is treated as "does not match".
    """
    if not phrase or not stored_hash:
        return False
    try:
        return _HASHER.verify(stored_hash, phrase)
    except VerifyMismatchError:
        return False
    except InvalidHash:
        return False
    except Exception:  # noqa: BLE001 - never let a hashing edge case unlock Victor
        return False