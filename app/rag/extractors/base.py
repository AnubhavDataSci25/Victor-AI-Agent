"""
Victor Conversational Document Intelligence & RAG Agent — Base Extractor.

Defines the contract and utility methods for all format-specific extractors.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
import uuid

from app.rag.models import Document, DocumentChunk, ExtractionResult


class BaseExtractor(ABC):
    """Abstract base class for document format extractors."""

    def __init__(self, chunk_size: int = 600, chunk_overlap: int = 100):
        self.chunk_size = chunk_size  # Approx target tokens per chunk
        self.chunk_overlap = chunk_overlap  # Approx overlap tokens

    @abstractmethod
    def extract(self, document: Document) -> ExtractionResult:
        """Extract content, structure, and chunks from a document."""
        pass

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimation (1 token ≈ 4 characters or ~0.75 words)."""
        if not text:
            return 0
        return max(1, len(text) // 4)

    def chunk_text(
        self,
        text: str,
        document_id: str,
        start_index: int = 0,
        page_number: Optional[int] = None,
        section_title: Optional[str] = None,
        sheet_name: Optional[str] = None,
        cell_range: Optional[str] = None,
        slide_number: Optional[int] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        """
        Splits text into sliding-window chunks respecting paragraphs and sentences.
        Preserves structural metadata (page, section, sheet, slide).
        """
        if not text or not text.strip():
            return []

        clean_text = text.strip()
        tokens = self.estimate_tokens(clean_text)

        # If text is small enough, return as single chunk
        if tokens <= self.chunk_size:
            chunk = DocumentChunk(
                chunk_id=f"{document_id}_{start_index}_{uuid.uuid4().hex[:6]}",
                document_id=document_id,
                chunk_index=start_index,
                content=clean_text,
                page_number=page_number,
                section_title=section_title,
                sheet_name=sheet_name,
                cell_range=cell_range,
                slide_number=slide_number,
                metadata=extra_metadata or {},
                token_count=tokens,
            )
            return [chunk]

        # Multi-chunk splitting
        paragraphs = clean_text.split("\n\n")
        chunks: List[DocumentChunk] = []
        current_chunk_paras: List[str] = []
        current_tokens = 0
        chunk_idx = start_index

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_tokens = self.estimate_tokens(para)

            # If a single paragraph is larger than chunk_size, split by sentences
            if para_tokens > self.chunk_size:
                # Flush pending chunk
                if current_chunk_paras:
                    c_text = "\n\n".join(current_chunk_paras)
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{document_id}_{chunk_idx}_{uuid.uuid4().hex[:6]}",
                            document_id=document_id,
                            chunk_index=chunk_idx,
                            content=c_text,
                            page_number=page_number,
                            section_title=section_title,
                            sheet_name=sheet_name,
                            cell_range=cell_range,
                            slide_number=slide_number,
                            metadata=extra_metadata or {},
                            token_count=self.estimate_tokens(c_text),
                        )
                    )
                    chunk_idx += 1
                    current_chunk_paras = []
                    current_tokens = 0

                # Split large paragraph by sentences (. / ? / !)
                sentences = [s.strip() for s in para.replace(".\n", ". ").split(". ") if s.strip()]
                sent_chunk: List[str] = []
                sent_tokens = 0
                for s in sentences:
                    s_t = self.estimate_tokens(s)
                    if sent_tokens + s_t > self.chunk_size and sent_chunk:
                        joined = ". ".join(sent_chunk) + "."
                        chunks.append(
                            DocumentChunk(
                                chunk_id=f"{document_id}_{chunk_idx}_{uuid.uuid4().hex[:6]}",
                                document_id=document_id,
                                chunk_index=chunk_idx,
                                content=joined,
                                page_number=page_number,
                                section_title=section_title,
                                sheet_name=sheet_name,
                                cell_range=cell_range,
                                slide_number=slide_number,
                                metadata=extra_metadata or {},
                                token_count=self.estimate_tokens(joined),
                            )
                        )
                        chunk_idx += 1
                        # Retain tail for overlap
                        sent_chunk = [sent_chunk[-1], s] if len(sent_chunk) > 1 else [s]
                        sent_tokens = sum(self.estimate_tokens(x) for x in sent_chunk)
                    else:
                        sent_chunk.append(s)
                        sent_tokens += s_t

                if sent_chunk:
                    joined = ". ".join(sent_chunk)
                    if not joined.endswith("."):
                        joined += "."
                    current_chunk_paras.append(joined)
                    current_tokens = self.estimate_tokens(joined)

            elif current_tokens + para_tokens > self.chunk_size:
                # Flush current chunk
                c_text = "\n\n".join(current_chunk_paras)
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{document_id}_{chunk_idx}_{uuid.uuid4().hex[:6]}",
                        document_id=document_id,
                        chunk_index=chunk_idx,
                        content=c_text,
                        page_number=page_number,
                        section_title=section_title,
                        sheet_name=sheet_name,
                        cell_range=cell_range,
                        slide_number=slide_number,
                        metadata=extra_metadata or {},
                        token_count=self.estimate_tokens(c_text),
                    )
                )
                chunk_idx += 1
                # Overlap: keep the last paragraph if possible
                if current_chunk_paras and len(current_chunk_paras) > 1:
                    current_chunk_paras = [current_chunk_paras[-1], para]
                    current_tokens = sum(self.estimate_tokens(x) for x in current_chunk_paras)
                else:
                    current_chunk_paras = [para]
                    current_tokens = para_tokens
            else:
                current_chunk_paras.append(para)
                current_tokens += para_tokens

        # Flush any remaining paragraphs
        if current_chunk_paras:
            c_text = "\n\n".join(current_chunk_paras)
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{document_id}_{chunk_idx}_{uuid.uuid4().hex[:6]}",
                    document_id=document_id,
                    chunk_index=chunk_idx,
                    content=c_text,
                    page_number=page_number,
                    section_title=section_title,
                    sheet_name=sheet_name,
                    cell_range=cell_range,
                    slide_number=slide_number,
                    metadata=extra_metadata or {},
                    token_count=self.estimate_tokens(c_text),
                )
            )

        return chunks
