"""
Victor Autonomous Email Assistant — Attachment Validation & Security.

Enforces strict allowlisted extensions, MIME detection, 25 MB Gmail size cap,
and blocks sensitive system/credential paths from ever being attached.
"""

from __future__ import annotations

import mimetypes
from pathlib import Path

from app.email_assistant.models import EmailAttachment

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024  # 25 MB Gmail limit

ALLOWED_EXTENSIONS: dict[str, str] = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".txt": "text/plain",
    ".csv": "text/csv",
}

_BLOCKED_FILENAMES = {
    ".env",
    "secrets.yaml",
    "secrets.yml",
    "gmail_token.enc",
    "paired_phone.json",
    "id_rsa",
    "id_ed25519",
}

_BLOCKED_PATH_PARTS = {
    "windows",
    "system32",
    "program files",
    "program files (x86)",
    ".ssh",
    ".gnupg",
}


def validate_attachment(file_path: str) -> EmailAttachment:
    """
    Validate a user-selected attachment path for existence, permissions,
    non-sensitive location, allowed extension, and size <= 25 MB.
    """
    raw = (file_path or "").strip().strip('"').strip("'")
    if not raw:
        raise ValueError("Attachment path cannot be empty.")

    resolved = Path(raw).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        raise FileNotFoundError(f"Attachment file not found: '{raw}'")

    name_lower = resolved.name.lower()
    if name_lower in _BLOCKED_FILENAMES or name_lower.endswith(".enc") or name_lower.endswith(".key"):
        raise PermissionError(f"Security Policy: Attaching sensitive file '{resolved.name}' is blocked.")

    parts_lower = {p.lower() for p in resolved.parts}
    if parts_lower & _BLOCKED_PATH_PARTS:
        raise PermissionError(f"Security Policy: Attaching files from system/private directory is blocked.")

    ext = resolved.suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS.keys()))
        raise ValueError(f"Unsupported attachment type '{ext}'. Supported types: {allowed}")

    size_bytes = resolved.stat().st_size
    if size_bytes == 0:
        raise ValueError(f"Attachment '{resolved.name}' is empty (0 bytes).")
    if size_bytes > MAX_ATTACHMENT_BYTES:
        mb = size_bytes / (1024 * 1024)
        raise ValueError(f"Attachment '{resolved.name}' is {mb:.1f} MB, exceeding Gmail's 25 MB limit.")

    # Confirm file is readable
    with resolved.open("rb") as f:
        f.read(1)

    guessed_mime, _ = mimetypes.guess_type(str(resolved))
    mime_type = ALLOWED_EXTENSIONS.get(ext) or guessed_mime or "application/octet-stream"

    return EmailAttachment(
        path=str(resolved),
        filename=resolved.name,
        mime_type=mime_type,
        size_bytes=size_bytes,
    )
