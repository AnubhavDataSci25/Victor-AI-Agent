"""
Victor Conversational Document Intelligence & RAG Agent — Word (DOCX) Extractor.

Extracts text, headings, tables, and document structure from Word documents (.docx)
using python-docx.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import docx

from app.rag.extractors.base import BaseExtractor
from app.rag.models import Document, DocumentChunk, ExtractionResult

logger = logging.getLogger(__name__)


class DocxExtractor(BaseExtractor):
    """Structure-aware Word (.docx) document extractor."""

    def extract(self, document: Document) -> ExtractionResult:
        file_path = Path(document.file_path)
        if not file_path.exists():
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"File not found: {document.file_path}",
            )

        try:
            doc = docx.Document(str(file_path))
            meta: Dict[str, Any] = {
                "title": file_path.stem,
            }

            try:
                core_props = doc.core_properties
                if core_props.title:
                    meta["title"] = core_props.title
                if core_props.author:
                    meta["author"] = core_props.author
                if core_props.subject:
                    meta["subject"] = core_props.subject
            except Exception as pe:
                logger.debug("Could not read docx core properties: %s", pe)

            chunks: List[DocumentChunk] = []
            chunk_idx = 0
            current_section = "Main Content"
            total_text_length = 0

            # Group content by sections / headings
            section_blocks: List[str] = []

            for paragraph in doc.paragraphs:
                text = paragraph.text.strip()
                if not text:
                    continue

                style_name = paragraph.style.name if paragraph.style else ""

                # Check if this paragraph is a heading
                if style_name.lower().startswith("heading") or style_name.lower().startswith("title"):
                    # If we had accumulated content for previous section, chunk it
                    if section_blocks:
                        section_text = "\n\n".join(section_blocks)
                        sec_chunks = self.chunk_text(
                            text=section_text,
                            document_id=document.document_id,
                            start_index=chunk_idx,
                            section_title=current_section,
                            extra_metadata={"section": current_section},
                        )
                        chunks.extend(sec_chunks)
                        chunk_idx += len(sec_chunks)
                        section_blocks = []

                    current_section = text
                else:
                    section_blocks.append(text)
                    total_text_length += len(text)

            # Also extract tables
            for table_idx, table in enumerate(doc.tables):
                table_rows = []
                for row in table.rows:
                    row_cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                    if any(row_cells):
                        table_rows.append(" | ".join(row_cells))

                if table_rows:
                    table_md = "\n".join(table_rows)
                    section_blocks.append(f"\n[Table {table_idx + 1} in '{current_section}']:\n{table_md}\n")
                    total_text_length += len(table_md)

            # Flush any remaining content
            if section_blocks:
                section_text = "\n\n".join(section_blocks)
                sec_chunks = self.chunk_text(
                    text=section_text,
                    document_id=document.document_id,
                    start_index=chunk_idx,
                    section_title=current_section,
                    extra_metadata={"section": current_section},
                )
                chunks.extend(sec_chunks)
                chunk_idx += len(sec_chunks)

            return ExtractionResult(
                document_id=document.document_id,
                chunks=chunks,
                metadata=meta,
                raw_text_length=total_text_length,
                total_pages=None,  # docx does not have fixed pages without rendering
            )

        except Exception as e:
            logger.error("Failed to extract DOCX %s: %s", document.file_path, e, exc_info=True)
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"DOCX extraction error: {str(e)}",
            )
