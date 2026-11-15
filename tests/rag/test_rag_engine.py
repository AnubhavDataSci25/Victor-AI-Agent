"""
Integration tests for Victor RAGEngine.

Tests end-to-end ingestion, hash idempotency, vector querying, and grounded answers.
"""

import os
os.environ["VICTOR_DISABLE_FAISS"] = "1"
from pathlib import Path
import tempfile
import pytest

from app.rag.embeddings import FastFallbackEmbeddingProvider, HybridEmbeddingManager
from app.rag.models import IngestionStatus, RAGQueryRequest
from app.rag.rag_engine import RAGEngine
from app.rag.router import GenerationResult, ModelRouter
from app.rag.store import DocumentStore


class MockModelRouter(ModelRouter):
    async def generate_response(self, prompt: str, **kwargs) -> GenerationResult:
        return GenerationResult(
            text="According to the research findings on Page 1, stroke prediction was evaluated using Logistic Regression.",
            provider="mock_gemini",
            model="gemini-2.5-flash",
            latency_ms=45.0,
        )


@pytest.fixture
def rag_engine():
    td = tempfile.mkdtemp()
    db_path = Path(td) / "test_docs.db"
    vec_dir = Path(td) / "vectors"

    store = DocumentStore(db_path=db_path)
    embed_mgr = HybridEmbeddingManager()
    # Use fast fallback provider for zero-latency, deterministic unit testing
    embed_mgr._provider = FastFallbackEmbeddingProvider(dimension=384)

    router = MockModelRouter()
    engine = RAGEngine(
        store=store,
        embedding_manager=embed_mgr,
        model_router=router,
        vector_storage_dir=vec_dir,
    )
    yield engine, Path(td)


@pytest.mark.asyncio
async def test_end_to_end_ingest_and_query(rag_engine):
    engine, td = rag_engine

    sample_doc = td / "stroke_prediction.txt"
    sample_doc.write_text(
        "Introduction\nStroke prediction research project.\n\n"
        "Methodology\nWe applied logistic regression and gradient boosting to analyze patient indicators.\n\n"
        "Results\nAchieved 94 percent accuracy on test sets.",
        encoding="utf-8",
    )

    # 1. Ingest
    doc = engine.ingest_document(str(sample_doc))
    assert doc.status == IngestionStatus.INDEXED
    assert doc.total_chunks > 0

    # 2. Hash idempotency check
    doc_repeat = engine.ingest_document(str(sample_doc))
    assert doc_repeat.document_id == doc.document_id

    # 3. Query
    req = RAGQueryRequest(query="What methodology was used in stroke prediction?")
    response = await engine.query(req)

    assert response.answer != ""
    assert len(response.citations) > 0
    assert response.citations[0].document_name == "stroke_prediction.txt"
    assert engine.active_document_id == doc.document_id


@pytest.mark.asyncio
async def test_summarize_and_notes(rag_engine):
    engine, td = rag_engine

    sample_doc = td / "ai_ethics.txt"
    sample_doc.write_text(
        "AI Ethics Guidelines.\n1. Transparency: models must explain their reasoning.\n2. Fairness: no demographic bias.",
        encoding="utf-8",
    )
    doc = engine.ingest_document(str(sample_doc))

    sum_res = await engine.summarize_document(doc.document_id)
    assert sum_res.answer != ""

    notes_res = await engine.generate_revision_notes(doc.document_id)
    assert notes_res.answer != ""
