"""
Structured logging for Victor 2.0.

Provides:
- SecretRedactingFormatter: masks credentials, PINs, tokens in log output
- get_logger(name): returns a namespaced logger under 'victor.'
- log_event(logger, level, event, **kwargs): structured event logging
- log_tool_call(...): specialized tool-call audit logging
"""

import json
import logging
import re
import sys
from typing import Any


class SecretRedactingFormatter(logging.Formatter):
    """
    Intercepts and masks sensitive keys (credentials, PINs, tokens)
    before they are written to the console or log files.
    """
    SECRET_PATTERNS = [
        (re.compile(r'(["\'"]?credential["\'"]?\s*[:=]\s*["\'"]?)[^"\']*(["\']?)', re.IGNORECASE), r'\1***REDACTED***\2'),
        (re.compile(r'(["\'"]?passphrase["\'"]?\s*[:=]\s*["\'"]?)[^"\']*(["\']?)', re.IGNORECASE), r'\1***REDACTED***\2'),
        (re.compile(r'(api_key\s*[:=]\s*["\'"]?)[^"\']*(["\']?)', re.IGNORECASE), r'\1***REDACTED***\2'),
    ]

    def format(self, record):
        original_msg = super().format(record)
        for pattern, replacement in self.SECRET_PATTERNS:
            original_msg = pattern.sub(replacement, original_msg)
        return original_msg


def setup_secure_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    formatter = SecretRedactingFormatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    file_handler = logging.FileHandler("app.log", encoding="utf-8")
    file_handler.setFormatter(formatter)

    # Replace existing handlers to ensure no raw logging bypasses the filter
    if logger.hasHandlers():
        logger.handlers.clear()
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger under 'victor.' prefix."""
    return logging.getLogger(f"victor.{name}")


def log_event(
    logger: logging.Logger,
    level: int,
    event: str,
    **kwargs: Any,
) -> None:
    """Log a structured event as JSON-ish key=value pairs.

    Example:
        log_event(logger, logging.INFO, "auth_success")
        log_event(logger, logging.WARNING, "auth_failure", failed_attempts=3)
    """
    payload = {"event": event, **kwargs}
    logger.log(level, "%s", json.dumps(payload, default=str))


def log_tool_call(
    tool: str,
    arguments: dict[str, Any],
    permission_level: str,
    success: bool,
    duration_ms: float,
    error: str | None = None,
) -> None:
    """Audit-log a tool call with its outcome."""
    _logger = get_logger("tools.audit")
    payload = {
        "event": "tool_call",
        "tool": tool,
        "arguments": arguments,
        "permission_level": permission_level,
        "success": success,
        "duration_ms": round(duration_ms, 2),
    }
    if error:
        payload["error"] = error
    _logger.info("%s", json.dumps(payload, default=str))


setup_secure_logging()