"""
Unit and integration tests for Victor Document Intelligence & RAG API endpoints.
"""

import tempfile
from pathlib import Path
import pytest
from starlette.testclient import TestClient

from app.main import app
from app.tools.rag.document_tools import get_rag_engine


@pytest.fixture
def client():
    return TestClient(app)


def test_api_collections_flow(client):
    # 1. List collections
    res = client.get("/api/documents/collections")
    assert res.status_code == 200
    data = res.json()
    assert data["success"] is True
    cols = data["collections"]
    assert isinstance(cols, list)
    assert any(c["collection_id"] == "default" for c in cols)

    # 2. Create custom collection
    res = client.post(
        "/api/documents/collections",
        json={"collection_id": "research_papers", "name": "Research Papers", "description": "Medical research"},
    )
    assert res.status_code == 200
    res_data = res.json()
    assert res_data["success"] is True
    assert res_data["collection"]["collection_id"] == "research_papers"


def test_api_document_ingest_and_query_flow(client):
    with tempfile.TemporaryDirectory() as td:
        sample_file = Path(td) / "sample_study.txt"
        sample_file.write_text(
            "Study on Diabetes Risk.\n"
            "Author: Victor Research Lab.\n\n"
            "Findings: High glucose and BMI correlate with elevated HbA1c levels.",
            encoding="utf-8",
        )

        # 1. Ingest document via file_path
        res = client.post("/api/documents/ingest", json={"file_path": str(sample_file)})
        assert res.status_code == 200
        ingest_res = res.json()
        assert ingest_res["success"] is True
        doc = ingest_res["document"]
        assert doc["file_name"] == "sample_study.txt"
        assert doc["status"] == "INDEXED"
        doc_id = doc["document_id"]

        # 2. List documents
        res = client.get("/api/documents")
        assert res.status_code == 200
        docs_data = res.json()
        assert docs_data["success"] is True
        assert any(d["document_id"] == doc_id for d in docs_data["documents"])

        # 3. Get single document details
        res = client.get(f"/api/documents/{doc_id}")
        assert res.status_code == 200
        assert res.json()["document"]["document_id"] == doc_id

        # 4. Get document chunks
        res = client.get(f"/api/documents/{doc_id}/chunks")
        assert res.status_code == 200
        chunks_data = res.json()
        assert chunks_data["success"] is True
        assert len(chunks_data["chunks"]) > 0

        # 5. Query document via RAG
        res = client.post(
            "/api/documents/query",
            json={
                "query": "What correlates with elevated HbA1c levels?",
                "document_ids": [doc_id],
            },
        )
        assert res.status_code == 200
        rag_res = res.json()
        assert rag_res["success"] is True
        assert "answer" in rag_res["response"]
        assert len(rag_res["response"]["citations"]) > 0

        # 6. Delete document
        res = client.delete(f"/api/documents/{doc_id}")
        assert res.status_code == 200
        assert res.json()["success"] is True
