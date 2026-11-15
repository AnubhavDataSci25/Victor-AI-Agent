"""
Victor Conversational Document Intelligence & RAG Agent — REST API Router.

Exposes endpoints for document upload, ingestion, semantic querying, summarization,
comparison, revision notes, and collection management.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from app.rag.models import RAGQueryRequest
from app.tools.rag.document_tools import get_rag_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/documents", tags=["documents"])
UPLOAD_DIR = Path("data/documents/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class IngestPathRequest(BaseModel):
    file_path: str
    collection_id: str = "default"
    force_reindex: bool = False


class QueryRequest(BaseModel):
    query: str
    collection_id: Optional[str] = "default"
    document_ids: Optional[List[str]] = None
    top_k: int = 5


class SummarizeRequest(BaseModel):
    document_id: str
    summary_type: str = "comprehensive"


class CompareRequest(BaseModel):
    document_id_1: str
    document_id_2: str


class RevisionNotesRequest(BaseModel):
    document_id: str


class CreateCollectionRequest(BaseModel):
    collection_id: str
    name: str
    description: str = ""


@router.get("")
async def list_documents(collection_id: Optional[str] = None):
    """Lists all indexed documents and storage statistics."""
    engine = get_rag_engine()
    docs = engine.store.list_documents(collection_id)
    collections = engine.store.list_collections()
    total_chunks = sum(d.total_chunks for d in docs)
    total_bytes = sum(d.file_size_bytes for d in docs)

    return {
        "success": True,
        "total_documents": len(docs),
        "total_chunks": total_chunks,
        "total_size_mb": round(total_bytes / (1024 * 1024), 2),
        "active_document_id": engine.active_document_id,
        "collections": [c.to_dict() for c in collections],
        "documents": [d.to_dict() for d in docs],
    }


@router.get("/collections")
async def list_collections():
    """Lists all document collections."""
    engine = get_rag_engine()
    collections = engine.store.list_collections()
    return {"success": True, "collections": [c.to_dict() for c in collections]}


@router.post("/collections")
async def create_collection(req: CreateCollectionRequest):
    """Creates a new document collection."""
    engine = get_rag_engine()
    col = engine.store.create_collection(
        collection_id=req.collection_id,
        name=req.name,
        description=req.description,
    )
    return {"success": True, "collection": col.to_dict()}


@router.post("/ingest")
async def ingest_file_path(req: IngestPathRequest):
    """Ingests a file from local filesystem."""
    engine = get_rag_engine()
    try:
        doc = engine.ingest_document(
            file_path=req.file_path,
            collection_id=req.collection_id,
            force_reindex=req.force_reindex,
        )
        return {
            "success": doc.status.value != "FAILED",
            "document": doc.to_dict(),
            "error": doc.error_message,
        }
    except Exception as e:
        logger.error("Failed to ingest path %s: %s", req.file_path, e)
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    collection_id: str = Form("default"),
):
    """Uploads and ingests a document directly from desktop UI."""
    engine = get_rag_engine()
    dest_path = UPLOAD_DIR / file.filename
    try:
        with open(dest_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        doc = engine.ingest_document(str(dest_path), collection_id=collection_id)
        return {
            "success": doc.status.value != "FAILED",
            "document": doc.to_dict(),
            "error": doc.error_message,
        }
    except Exception as e:
        logger.error("Failed to upload document %s: %s", file.filename, e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}")
async def get_document(document_id: str):
    """Retrieves metadata and status of a single document."""
    engine = get_rag_engine()
    doc = engine.store.get_document(document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"success": True, "document": doc.to_dict()}


@router.get("/{document_id}/chunks")
async def get_document_chunks(document_id: str):
    """Retrieves all indexed text chunks and metadata for a single document."""
    engine = get_rag_engine()
    chunks = engine.store.get_chunks_for_document(document_id)
    return {
        "success": True,
        "document_id": document_id,
        "total_chunks": len(chunks),
        "chunks": [c.to_dict() for c in chunks],
    }


@router.delete("/{document_id}")
async def delete_document(document_id: str):
    """Deletes a document from SQLite and removes vectors from FAISS."""
    engine = get_rag_engine()
    success = engine.delete_document(document_id)
    if not success:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"success": True, "document_id": document_id}


@router.post("/query")
async def query_documents(req: QueryRequest):
    """Executes a grounded conversational semantic query with citations."""
    engine = get_rag_engine()
    rag_req = RAGQueryRequest(
        query=req.query,
        collection_id=req.collection_id,
        document_ids=req.document_ids,
        top_k=req.top_k,
    )
    res = await engine.query(rag_req)
    return {
        "success": True,
        "response": res.to_dict(),
    }


@router.get("/latest-summary")
async def get_latest_summary():
    """Retrieves the most recent document summary generated via voice or UI."""
    engine = get_rag_engine()
    docs = engine.store.list_documents()
    for d in docs:
        if d.metadata and "latest_summary" in d.metadata:
            return {
                "success": True,
                "document_id": d.document_id,
                "file_name": d.file_name,
                "summary": d.metadata["latest_summary"],
                "updated_at": d.updated_at,
            }
    return {"success": False, "summary": None}


@router.post("/summarize")
async def summarize_document_endpoint(req: SummarizeRequest):
    """Summarizes a specific document."""
    engine = get_rag_engine()
    res = await engine.summarize_document(req.document_id, summary_type=req.summary_type)
    return {
        "success": True,
        "response": res.to_dict(),
    }


@router.post("/compare")
async def compare_documents_endpoint(req: CompareRequest):
    """Compares two documents side by side."""
    engine = get_rag_engine()
    res = await engine.compare_documents(req.document_id_1, req.document_id_2)
    return {
        "success": True,
        "response": res.to_dict(),
    }


@router.post("/notes")
async def revision_notes_endpoint(req: RevisionNotesRequest):
    """Generates revision notes for a document."""
    engine = get_rag_engine()
    res = await engine.generate_revision_notes(req.document_id)
    return {
        "success": True,
        "response": res.to_dict(),
    }
