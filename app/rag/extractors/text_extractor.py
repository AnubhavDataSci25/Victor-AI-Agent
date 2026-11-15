"""
Victor Conversational Document Intelligence & RAG Agent — Text, Markdown, CSV & JSON Extractor.

Extracts text and structured representation from plain text, markdown, CSV, and JSON files.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd

from app.rag.extractors.base import BaseExtractor
from app.rag.models import Document, DocumentChunk, DocumentType, ExtractionResult

logger = logging.getLogger(__name__)


class TextExtractor(BaseExtractor):
    """Extractor for TXT, Markdown, CSV, and JSON formats."""

    def extract(self, document: Document) -> ExtractionResult:
        file_path = Path(document.file_path)
        if not file_path.exists():
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"File not found: {document.file_path}",
            )

        try:
            doc_type = document.doc_type

            if doc_type == DocumentType.CSV:
                return self._extract_csv(document, file_path)
            elif doc_type == DocumentType.JSON:
                return self._extract_json(document, file_path)
            elif doc_type == DocumentType.MD:
                return self._extract_markdown(document, file_path)
            else:
                return self._extract_plain_text(document, file_path)

        except Exception as e:
            logger.error("Failed to extract %s: %s", document.file_path, e, exc_info=True)
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"Text extraction error: {str(e)}",
            )

    def _extract_plain_text(self, document: Document, file_path: Path) -> ExtractionResult:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        meta = {"title": file_path.name, "format": "txt"}
        chunks = self.chunk_text(
            text=content,
            document_id=document.document_id,
            section_title="Full Document",
        )
        return ExtractionResult(
            document_id=document.document_id,
            chunks=chunks,
            metadata=meta,
            raw_text_length=len(content),
            total_pages=1,
        )

    def _extract_markdown(self, document: Document, file_path: Path) -> ExtractionResult:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        meta = {"title": file_path.stem, "format": "markdown"}
        chunks: List[DocumentChunk] = []
        chunk_idx = 0
        current_section = "Introduction"
        section_lines: List[str] = []
        total_len = 0

        for line in lines:
            stripped = line.strip()
            total_len += len(line)

            # Markdown headings: #, ##, ###
            if stripped.startswith("#"):
                if section_lines:
                    text_block = "".join(section_lines).strip()
                    if text_block:
                        sec_chunks = self.chunk_text(
                            text=text_block,
                            document_id=document.document_id,
                            start_index=chunk_idx,
                            section_title=current_section,
                            extra_metadata={"section": current_section},
                        )
                        chunks.extend(sec_chunks)
                        chunk_idx += len(sec_chunks)
                        section_lines = []

                # New heading
                current_section = stripped.lstrip("#").strip()
                section_lines.append(line)
            else:
                section_lines.append(line)

        if section_lines:
            text_block = "".join(section_lines).strip()
            if text_block:
                sec_chunks = self.chunk_text(
                    text=text_block,
                    document_id=document.document_id,
                    start_index=chunk_idx,
                    section_title=current_section,
                    extra_metadata={"section": current_section},
                )
                chunks.extend(sec_chunks)

        return ExtractionResult(
            document_id=document.document_id,
            chunks=chunks,
            metadata=meta,
            raw_text_length=total_len,
            total_pages=1,
        )

    def _extract_csv(self, document: Document, file_path: Path) -> ExtractionResult:
        df = pd.read_csv(file_path, nrows=5000)  # Safe preview limit
        row_count, col_count = df.shape
        columns = list(df.columns)

        # Build schema and statistical summary
        meta = {
            "title": file_path.name,
            "format": "csv",
            "row_count": row_count,
            "column_count": col_count,
            "columns": columns,
        }

        summary_lines = [
            f"CSV Dataset: {file_path.name}",
            f"Dimensions: {row_count} rows, {col_count} columns",
            f"Columns: {', '.join(str(c) for c in columns)}",
            "",
            "Column Types:",
        ]
        for col, dtype in df.dtypes.items():
            summary_lines.append(f"- {col}: {dtype}")

        # Basic numerical stats if any
        num_desc = df.describe().to_string()
        summary_lines.append("\nStatistical Summary (Numerical Columns):")
        summary_lines.append(num_desc)

        summary_text = "\n".join(summary_lines)

        # Build sample table rows (first 50 rows)
        sample_rows_md = df.head(50).to_markdown(index=False)
        full_text = f"{summary_text}\n\nSample Data (First 50 Rows):\n{sample_rows_md}"

        chunks = self.chunk_text(
            text=full_text,
            document_id=document.document_id,
            section_title="CSV Schema & Summary",
            extra_metadata=meta,
        )

        return ExtractionResult(
            document_id=document.document_id,
            chunks=chunks,
            metadata=meta,
            raw_text_length=len(full_text),
            total_pages=1,
        )

    def _extract_json(self, document: Document, file_path: Path) -> ExtractionResult:
        with open(file_path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        meta = {"title": file_path.name, "format": "json"}
        formatted_json = json.dumps(data, indent=2)

        # Overview of keys if dict or item count if list
        if isinstance(data, dict):
            overview = f"JSON Object with keys: {list(data.keys())}\n\n"
        elif isinstance(data, list):
            overview = f"JSON Array with {len(data)} items.\n\n"
        else:
            overview = "JSON Value:\n\n"

        full_content = overview + formatted_json

        chunks = self.chunk_text(
            text=full_content,
            document_id=document.document_id,
            section_title="JSON Content",
            extra_metadata=meta,
        )

        return ExtractionResult(
            document_id=document.document_id,
            chunks=chunks,
            metadata=meta,
            raw_text_length=len(full_content),
            total_pages=1,
        )
