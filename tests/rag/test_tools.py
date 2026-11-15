"""
Unit tests for Victor Document Tools and ToolGateway Integration.
"""

import os
os.environ["VICTOR_DISABLE_FAISS"] = "1"
os.environ["VICTOR_FAST_EMBEDDING"] = "1"
from pathlib import Path
import tempfile
import pytest

from app.tools.tool_setup import build_tool_registry


def test_rag_tools_registered():
    registry = build_tool_registry()

    expected_tools = [
        "document_read_and_explain",
        "document_search_and_query",
        "document_compare",
        "document_summarize",
        "document_generate_notes",
        "document_excel_query",
        "document_list_library",
        "document_voice_upload_and_summarize",
    ]

    for tool_name in expected_tools:
        tool = registry.get(tool_name)
        assert tool is not None, f"Tool '{tool_name}' was not found in registry"
        assert hasattr(tool, "execute"), f"Tool '{tool_name}' missing execute method"
        schema = tool.get_schema()
        assert schema["name"] == tool_name
        assert "description" in schema


@pytest.mark.asyncio
async def test_document_tools_execution():
    with tempfile.TemporaryDirectory() as td:
        sample_path = Path(td) / "project_report.md"
        sample_path.write_text(
            "# Autonomous Agent Architecture\n"
            "This project presents Victor, an agent with continuous listening and document intelligence.\n"
            "## Architecture\n"
            "We employ SQLite WAL storage, FAISS vector indexing, and multi-provider model routing.",
            encoding="utf-8",
        )

        registry = build_tool_registry()

        # 1. document_read_and_explain
        read_tool = registry.get("document_read_and_explain")
        res = await read_tool.execute({
            "file_path": str(sample_path),
            "question": "What architecture is used?",
        })
        assert "Victor" in res or "SQLite" in res or "Architecture" in res or "Sources" in res

        # 2. document_list_library
        list_tool = registry.get("document_list_library")
        list_res = await list_tool.execute({})
        assert "project_report.md" in list_res
