"""
Victor Conversational Document Intelligence & RAG Agent — Embedding Providers.

Provides hybrid embedding capabilities:
1. NVIDIA NIM Hosted Embeddings (nvidia/llama-3.2-nv-embedqa-1b-v1)
2. Google Gemini Hosted Embeddings (text-embedding-004)
3. Local CPU Sentence Transformers (BAAI/bge-small-en-v1.5 or all-MiniLM-L6-v2)
4. Fast Fallback Hashing Embeddings (pure CPU numpy, zero-latency fallback)

All providers return L2-normalized numpy arrays suitable for FAISS Inner Product search.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
import logging
import os
from typing import Any, List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class BaseEmbeddingProvider(ABC):
    """Abstract contract for document and query embedding generators."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @abstractmethod
    def embed_texts(self, texts: List[str], input_type: str = "passage") -> np.ndarray:
        """Embeds a batch of texts. Returns shape [len(texts), dimension]."""
        pass

    @abstractmethod
    def embed_query(self, query: str) -> np.ndarray:
        """Embeds a single search query. Returns shape [dimension]."""
        pass


class NIMEmbeddingProvider(BaseEmbeddingProvider):
    """NVIDIA NIM Hosted Embedding Provider."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: str = "nvidia/llama-3.2-nv-embedqa-1b-v1",
        base_url: str = "https://integrate.api.nvidia.com/v1",
        dimension: int = 2048,
    ):
        self._api_key = api_key or os.getenv("NVIDIA_NIM_API") or os.getenv("NVIDIA_API_KEY")
        self.model_name = model_name
        self.base_url = base_url.rstrip("/")
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str], input_type: str = "passage") -> np.ndarray:
        if not self._api_key:
            raise ValueError("NVIDIA_NIM_API key not configured")

        import httpx

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        # Batch into max 50 texts per call
        all_embeddings: List[List[float]] = []
        batch_size = 50

        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            payload = {
                "input": batch,
                "model": self.model_name,
                "input_type": input_type,
            }
            with httpx.Client(timeout=45.0) as client:
                resp = client.post(f"{self.base_url}/embeddings", headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                for item in data.get("data", []):
                    all_embeddings.append(item["embedding"])

        arr = np.array(all_embeddings, dtype=np.float32)
        if arr.shape[0] > 0:
            self._dim = arr.shape[1]
        return arr

    def embed_query(self, query: str) -> np.ndarray:
        res = self.embed_texts([query], input_type="query")
        return res[0]


class GeminiEmbeddingProvider(BaseEmbeddingProvider):
    """Google Gemini Embedding Provider (text-embedding-004)."""

    def __init__(self, api_key: Optional[str] = None, model_name: str = "text-embedding-004"):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name
        self._dim = 768

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_texts(self, texts: List[str], input_type: str = "passage") -> np.ndarray:
        if not self._api_key:
            raise ValueError("GEMINI_API_KEY not configured")

        from google import genai

        client = genai.Client(api_key=self._api_key)
        all_embeddings = []

        # Gemini supports batch embedding
        batch_size = 100
        for i in range(0, len(texts), batch_size):
            batch = texts[i : i + batch_size]
            result = client.models.embed_content(
                model=self.model_name,
                contents=batch,
            )
            for emb in result.embeddings:
                all_embeddings.append(emb.values)

        arr = np.array(all_embeddings, dtype=np.float32)
        if arr.shape[0] > 0:
            self._dim = arr.shape[1]
        return arr

    def embed_query(self, query: str) -> np.ndarray:
        res = self.embed_texts([query], input_type="query")
        return res[0]


class LocalSentenceTransformerProvider(BaseEmbeddingProvider):
    """Local CPU SentenceTransformer Provider."""

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5", dimension: int = 384):
        self.model_name = model_name
        self._dim = dimension
        self._model = None

    @property
    def dimension(self) -> int:
        return self._dim

    def _get_model(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            # Force strictly CPU mode (2GB VRAM laptop constraint)
            logger.info("Loading local embedding model '%s' on CPU...", self.model_name)
            self._model = SentenceTransformer(self.model_name, device="cpu")
            self._dim = self._model.get_sentence_embedding_dimension()
        return self._model

    def embed_texts(self, texts: List[str], input_type: str = "passage") -> np.ndarray:
        model = self._get_model()
        embeddings = model.encode(texts, batch_size=32, show_progress_bar=False, normalize_embeddings=True)
        return np.array(embeddings, dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        model = self._get_model()
        emb = model.encode(query, show_progress_bar=False, normalize_embeddings=True)
        return np.array(emb, dtype=np.float32)


class FastFallbackEmbeddingProvider(BaseEmbeddingProvider):
    """
    Deterministic Hash/TF-IDF based vectorizer with fixed dimension.
    Zero-dependency, offline, runs in < 1ms, guaranteed to work when no weights downloaded.
    """

    def __init__(self, dimension: int = 384):
        self._dim = dimension

    @property
    def dimension(self) -> int:
        return self._dim

    def _hash_text(self, text: str) -> np.ndarray:
        import hashlib
        import re

        words = re.findall(r"\w+", text.lower())
        vec = np.zeros(self._dim, dtype=np.float32)
        if not words:
            return vec

        for w in words:
            h = int(hashlib.md5(w.encode("utf-8")).hexdigest(), 16)
            idx = h % self._dim
            sign = 1.0 if (h % 2 == 0) else -1.0
            vec[idx] += sign

        norm = np.linalg.norm(vec)
        if norm > 0:
            vec = vec / norm
        return vec

    def embed_texts(self, texts: List[str], input_type: str = "passage") -> np.ndarray:
        return np.array([self._hash_text(t) for t in texts], dtype=np.float32)

    def embed_query(self, query: str) -> np.ndarray:
        return self._hash_text(query)


class HybridEmbeddingManager:
    """
    Unified manager that selects the best available embedding provider with fallbacks.
    Priority:
    1. NVIDIA NIM (if key configured and online)
    2. Google Gemini (if key configured and online)
    3. Local SentenceTransformer (CPU)
    4. Fast Fallback Hash Vectorizer
    """

    def __init__(self, preferred_provider: str = "auto"):
        self.preferred_provider = preferred_provider
        self._provider: Optional[BaseEmbeddingProvider] = None

    def get_provider(self) -> BaseEmbeddingProvider:
        if self._provider is not None:
            return self._provider

        if os.environ.get("VICTOR_FAST_EMBEDDING") == "1":
            self._provider = FastFallbackEmbeddingProvider()
            logger.info("Using Fast Fallback Embedding Provider (VICTOR_FAST_EMBEDDING=1)")
            return self._provider

        # Check preferred
        if self.preferred_provider == "nim" or (self.preferred_provider == "auto" and os.getenv("NVIDIA_NIM_API")):
            try:
                p = NIMEmbeddingProvider()
                self._provider = p
                logger.info("Using NVIDIA NIM Embedding Provider (%s)", p.model_name)
                return self._provider
            except Exception as e:
                logger.warning("Could not initialize NIM Embedding: %s", e)

        if self.preferred_provider == "gemini" or (self.preferred_provider == "auto" and os.getenv("GEMINI_API_KEY")):
            try:
                p = GeminiEmbeddingProvider()
                self._provider = p
                logger.info("Using Gemini Embedding Provider (%s)", p.model_name)
                return self._provider
            except Exception as e:
                logger.warning("Could not initialize Gemini Embedding: %s", e)

        try:
            p = LocalSentenceTransformerProvider()
            self._provider = p
            logger.info("Using Local SentenceTransformer Provider (%s on CPU)", p.model_name)
            return self._provider
        except Exception as e:
            logger.warning("Could not initialize Local SentenceTransformer: %s", e)

        self._provider = FastFallbackEmbeddingProvider()
        logger.info("Using Fast Fallback Embedding Provider (384-dim hash)")
        return self._provider

    def _fallback_provider(self, failed_provider: BaseEmbeddingProvider) -> BaseEmbeddingProvider:
        logger.warning("Embedding provider %s encountered an error; falling back...", type(failed_provider).__name__)
        if isinstance(failed_provider, NIMEmbeddingProvider):
            if os.getenv("GEMINI_API_KEY"):
                try:
                    p = GeminiEmbeddingProvider()
                    logger.info("Fell back to Gemini Embedding Provider")
                    return p
                except Exception:
                    pass
            try:
                p = LocalSentenceTransformerProvider()
                logger.info("Fell back to Local SentenceTransformer Provider")
                return p
            except Exception:
                pass
            p = FastFallbackEmbeddingProvider()
            logger.info("Fell back to Fast Fallback Embedding Provider")
            return p
        elif isinstance(failed_provider, GeminiEmbeddingProvider):
            try:
                p = LocalSentenceTransformerProvider()
                logger.info("Fell back to Local SentenceTransformer Provider")
                return p
            except Exception:
                pass
            p = FastFallbackEmbeddingProvider()
            logger.info("Fell back to Fast Fallback Embedding Provider")
            return p
        elif isinstance(failed_provider, LocalSentenceTransformerProvider):
            p = FastFallbackEmbeddingProvider()
            logger.info("Fell back to Fast Fallback Embedding Provider")
            return p
        else:
            return FastFallbackEmbeddingProvider()

    @property
    def dimension(self) -> int:
        return self.get_provider().dimension

    def embed_texts(self, texts: List[str]) -> np.ndarray:
        while True:
            provider = self.get_provider()
            try:
                return provider.embed_texts(texts)
            except Exception as e:
                logger.warning("Embedding provider %s embed_texts failed: %s; transitioning to next provider", type(provider).__name__, e)
                if isinstance(provider, FastFallbackEmbeddingProvider):
                    raise e
                self._provider = self._fallback_provider(provider)

    def embed_query(self, query: str) -> np.ndarray:
        while True:
            provider = self.get_provider()
            try:
                return provider.embed_query(query)
            except Exception as e:
                logger.warning("Embedding provider %s embed_query failed: %s; transitioning to next provider", type(provider).__name__, e)
                if isinstance(provider, FastFallbackEmbeddingProvider):
                    raise e
                self._provider = self._fallback_provider(provider)
