"""
Victor Conversational Document Intelligence & RAG Agent — Extractor Factory.

Factory that selects and instantiates the proper document extractor based on
file type, MIME type, or file extension.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, Type

from app.rag.extractors.base import BaseExtractor
from app.rag.extractors.docx_extractor import DocxExtractor
from app.rag.extractors.excel_extractor import ExcelExtractor
from app.rag.extractors.pdf_extractor import PDFExtractor
from app.rag.extractors.pptx_extractor import PPTXExtractor
from app.rag.extractors.text_extractor import TextExtractor
from app.rag.models import Document, DocumentType


class ExtractorFactory:
    """Resolves and instantiates the appropriate BaseExtractor for a document."""

    _EXTRACTORS: Dict[DocumentType, Type[BaseExtractor]] = {
        DocumentType.PDF: PDFExtractor,
        DocumentType.DOCX: DocxExtractor,
        DocumentType.DOC: DocxExtractor,  # Best-effort fallback
        DocumentType.XLSX: ExcelExtractor,
        DocumentType.XLS: ExcelExtractor,
        DocumentType.PPTX: PPTXExtractor,
        DocumentType.CSV: TextExtractor,
        DocumentType.TXT: TextExtractor,
        DocumentType.MD: TextExtractor,
        DocumentType.JSON: TextExtractor,
        DocumentType.OTHER: TextExtractor,
    }

    @classmethod
    def get_extractor(cls, document_or_type: Document | DocumentType | str, **kwargs) -> BaseExtractor:
        """
        Returns an extractor instance configured with the specified kwargs (chunk_size, etc.).
        """
        if isinstance(document_or_type, Document):
            doc_type = document_or_type.doc_type
        elif isinstance(document_or_type, DocumentType):
            doc_type = document_or_type
        elif isinstance(document_or_type, str):
            # Could be a file extension or path
            ext = Path(document_or_type).suffix if "." in document_or_type else document_or_type
            doc_type = DocumentType.from_extension(ext)
        else:
            doc_type = DocumentType.OTHER

        extractor_cls = cls._EXTRACTORS.get(doc_type, TextExtractor)
        return extractor_cls(**kwargs)
