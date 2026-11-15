"""
Victor Conversational Document Intelligence & RAG Agent — PowerPoint (PPTX) Extractor.

Extracts text, slide titles, notes, shapes, and tables from PowerPoint presentations (.pptx)
using python-pptx.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List

from pptx import Presentation

from app.rag.extractors.base import BaseExtractor
from app.rag.models import Document, DocumentChunk, ExtractionResult

logger = logging.getLogger(__name__)


class PPTXExtractor(BaseExtractor):
    """Structure-aware PowerPoint (.pptx) presentation extractor."""

    def extract(self, document: Document) -> ExtractionResult:
        file_path = Path(document.file_path)
        if not file_path.exists():
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"File not found: {document.file_path}",
            )

        try:
            prs = Presentation(str(file_path))
            total_slides = len(prs.slides)
            meta: Dict[str, Any] = {
                "title": file_path.stem,
                "slide_count": total_slides,
            }

            try:
                core_props = prs.core_properties
                if core_props.title:
                    meta["title"] = core_props.title
                if core_props.author:
                    meta["author"] = core_props.author
                if core_props.subject:
                    meta["subject"] = core_props.subject
            except Exception as pe:
                logger.debug("Could not read pptx core properties: %s", pe)

            chunks: List[DocumentChunk] = []
            chunk_idx = 0
            total_text_length = 0

            for slide_idx, slide in enumerate(prs.slides):
                slide_num = slide_idx + 1
                slide_title = ""
                slide_text_elements: List[str] = []

                # Extract slide title if available
                if slide.shapes.title and slide.shapes.title.text.strip():
                    slide_title = slide.shapes.title.text.strip()

                # Extract shapes text and tables
                for shape in slide.shapes:
                    if shape == slide.shapes.title:
                        continue

                    # Text frame
                    if shape.has_text_frame and shape.text_frame:
                        shape_text = shape.text_frame.text.strip()
                        if shape_text:
                            slide_text_elements.append(shape_text)

                    # Table shape
                    elif shape.has_table and shape.table:
                        tbl = shape.table
                        rows = []
                        for row in tbl.rows:
                            cells = [c.text.strip().replace("\n", " ") for c in row.cells]
                            if any(cells):
                                rows.append(" | ".join(cells))
                        if rows:
                            slide_text_elements.append(f"[Table on Slide {slide_num}]:\n" + "\n".join(rows))

                # Slide notes
                if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
                    notes = slide.notes_slide.notes_text_frame.text.strip()
                    if notes:
                        slide_text_elements.append(f"[Speaker Notes]: {notes}")

                full_slide_content = f"Slide {slide_num}"
                if slide_title:
                    full_slide_content += f": {slide_title}"
                if slide_text_elements:
                    full_slide_content += "\n\n" + "\n\n".join(slide_text_elements)

                total_text_length += len(full_slide_content)

                slide_chunks = self.chunk_text(
                    text=full_slide_content,
                    document_id=document.document_id,
                    start_index=chunk_idx,
                    slide_number=slide_num,
                    section_title=slide_title or f"Slide {slide_num}",
                    extra_metadata={"slide": slide_num, "title": slide_title},
                )
                chunks.extend(slide_chunks)
                chunk_idx += len(slide_chunks)

            return ExtractionResult(
                document_id=document.document_id,
                chunks=chunks,
                metadata=meta,
                raw_text_length=total_text_length,
                total_pages=total_slides,
            )

        except Exception as e:
            logger.error("Failed to extract PPTX %s: %s", document.file_path, e, exc_info=True)
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"PPTX extraction error: {str(e)}",
            )
