"""
Victor Conversational Document Intelligence & RAG Agent — Data Models.

Defines schemas for documents, chunks, collections, citations, extraction results,
and conversational query states.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
import hashlib
from pathlib import Path
import time
from typing import Any, Dict, List, Optional
import uuid


class DocumentType(str, Enum):
    PDF = "PDF"
    DOCX = "DOCX"
    DOC = "DOC"
    XLSX = "XLSX"
    XLS = "XLS"
    PPTX = "PPTX"
    CSV = "CSV"
    TXT = "TXT"
    MD = "MD"
    JSON = "JSON"
    OTHER = "OTHER"

    @classmethod
    def from_extension(cls, ext: str) -> DocumentType:
        norm = ext.lower().lstrip(".")
        mapping = {
            "pdf": cls.PDF,
            "docx": cls.DOCX,
            "doc": cls.DOC,
            "xlsx": cls.XLSX,
            "xls": cls.XLS,
            "pptx": cls.PPTX,
            "csv": cls.CSV,
            "txt": cls.TXT,
            "md": cls.MD,
            "markdown": cls.MD,
            "json": cls.JSON,
        }
        return mapping.get(norm, cls.OTHER)


class IngestionStatus(str, Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    INDEXED = "INDEXED"
    FAILED = "FAILED"
    OUTDATED = "OUTDATED"


@dataclass
class SourceCitation:
    document_id: str
    document_name: str
    snippet: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    sheet_name: Optional[str] = None
    cell_range: Optional[str] = None
    slide_number: Optional[int] = None
    line_numbers: Optional[str] = None
    confidence_score: float = 0.0

    def format_citation(self) -> str:
        loc = []
        if self.page_number:
            loc.append(f"Page {self.page_number}")
        if self.section_title:
            loc.append(f"Section '{self.section_title}'")
        if self.sheet_name:
            if self.cell_range:
                loc.append(f"Sheet '{self.sheet_name}' (Cells {self.cell_range})")
            else:
                loc.append(f"Sheet '{self.sheet_name}'")
        if self.slide_number:
            loc.append(f"Slide {self.slide_number}")
        if self.line_numbers:
            loc.append(f"Lines {self.line_numbers}")

        loc_str = f" [{', '.join(loc)}]" if loc else ""
        return f"{self.document_name}{loc_str}"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentChunk:
    chunk_id: str
    document_id: str
    chunk_index: int
    content: str
    page_number: Optional[int] = None
    section_title: Optional[str] = None
    sheet_name: Optional[str] = None
    cell_range: Optional[str] = None
    slide_number: Optional[int] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    token_count: int = 0
    embedding_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentChunk:
        return cls(**data)


@dataclass
class Document:
    document_id: str
    file_path: str
    file_name: str
    file_size_bytes: int
    file_hash: str
    doc_type: DocumentType
    collection_id: str = "default"
    status: IngestionStatus = IngestionStatus.PENDING
    total_pages: Optional[int] = None
    total_chunks: int = 0
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    @classmethod
    def create_new(
        cls,
        file_path: str,
        collection_id: str = "default",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Document:
        p = Path(file_path).resolve()
        stat = p.stat()
        hasher = hashlib.sha256()
        with open(p, "rb") as f:
            for buf in iter(lambda: f.read(65536), b""):
                hasher.update(buf)
        file_hash = hasher.hexdigest()

        doc_type = DocumentType.from_extension(p.suffix)
        doc_id = f"doc_{uuid.uuid4().hex[:12]}"
        return cls(
            document_id=doc_id,
            file_path=str(p),
            file_name=p.name,
            file_size_bytes=stat.st_size,
            file_hash=file_hash,
            doc_type=doc_type,
            collection_id=collection_id,
            status=IngestionStatus.PENDING,
            metadata=metadata or {},
        )

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["doc_type"] = self.doc_type.value
        d["status"] = self.status.value
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Document:
        c = dict(data)
        if isinstance(c.get("doc_type"), str):
            c["doc_type"] = DocumentType(c["doc_type"])
        if isinstance(c.get("status"), str):
            c["status"] = IngestionStatus(c["status"])
        return cls(**c)


@dataclass
class DocumentCollection:
    collection_id: str
    name: str
    description: str = ""
    document_count: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DocumentCollection:
        return cls(**data)


@dataclass
class ExtractionResult:
    document_id: str
    chunks: List[DocumentChunk]
    metadata: Dict[str, Any] = field(default_factory=dict)
    raw_text_length: int = 0
    total_pages: Optional[int] = None
    error: Optional[str] = None


@dataclass
class RAGQueryRequest:
    query: str
    collection_id: Optional[str] = None
    document_ids: Optional[List[str]] = None
    top_k: int = 5
    conversation_context: Optional[List[Dict[str, str]]] = None
    deterministic_mode: bool = False


@dataclass
class RAGResponse:
    query: str
    answer: str
    citations: List[SourceCitation] = field(default_factory=list)
    model_used: str = ""
    provider_used: str = ""
    latency_ms: float = 0.0
    used_excel_engine: bool = False
    context_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["citations"] = [c.to_dict() for c in self.citations]
        return d
