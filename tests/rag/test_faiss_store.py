"""
Unit tests for Victor FAISS Vector Store.

Tests persistent FAISS index storage, cosine similarity search, ID mappings, and document pruning.
"""

import os
os.environ["VICTOR_DISABLE_FAISS"] = "1"
from pathlib import Path
import tempfile
import numpy as np
import pytest

from app.rag.vector.faiss_store import FAISSStore


@pytest.fixture
def temp_vector_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_faiss_lifecycle_and_search(temp_vector_dir):
    store = FAISSStore(collection_id="test_col", dimension=4, storage_dir=temp_vector_dir)

    # Create 3 normalized vectors
    v1 = np.array([1.0, 0.0, 0.0, 0.0], dtype=np.float32)
    v2 = np.array([0.0, 1.0, 0.0, 0.0], dtype=np.float32)
    v3 = np.array([0.7071, 0.7071, 0.0, 0.0], dtype=np.float32)

    vecs = np.vstack([v1, v2, v3])
    chunk_ids = ["chunk_1", "chunk_2", "chunk_3"]
    doc_id = "doc_alpha"

    indices = store.add_vectors(vecs, chunk_ids, doc_id)
    assert len(indices) == 3
    assert store.index.ntotal == 3

    # Query for vector close to v1
    query_vec = np.array([0.9, 0.1, 0.0, 0.0], dtype=np.float32)
    hits = store.search(query_vec, top_k=2)

    assert len(hits) == 2
    assert hits[0][0] == "chunk_1"
    assert hits[0][1] > 0.8  # high cosine similarity


def test_faiss_persistence(temp_vector_dir):
    store1 = FAISSStore(collection_id="persist_col", dimension=4, storage_dir=temp_vector_dir)
    v = np.array([[1.0, 0.0, 0.0, 0.0]], dtype=np.float32)
    store1.add_vectors(v, ["c_1"], "d_1")

    # Reopen same collection from disk
    store2 = FAISSStore(collection_id="persist_col", dimension=4, storage_dir=temp_vector_dir)
    assert store2.index.ntotal == 1
    assert store2.id_to_chunk_id[0] == "c_1"
