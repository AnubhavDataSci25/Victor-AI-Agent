"""
Victor Conversational Document Intelligence & RAG Agent — Vector Store.

Manages persistent vector indices per collection with L2-normalized cosine similarity,
mapping chunk IDs to vector IDs, and handling incremental updates and persistence.
Seamlessly uses FAISS FlatIP when available, with an automatic pure NumPy fallback.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import threading
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

_FAISS_AVAILABLE = False
if os.environ.get("VICTOR_DISABLE_FAISS", "0") != "1":
    try:
        import faiss
        _FAISS_AVAILABLE = True
    except Exception as fe:
        logger.debug("FAISS native library not loaded: %s; using NumPy vector engine", fe)
    except BaseException as be:
        logger.debug("FAISS base exception: %s", be)

DEFAULT_VECTOR_DIR = Path("data/vectors")


class _IndexWrapper:
    def __init__(self, store: "FAISSStore"):
        self._store = store

    @property
    def ntotal(self) -> int:
        return len(self._store._vectors) if self._store._vectors is not None else 0

    @property
    def d(self) -> int:
        return self._store.dimension


class FAISSStore:
    """Thread-safe vector index manager for a document collection."""

    def __init__(
        self,
        collection_id: str = "default",
        dimension: int = 384,
        storage_dir: Path | str = DEFAULT_VECTOR_DIR,
    ):
        self.collection_id = collection_id
        self.dimension = dimension
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        self.index_file = self.storage_dir / f"{self.collection_id}.index"
        self.numpy_file = self.storage_dir / f"{self.collection_id}_vectors.npy"
        self.mapping_file = self.storage_dir / f"{self.collection_id}_mapping.json"

        self._lock = threading.RLock()
        self.id_to_chunk_id: Dict[int, str] = {}
        self.chunk_id_to_id: Dict[str, int] = {}
        self.chunk_id_to_doc_id: Dict[str, str] = {}

        # Vectors matrix for NumPy fallback or rebuilds
        self._vectors: Optional[np.ndarray] = None

        if _FAISS_AVAILABLE:
            self.index = faiss.IndexFlatIP(self.dimension)
        else:
            self.index = _IndexWrapper(self)

        self._load_if_exists()

    def _load_if_exists(self) -> None:
        if self.mapping_file.exists():
            try:
                with open(self.mapping_file, "r", encoding="utf-8") as f:
                    meta = json.load(f)

                self.dimension = meta.get("dimension", self.dimension)
                self.id_to_chunk_id = {int(k): v for k, v in meta.get("id_to_chunk", {}).items()}
                self.chunk_id_to_id = {k: int(v) for k, v in meta.get("chunk_to_id", {}).items()}
                self.chunk_id_to_doc_id = meta.get("chunk_to_doc", {})

                # Load NumPy vectors if exist
                if self.numpy_file.exists():
                    self._vectors = np.load(str(self.numpy_file))
                    if self._vectors.shape[0] > 0:
                        self.dimension = self._vectors.shape[1]

                if _FAISS_AVAILABLE and self.index_file.exists():
                    self.index = faiss.read_index(str(self.index_file))
                elif _FAISS_AVAILABLE and self._vectors is not None:
                    self.index = faiss.IndexFlatIP(self.dimension)
                    self.index.add(self._vectors)

                ntotal = self.index.ntotal if self.index else (len(self._vectors) if self._vectors is not None else 0)
                logger.info("Loaded vector index for '%s' (%d vectors, dim=%d)", self.collection_id, ntotal, self.dimension)
            except Exception as e:
                logger.error("Failed to load vector index for %s: %s", self.collection_id, e)
                if _FAISS_AVAILABLE:
                    self.index = faiss.IndexFlatIP(self.dimension)
                self._vectors = None

    def save(self) -> None:
        """Persists vector indices and metadata mappings to disk."""
        with self._lock:
            try:
                if _FAISS_AVAILABLE and self.index is not None:
                    faiss.write_index(self.index, str(self.index_file))

                if self._vectors is not None:
                    np.save(str(self.numpy_file), self._vectors)

                ntotal = self.index.ntotal if (self.index is not None) else (len(self._vectors) if self._vectors is not None else 0)
                meta = {
                    "dimension": self.dimension,
                    "ntotal": ntotal,
                    "id_to_chunk": {str(k): v for k, v in self.id_to_chunk_id.items()},
                    "chunk_to_id": self.chunk_id_to_id,
                    "chunk_to_doc": self.chunk_id_to_doc_id,
                }
                with open(self.mapping_file, "w", encoding="utf-8") as f:
                    json.dump(meta, f, indent=2)
            except Exception as e:
                logger.error("Failed to save vector index for %s: %s", self.collection_id, e, exc_info=True)

    def add_vectors(
        self,
        vectors: np.ndarray,
        chunk_ids: List[str],
        document_id: str,
    ) -> List[int]:
        """Adds normalized vectors and updates chunk mappings."""
        if len(vectors) == 0:
            return []

        vecs = np.ascontiguousarray(vectors, dtype=np.float32)
        if vecs.ndim == 1:
            vecs = vecs.reshape(1, -1)

        # L2-normalize
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        vecs = vecs / norms

        with self._lock:
            if self._vectors is None or len(self._vectors) == 0:
                start_idx = 0
                self._vectors = vecs
                self.dimension = vecs.shape[1]
                if _FAISS_AVAILABLE:
                    self.index = faiss.IndexFlatIP(self.dimension)
                    self.index.add(vecs)
            else:
                start_idx = len(self._vectors)
                self._vectors = np.vstack([self._vectors, vecs])
                if _FAISS_AVAILABLE and self.index is not None:
                    self.index.add(vecs)

            assigned_indices: List[int] = []
            for i, chunk_id in enumerate(chunk_ids):
                idx = start_idx + i
                self.id_to_chunk_id[idx] = chunk_id
                self.chunk_id_to_id[chunk_id] = idx
                self.chunk_id_to_doc_id[chunk_id] = document_id
                assigned_indices.append(idx)

            self.save()
            return assigned_indices

    def search(
        self,
        query_vector: np.ndarray,
        top_k: int = 5,
        filter_document_ids: Optional[List[str]] = None,
    ) -> List[Tuple[str, float]]:
        """Searches for top_k most similar vectors (Cosine similarity)."""
        if self._vectors is None or len(self._vectors) == 0:
            return []

        vec = np.ascontiguousarray(query_vector, dtype=np.float32)
        if vec.ndim == 1:
            vec = vec.reshape(1, -1)

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm

        filter_set = set(filter_document_ids) if filter_document_ids else None

        with self._lock:
            # If FAISS available, use FAISS
            if _FAISS_AVAILABLE and self.index is not None and self.index.ntotal > 0:
                fetch_k = min(self.index.ntotal, top_k * 4 if filter_document_ids else top_k)
                scores, indices = self.index.search(vec, fetch_k)
                results: List[Tuple[str, float]] = []
                for score, idx in zip(scores[0], indices[0]):
                    if idx == -1:
                        continue
                    cid = self.id_to_chunk_id.get(int(idx))
                    if not cid:
                        continue
                    if filter_set and self.chunk_id_to_doc_id.get(cid) not in filter_set:
                        continue
                    results.append((cid, float(score)))
                    if len(results) >= top_k:
                        break
                return results

            # Pure NumPy cosine similarity fallback
            scores = np.dot(self._vectors, vec.T).flatten()
            sorted_indices = np.argsort(-scores)

            results = []
            for idx in sorted_indices:
                cid = self.id_to_chunk_id.get(int(idx))
                if not cid:
                    continue
                if filter_set and self.chunk_id_to_doc_id.get(cid) not in filter_set:
                    continue
                results.append((cid, float(scores[idx])))
                if len(results) >= top_k:
                    break

            return results

    def remove_document(self, document_id: str) -> None:
        """Removes all vectors belonging to document_id."""
        with self._lock:
            chunks_to_remove = {
                cid for cid, did in self.chunk_id_to_doc_id.items() if did == document_id
            }
            if not chunks_to_remove or self._vectors is None:
                return

            keep_indices = []
            new_id_to_chunk = {}
            new_chunk_to_id = {}
            new_chunk_to_doc = {}

            for old_idx in range(len(self._vectors)):
                cid = self.id_to_chunk_id.get(old_idx)
                if cid and cid not in chunks_to_remove:
                    new_idx = len(keep_indices)
                    keep_indices.append(old_idx)
                    new_id_to_chunk[new_idx] = cid
                    new_chunk_to_id[cid] = new_idx
                    new_chunk_to_doc[cid] = self.chunk_id_to_doc_id[cid]

            if keep_indices:
                self._vectors = self._vectors[keep_indices]
                if _FAISS_AVAILABLE:
                    self.index = faiss.IndexFlatIP(self.dimension)
                    self.index.add(self._vectors)
            else:
                self._vectors = None
                if _FAISS_AVAILABLE:
                    self.index = faiss.IndexFlatIP(self.dimension)

            self.id_to_chunk_id = new_id_to_chunk
            self.chunk_id_to_id = new_chunk_to_id
            self.chunk_id_to_doc_id = new_chunk_to_doc
            self.save()
