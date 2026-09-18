"""
PIN normalization for voice-based authentication.

When auth_mode is 'pin', the user speaks digits which may arrive as
words ("one two three four") or mixed ("1 two 3 four"). This module
normalizes them into a digit-only string before hashing/verification.
"""

from __future__ import annotations

_WORD_TO_DIGIT = {
    "zero": "0", "oh": "0",
    "one": "1", "won": "1",
    "two": "2", "to": "2", "too": "2",
    "three": "3",
    "four": "4", "for": "4",
    "five": "5",
    "six": "6",
    "seven": "7",
    "eight": "8", "ate": "8",
    "nine": "9",
}


def normalize_pin(raw: str) -> str:
    """Convert a spoken or typed PIN into a digit-only string.

    Examples:
        "one two three four" -> "1234"
        "1 2 3 4"            -> "1234"
        "12 34"              -> "1234"
        "one234"             -> "1234"
    """
    if not raw or not raw.strip():
        return ""

    tokens = raw.lower().split()
    digits: list[str] = []

    for token in tokens:
        if token in _WORD_TO_DIGIT:
            digits.append(_WORD_TO_DIGIT[token])
        else:
            # Extract any digits from the token directly
            for ch in token:
                if ch.isdigit():
                    digits.append(ch)

    return "".join(digits)
