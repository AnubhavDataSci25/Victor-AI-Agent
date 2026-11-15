"""
Victor Conversational Document Intelligence & RAG Agent — PDF Extractor.

Extracts text, headings, structure, tables, and page-level metadata from PDF documents
using PyMuPDF (pymupdf).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

import pymupdf

from app.rag.extractors.base import BaseExtractor
from app.rag.models import Document, DocumentChunk, ExtractionResult

logger = logging.getLogger(__name__)


class PDFExtractor(BaseExtractor):
    """Structure-aware PDF extractor using PyMuPDF."""

    def extract(self, document: Document) -> ExtractionResult:
        file_path = Path(document.file_path)
        if not file_path.exists():
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"File not found: {document.file_path}",
            )

        try:
            doc = pymupdf.open(str(file_path))
            total_pages = len(doc)
            meta: Dict[str, Any] = {
                "title": doc.metadata.get("title") or file_path.stem,
                "author": doc.metadata.get("author") or "",
                "subject": doc.metadata.get("subject") or "",
                "keywords": doc.metadata.get("keywords") or "",
                "page_count": total_pages,
            }

            chunks: List[DocumentChunk] = []
            chunk_idx = 0
            current_section = "Introduction"
            total_text_length = 0

            for page_num in range(total_pages):
                page = doc[page_num]
                page_display_num = page_num + 1

                # Extract text with layout blocks
                # flags: pymupdf.TEXT_DEHYPHENATE | pymupdf.TEXT_PRESERVE_WHITESPACE
                blocks = page.get_text("blocks")
                page_text_segments: List[str] = []

                for block in blocks:
                    # block: (x0, y0, x1, y1, text, block_no, block_type)
                    # block_type 0 = text, 1 = image
                    if len(block) >= 7 and block[6] == 0:
                        text = block[4].strip()
                        if not text:
                            continue

                        # Detect probable headings (short text, uppercase or title casing)
                        lines = [line.strip() for line in text.split("\n") if line.strip()]
                        if len(lines) == 1 and len(lines[0]) < 80:
                            line = lines[0]
                            # Heuristic: all caps or ends without period and short
                            if (line.isupper() or line.istitle()) and not line.endswith("."):
                                current_section = line

                        page_text_segments.append(text)

                # Also inspect for tables if available
                try:
                    tables = page.find_tables()
                    for t in tables:
                        table_df = t.extract()
                        if table_df:
                            # Convert table to readable markdown representation
                            table_md = "\n".join([" | ".join(str(cell or "") for cell in row) for row in table_df])
                            page_text_segments.append(f"\n[Table on Page {page_display_num}]:\n{table_md}\n")
                except Exception as e:
                    logger.debug("Table extraction skipped for page %d: %s", page_display_num, e)

                full_page_text = "\n\n".join(page_text_segments)
                total_text_length += len(full_page_text)

                if full_page_text.strip():
                    page_chunks = self.chunk_text(
                        text=full_page_text,
                        document_id=document.document_id,
                        start_index=chunk_idx,
                        page_number=page_display_num,
                        section_title=current_section,
                        extra_metadata={"page": page_display_num},
                    )
                    chunks.extend(page_chunks)
                    chunk_idx += len(page_chunks)

            doc.close()

            return ExtractionResult(
                document_id=document.document_id,
                chunks=chunks,
                metadata=meta,
                raw_text_length=total_text_length,
                total_pages=total_pages,
            )

        except Exception as e:
            logger.error("Failed to extract PDF %s: %s", document.file_path, e, exc_info=True)
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"PDF extraction error: {str(e)}",
            )
