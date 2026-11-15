"""
Unit and integration tests for Victor Voice-Based Document Upload, Smart Path Resolver,
and Real-Time Dashboard Synchronization.
"""

import asyncio
import os
import tempfile
from pathlib import Path
import pytest

from app.rag.events import (
    broadcast_document_summary,
    broadcast_rag_event,
    register_ui_listener,
    unregister_ui_listener,
)
from app.rag.path_resolver import _clean_spoken_filename, resolve_document_path
from app.tools.tool_setup import build_tool_registry


def test_clean_spoken_filename():
    cases = [
        ("analyse xyz.pdf file in downloads folder and give me summary", "xyz.pdf", "downloads"),
        ("Victor, analyze my stroke_prediction.pdf on desktop", "stroke_prediction.pdf", "desktop"),
        ("read sales_report.xlsx in documents folder", "sales_report.xlsx", "documents"),
        ("give me summary of lecture_notes.docx", "lecture_notes.docx", None),
        ("C:/Users/test/Downloads/invoice.pdf", "invoice.pdf", None),
    ]

    for spoken_input, expected_file, expected_hint in cases:
        file_extracted, hint = _clean_spoken_filename(spoken_input)
        assert expected_file.lower() in file_extracted.lower(), f"Failed on: {spoken_input}"
        if expected_hint:
            assert hint == expected_hint, f"Hint failed on: {spoken_input} (got {hint})"


def test_resolve_document_path():
    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        test_file = temp_dir / "research_paper.pdf"
        test_file.write_text("Dummy content for testing path resolution", encoding="utf-8")

        # 1. Direct path
        resolved = resolve_document_path(str(test_file))
        assert resolved is not None
        assert resolved.resolve() == test_file.resolve()

        # 2. Relative or nested query simulation using monkeypatch/temp search
        from app.rag import path_resolver
        orig_search_dirs = path_resolver._get_standard_search_directories
        try:
            path_resolver._get_standard_search_directories = lambda hint=None: [temp_dir]

            # Spoken voice command format:
            spoken_cmd = "Victor, analyse research_paper.pdf file in downloads folder and give me summary"
            resolved_spoken = resolve_document_path(spoken_cmd)
            assert resolved_spoken is not None
            assert resolved_spoken.resolve() == test_file.resolve()

            # Case-insensitive stem matching
            spoken_fuzzy = "please summarize RESEARCH PAPER"
            resolved_fuzzy = resolve_document_path(spoken_fuzzy)
            assert resolved_fuzzy is not None
            assert resolved_fuzzy.resolve() == test_file.resolve()
        finally:
            path_resolver._get_standard_search_directories = orig_search_dirs


@pytest.mark.asyncio
async def test_rag_events_broadcast():
    received_events = []

    async def mock_ws_sender(data: dict):
        received_events.append(data)

    register_ui_listener(mock_ws_sender)
    try:
        await broadcast_document_summary(
            document_id="doc_test_123",
            file_name="quarterly_report.pdf",
            summary="Revenue increased by 24% year-over-year.",
            summary_type="comprehensive",
            auto_navigate=True,
        )

        assert len(received_events) >= 2
        update_evt = next((e for e in received_events if e.get("type") == "document_update"), None)
        nav_evt = next((e for e in received_events if e.get("type") == "dashboard_navigate"), None)

        assert update_evt is not None
        assert update_evt["action"] == "voice_summary"
        assert update_evt["data"]["file_name"] == "quarterly_report.pdf"

        assert nav_evt is not None
        assert nav_evt["section"] == "documents"
        assert nav_evt["tab"] == "study"
        assert "Revenue increased" in nav_evt["summary"]
    finally:
        unregister_ui_listener(mock_ws_sender)


@pytest.mark.asyncio
async def test_voice_upload_and_summarize_tool_execution():
    with tempfile.TemporaryDirectory() as td:
        temp_dir = Path(td)
        doc_path = temp_dir / "machine_learning_notes.md"
        doc_path.write_text(
            "# Machine Learning Fundamentals\n"
            "This document covers supervised learning, gradient descent, and cross-validation.\n"
            "## Key Formulas\n"
            "MSE = 1/n sum((y - y_hat)^2)",
            encoding="utf-8",
        )

        registry = build_tool_registry()

        # 1. Verify tool registration
        tool = registry.get("document_voice_upload_and_summarize")
        assert tool is not None, "document_voice_upload_and_summarize tool not registered"

        # 2. Execute voice upload and summarize
        res = await tool.execute({
            "document_query_or_path": str(doc_path),
            "summary_type": "comprehensive",
        })

        assert "Sir" in res
        assert "machine_learning_notes.md" in res
        assert "summary" in res.lower() or "Machine Learning" in res
        assert "Document Intelligence dashboard" in res
