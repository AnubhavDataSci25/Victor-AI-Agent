"""
Memory Sanitizer — Prevents storing sensitive credentials, API keys, passwords, and PINs.
"""

from __future__ import annotations

import re
from typing import Tuple

# Patterns that match secrets, credentials, or sensitive authentication details
SENSITIVE_PATTERNS = [
    # API Keys (Gemini, OpenAI, GitHub, AWS, Generic)
    (re.compile(r"AIzaSy[A-Za-z0-9_-]{33}", re.IGNORECASE), "Google/Gemini API Key"),
    (re.compile(r"sk-[A-Za-z0-9]{20,}", re.IGNORECASE), "OpenAI/Secret Key"),
    (re.compile(r"ghp_[A-Za-z0-9]{36}", re.IGNORECASE), "GitHub Personal Access Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE), "AWS Access Key"),
    (re.compile(r"(?:api[_-]?key|secret[_-]?key|auth[_-]?token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-\.]{16,}['\"]?", re.IGNORECASE), "API/Secret Key assignment"),
    
    # Passwords
    (re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?\S+['\"]?", re.IGNORECASE), "Password assignment"),
    (re.compile(r"(?:my|the)\s+password\s+is\s+['\"]?\S+['\"]?", re.IGNORECASE), "Password disclosure"),
    
    # PIN codes
    (re.compile(r"(?:pin|passcode)\s*(?:is|code|number)?\s*[:=]?\s*\b\d{4,8}\b", re.IGNORECASE), "PIN code"),
    
    # Bearer tokens & JWTs
    (re.compile(r"bearer\s+[A-Za-z0-9\-\._~\+\/]+=*", re.IGNORECASE), "Bearer token"),
    (re.compile(r"ey[A-Za-z0-9_-]{10,}\.ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", re.IGNORECASE), "JWT token"),
    
    # Private keys
    (re.compile(r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----", re.IGNORECASE), "Cryptographic private key"),
    
    # Credit card numbers
    (re.compile(r"\b(?:\d{4}[- ]?){3}\d{4}\b"), "Credit card number"),
]


class MemorySanitizer:
    """Security filter ensuring credentials and sensitive tokens are never stored in long-term memory."""

    @staticmethod
    def is_sensitive(text: str) -> Tuple[bool, str]:
        """
        Checks if text contains sensitive data.
        Returns (is_sensitive: bool, description: str).
        """
        if not text:
            return False, ""

        for pattern, desc in SENSITIVE_PATTERNS:
            if pattern.search(text):
                return True, f"Content contains sensitive data ({desc}) and cannot be stored in long-term memory."

        return False, ""

    @staticmethod
    def sanitize_text(text: str) -> str:
        """Normalizes text by removing non-printable control characters and excessive whitespace."""
        if not text:
            return ""
        # Keep printable chars and standard whitespace
        cleaned = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]", "", text)
        return cleaned.strip()
