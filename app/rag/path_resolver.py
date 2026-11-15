"""
Victor Conversational Document Intelligence — Smart Document Path Resolver.

Resolves document file paths from natural language voice commands, user directory
aliases (Downloads, Desktop, Documents), relative paths, and fuzzy filename matches.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".xlsx", ".xls", ".pptx", ".csv", ".txt", ".md", ".json"
}


def _get_standard_search_directories(hint_folder: Optional[str] = None) -> List[Path]:
    """Returns prioritized candidate directories based on explicit hints or defaults."""
    home = Path.home()
    dirs: List[Path] = []

    # Map user folder hints
    if hint_folder:
        hint_lower = hint_folder.lower().strip()
        if "download" in hint_lower:
            dirs.append(home / "Downloads")
        elif "desktop" in hint_lower:
            dirs.append(home / "Desktop")
        elif "doc" in hint_lower:
            dirs.append(home / "Documents")

    # Add all standard locations in priority order
    standard = [
        home / "Downloads",
        home / "Desktop",
        home / "Documents",
        Path.cwd(),
        Path.cwd() / "data" / "documents" / "uploads",
        home,
    ]
    for d in standard:
        if d not in dirs and d.exists() and d.is_dir():
            dirs.append(d)

    return dirs


def _normalize_stem(s: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]", "", s).lower()


def _clean_spoken_filename(query: str) -> tuple[str, Optional[str]]:
    """
    Extracts filename and potential folder hint from spoken phrases.
    Example: 'analyse xyz.pdf file in downloads folder and give me summary'
    Returns: ('xyz.pdf', 'downloads')
    """
    cleaned = query.strip().strip("'\"")

    # If it's already a full file path
    if ("/" in cleaned or "\\" in cleaned) and not re.search(r"\b(in|on|from)\s+(the\s+)?(downloads|desktop|documents)\b", cleaned, re.I):
        return Path(cleaned).name, None

    # Detect folder hints in speech
    hint_folder = None
    if re.search(r"\b(in|from|inside)\s+(the\s+)?downloads?(\s+folder|\s+directory)?\b", cleaned, re.I):
        hint_folder = "downloads"
    elif re.search(r"\b(on|from|in)\s+(the\s+)?desktop\b", cleaned, re.I):
        hint_folder = "desktop"
    elif re.search(r"\b(in|from|inside)\s+(the\s+)?documents?(\s+folder|\s+directory)?\b", cleaned, re.I):
        hint_folder = "documents"

    # Remove command noise words
    noise_patterns = [
        r"^victor[, ]*",
        r"\b(please|can you|could you|analyse|analyze|read|summarize|summary of|explain|index|upload|open)\b",
        r"\b(and give me (a )?summary|and summarize( it)?|and explain( it)?)\b",
        r"\b(file|document)\s+(in|from|inside|on)\s+(the\s+)?[a-zA-Z0-9_-]+(\s+folder|\s+directory)?\b",
        r"\b(in|from|inside|on)\s+(the\s+)?[a-zA-Z0-9_-]+(\s+folder|\s+directory)?\b",
        r"\b(file|document)\b",
    ]
    for pat in noise_patterns:
        cleaned = re.sub(pat, " ", cleaned, flags=re.I)

    # Clean redundant whitespace
    target = re.sub(r"\s+", " ", cleaned).strip()

    # If an exact filename with extension is embedded (e.g. 'xyz.pdf')
    ext_match = re.search(r"([a-zA-Z0-9_\-\.\s]+\.(?:pdf|docx|doc|xlsx|xls|pptx|csv|txt|md|json))", query, re.I)
    if ext_match:
        extracted = ext_match.group(1).strip()
        # Ensure it doesn't have leading command preambles
        extracted = re.sub(r"^(analyse|analyze|read|summarize|index|upload)\s+", "", extracted, flags=re.I).strip()
        return extracted, hint_folder

    return target, hint_folder


def resolve_document_path(raw_path_or_query: str) -> Optional[Path]:
    """
    Resolves a document path from an exact path, filename, or spoken voice command.
    Returns resolved absolute Path if a file is found, otherwise None.
    """
    if not raw_path_or_query or not raw_path_or_query.strip():
        return None

    raw_str = raw_path_or_query.strip().strip("'\"")

    # 1. Direct path check
    direct = Path(raw_str).expanduser()
    if direct.is_absolute() and direct.exists() and direct.is_file():
        return direct.resolve()

    # Relative to cwd
    cwd_rel = (Path.cwd() / direct).resolve()
    if cwd_rel.exists() and cwd_rel.is_file():
        return cwd_rel

    # 2. Extract potential filename and folder hint from spoken query
    cleaned_name, hint_folder = _clean_spoken_filename(raw_str)
    search_dirs = _get_standard_search_directories(hint_folder)

    # Check direct combination with search dirs
    for s_dir in search_dirs:
        candidate = (s_dir / cleaned_name).resolve()
        if candidate.exists() and candidate.is_file():
            logger.info("Resolved document '%s' -> %s", raw_str, candidate)
            return candidate

        # Try without spaces if spoken with extra spaces
        no_spaces = cleaned_name.replace(" ", "")
        candidate_ns = (s_dir / no_spaces).resolve()
        if candidate_ns.exists() and candidate_ns.is_file():
            logger.info("Resolved document '%s' -> %s", raw_str, candidate_ns)
            return candidate_ns

        # Try replacing spaces with underscores or hyphens
        for sep in ["_", "-"]:
            candidate_sep = (s_dir / cleaned_name.replace(" ", sep)).resolve()
            if candidate_sep.exists() and candidate_sep.is_file():
                logger.info("Resolved document '%s' -> %s", raw_str, candidate_sep)
                return candidate_sep

    # 3. Fuzzy search in candidate directories (case-insensitive filename match)
    target_base = Path(cleaned_name).stem.lower().strip()
    target_norm = _normalize_stem(target_base)
    target_ext = Path(cleaned_name).suffix.lower().strip()

    for s_dir in search_dirs:
        try:
            if not s_dir.exists() or not s_dir.is_dir():
                continue
            for item in s_dir.iterdir():
                if not item.is_file():
                    continue
                item_ext = item.suffix.lower()
                if target_ext and item_ext != target_ext:
                    continue
                if not target_ext and item_ext not in SUPPORTED_EXTENSIONS:
                    continue

                item_stem = item.stem.lower()
                item_norm = _normalize_stem(item_stem)
                # Exact or normalized stem match
                if item_stem == target_base or item_norm == target_norm:
                    logger.info("Fuzzy matched document '%s' -> %s", raw_str, item.resolve())
                    return item.resolve()
                # Substring stem match if long enough
                if len(target_norm) >= 4 and (target_norm in item_norm or item_norm in target_norm):
                    logger.info("Substring matched document '%s' -> %s", raw_str, item.resolve())
                    return item.resolve()
        except (PermissionError, OSError) as e:
            logger.debug("Could not search directory %s: %s", s_dir, e)

    logger.warning("Could not resolve document path for: '%s' (cleaned: '%s', hint: '%s')", raw_str, cleaned_name, hint_folder)
    return None
