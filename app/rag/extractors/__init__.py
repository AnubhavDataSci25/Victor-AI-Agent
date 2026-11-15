"""
Victor Document Extractors.
"""

from app.rag.extractors.base import BaseExtractor
from app.rag.extractors.docx_extractor import DocxExtractor
from app.rag.extractors.excel_extractor import ExcelExtractor
from app.rag.extractors.factory import ExtractorFactory
from app.rag.extractors.pdf_extractor import PDFExtractor
from app.rag.extractors.pptx_extractor import PPTXExtractor
from app.rag.extractors.text_extractor import TextExtractor

__all__ = [
    "BaseExtractor",
    "PDFExtractor",
    "DocxExtractor",
    "ExcelExtractor",
    "PPTXExtractor",
    "TextExtractor",
    "ExtractorFactory",
]
