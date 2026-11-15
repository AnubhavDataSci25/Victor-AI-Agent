"""
Victor Conversational Document Intelligence & RAG Agent — Conversational RAG Engine.

Orchestrates document ingestion, structure-aware chunking, vector indexing,
conversational retrieval, multi-provider grounded answering, source citations,
multi-document comparisons, summarization, revision notes, and quiz generation.
"""

from __future__ import annotations

import logging
from pathlib import Path
import time
from typing import Any, Dict, List, Optional, Tuple

from app.rag.embeddings import HybridEmbeddingManager
from app.rag.excel_engine import ExcelIntelligenceEngine
from app.rag.extractors.factory import ExtractorFactory
from app.rag.models import (
    Document,
    DocumentChunk,
    DocumentCollection,
    DocumentType,
    IngestionStatus,
    RAGQueryRequest,
    RAGResponse,
    SourceCitation,
)
from app.rag.router import ModelRouter
from app.rag.store import DocumentStore
from app.rag.vector.faiss_store import FAISSStore

logger = logging.getLogger(__name__)


SYSTEM_PROMPT_RAG = """You are Victor, a hyper-intelligent, precise personal AI assistant.
Answer the user's inquiry based strictly on the retrieved document excerpts provided below.

Strict Grounding Rules:
1. Every factual assertion must be directly supported by the context snippets.
2. If the context does not contain enough information to answer with confidence, clearly state: "Based on the provided document excerpts, I cannot find information regarding [topic]." Do not invent or assume facts.
3. Cite your sources clearly using the provided document names, page numbers, sections, slides, or worksheet names.
4. Keep the tone helpful, articulate, and conversational (address the user naturally as Victor).
"""


class RAGEngine:
    """End-to-end Conversational Document Intelligence and RAG Engine."""

    def __init__(
        self,
        store: Optional[DocumentStore] = None,
        embedding_manager: Optional[HybridEmbeddingManager] = None,
        model_router: Optional[ModelRouter] = None,
        excel_engine: Optional[ExcelIntelligenceEngine] = None,
        vector_storage_dir: Optional[Path | str] = None,
    ):
        self.store = store or DocumentStore()
        self.embedding_manager = embedding_manager or HybridEmbeddingManager()
        self.model_router = model_router or ModelRouter()
        self.excel_engine = excel_engine or ExcelIntelligenceEngine()
        self.vector_storage_dir = Path(vector_storage_dir) if vector_storage_dir else Path("data/vectors")

        self._vector_stores: Dict[str, FAISSStore] = {}
        # Session state: last discussed document / context for follow-up resolution
        self.active_document_id: Optional[str] = None
        self.active_collection_id: str = "default"

    def get_vector_store(self, collection_id: str = "default") -> FAISSStore:
        if collection_id not in self._vector_stores:
            dim = self.embedding_manager.dimension
            self._vector_stores[collection_id] = FAISSStore(
                collection_id=collection_id,
                dimension=dim,
                storage_dir=self.vector_storage_dir,
            )
        return self._vector_stores[collection_id]

    # --- Document Ingestion & Indexing ---

    def ingest_document(
        self,
        file_path: str,
        collection_id: str = "default",
        force_reindex: bool = False,
    ) -> Document:
        """
        Ingests a document file: checks hash idempotency, extracts content,
        generates embeddings, stores chunks in SQLite, and adds vectors to FAISS.
        """
        p = Path(file_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Document file not found: {file_path}")

        # Create or retrieve existing document record
        existing = self.store.find_by_path(str(p))

        # Check hash
        doc = Document.create_new(str(p), collection_id=collection_id)
        if existing and not force_reindex:
            if existing.file_hash == doc.file_hash and existing.status == IngestionStatus.INDEXED:
                logger.info("Document '%s' already indexed with matching hash. Skipping.", p.name)
                self.active_document_id = existing.document_id
                return existing
            else:
                doc.document_id = existing.document_id

        doc.status = IngestionStatus.PROCESSING
        self.store.upsert_document(doc)

        try:
            # 1. Extract content & chunks
            extractor = ExtractorFactory.get_extractor(doc)
            result = extractor.extract(doc)

            if result.error:
                doc.status = IngestionStatus.FAILED
                doc.error_message = result.error
                self.store.upsert_document(doc)
                return doc

            doc.total_pages = result.total_pages
            doc.metadata.update(result.metadata)

            chunks = result.chunks
            if not chunks:
                doc.status = IngestionStatus.INDEXED
                doc.total_chunks = 0
                self.store.upsert_document(doc)
                return doc

            # 2. Generate embeddings
            texts = [c.content for c in chunks]
            vectors = self.embedding_manager.embed_texts(texts)

            # 3. Store in FAISS
            v_store = self.get_vector_store(collection_id)
            chunk_ids = [c.chunk_id for c in chunks]
            assigned_indices = v_store.add_vectors(vectors, chunk_ids, doc.document_id)

            for i, c in enumerate(chunks):
                if i < len(assigned_indices):
                    c.embedding_index = assigned_indices[i]

            # 4. Store chunks in SQLite
            self.store.insert_chunks(chunks)

            doc.status = IngestionStatus.INDEXED
            doc.total_chunks = len(chunks)
            doc.error_message = None
            self.store.upsert_document(doc)
            self.active_document_id = doc.document_id
            logger.info("Successfully ingested document '%s' (%d chunks)", doc.file_name, len(chunks))
            return doc

        except Exception as e:
            logger.error("Failed to ingest document %s: %s", file_path, e, exc_info=True)
            doc.status = IngestionStatus.FAILED
            doc.error_message = str(e)
            self.store.upsert_document(doc)
            return doc

    def delete_document(self, document_id: str) -> bool:
        doc = self.store.get_document(document_id)
        if not doc:
            return False

        # Remove from vector index
        v_store = self.get_vector_store(doc.collection_id)
        v_store.remove_document(document_id)

        # Remove from SQLite
        success = self.store.delete_document(document_id)
        if self.active_document_id == document_id:
            self.active_document_id = None
        return success

    # --- Conversational Query Execution ---

    async def query(self, req: RAGQueryRequest) -> RAGResponse:
        """
        Executes a grounded conversational query against ingested documents.
        Handles contextual follow-ups, deterministic Excel calculations,
        vector retrieval, source citation formatting, and multi-provider generation.
        """
        start_t = time.perf_counter()
        query_text = req.query.strip()
        col_id = req.collection_id or self.active_collection_id

        # 1. Contextual Follow-up Resolution
        target_doc_ids = req.document_ids
        if not target_doc_ids and self.active_document_id:
            # Check if query references "this document", "it", "the file", "the paper", etc.
            ref_keywords = ["this", "that", "the document", "the paper", "the file", "it", "here", "above"]
            if any(k in query_text.lower() for k in ref_keywords):
                target_doc_ids = [self.active_document_id]

        # 2. Check for Excel / Numerical query
        if target_doc_ids and len(target_doc_ids) == 1:
            target_doc = self.store.get_document(target_doc_ids[0])
            if target_doc and target_doc.doc_type in (DocumentType.XLSX, DocumentType.XLS, DocumentType.CSV):
                # Try deterministic numerical execution
                num_res = self.excel_engine.answer_numerical_query(target_doc.file_path, query_text)
                if num_res and "result" in num_res:
                    answer = (
                        f"Sir, based on the calculation performed directly on '{target_doc.file_name}' "
                        f"(Worksheet: '{num_res.get('sheet_name', 'Sheet1')}'):\n"
                        f"- Target Metric: {num_res.get('operation')} of `{num_res.get('target_column')}`\n"
                        f"- Filter: {num_res.get('filter')}\n"
                        f"- Rows Evaluated: {num_res.get('matched_rows')}\n"
                        f"- Calculated Value: **{num_res.get('formatted_result')}**"
                    )
                    cit = SourceCitation(
                        document_id=target_doc.document_id,
                        document_name=target_doc.file_name,
                        snippet=f"{num_res.get('operation')} calculation on column '{num_res.get('target_column')}'",
                        sheet_name=num_res.get("sheet_name"),
                        confidence_score=1.0,
                    )
                    return RAGResponse(
                        query=query_text,
                        answer=answer,
                        citations=[cit],
                        model_used="ExcelIntelligenceEngine (Deterministic)",
                        provider_used="python/pandas",
                        latency_ms=(time.perf_counter() - start_t) * 1000.0,
                        used_excel_engine=True,
                    )

        # 3. Vector Similarity Search
        v_store = self.get_vector_store(col_id)
        if v_store.index.ntotal == 0:
            return RAGResponse(
                query=query_text,
                answer="Sir, no documents have been indexed yet in this collection. Please add documents first.",
                citations=[],
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        query_vec = self.embedding_manager.embed_query(query_text)
        hits = v_store.search(query_vec, top_k=req.top_k, filter_document_ids=target_doc_ids)

        if not hits:
            return RAGResponse(
                query=query_text,
                answer="Sir, I searched the document collection but could not find relevant excerpts matching your query.",
                citations=[],
                latency_ms=(time.perf_counter() - start_t) * 1000.0,
            )

        # 4. Fetch Chunks and Build Context
        context_blocks: List[str] = []
        citations: List[SourceCitation] = []
        doc_cache: Dict[str, Document] = {}

        for chunk_id, score in hits:
            chunk = self.store.get_chunk(chunk_id)
            if not chunk:
                continue

            if chunk.document_id not in doc_cache:
                d = self.store.get_document(chunk.document_id)
                if d:
                    doc_cache[chunk.document_id] = d
            doc = doc_cache.get(chunk.document_id)
            doc_name = doc.file_name if doc else "Document"

            citation = SourceCitation(
                document_id=chunk.document_id,
                document_name=doc_name,
                snippet=chunk.content[:200] + "..." if len(chunk.content) > 200 else chunk.content,
                page_number=chunk.page_number,
                section_title=chunk.section_title,
                sheet_name=chunk.sheet_name,
                cell_range=chunk.cell_range,
                slide_number=chunk.slide_number,
                confidence_score=round(score, 4),
            )
            citations.append(citation)

            # Build contextual snippet
            loc_label = citation.format_citation()
            context_blocks.append(f"--- SOURCE: {loc_label} (Relevance Score: {score:.2f}) ---\n{chunk.content}\n")

        # Update active document if hits are predominantly from one document
        if citations:
            self.active_document_id = citations[0].document_id

        # 5. Build LLM Prompt
        combined_context = "\n".join(context_blocks)
        prompt = (
            f"User Question: {query_text}\n\n"
            f"Retrieved Document Excerpts:\n{combined_context}\n\n"
            f"Please formulate a precise, well-structured answer strictly grounded in the excerpts above. "
            f"Cite the relevant pages, sections, or slides where appropriate."
        )

        gen_result = await self.model_router.generate_response(
            prompt=prompt,
            system_instruction=SYSTEM_PROMPT_RAG,
            temperature=0.1,
        )

        total_lat = (time.perf_counter() - start_t) * 1000.0

        answer_text = gen_result.text
        if gen_result.error and citations:
            answer_text = (
                f"Sir, here are the relevant findings from {citations[0].document_name}:\n\n"
                + "\n\n".join(f"[{c.format_citation()}]:\n{c.snippet}" for c in citations[:3])
            )

        return RAGResponse(
            query=query_text,
            answer=answer_text,
            citations=citations,
            model_used=gen_result.model if not gen_result.error else "Offline Grounded Fallback",
            provider_used=gen_result.provider if not gen_result.error else "victor/local",
            latency_ms=total_lat,
            context_used=context_blocks,
        )

    # --- Document Analysis & Study Helpers ---

    async def summarize_document(self, document_id: str, summary_type: str = "comprehensive") -> RAGResponse:
        """Generates an executive, comprehensive, or bulleted summary of a specific document."""
        doc = self.store.get_document(document_id)
        if not doc:
            return RAGResponse(query="Summarize", answer=f"Document ID {document_id} not found.")

        chunks = self.store.get_chunks_for_document(document_id)
        if not chunks:
            return RAGResponse(query="Summarize", answer=f"No text content found in {doc.file_name}.")

        # Sample key chunks across the document (first, middle, last)
        sample_chunks = chunks[:5] + (chunks[5:-5:max(1, len(chunks) // 10)] if len(chunks) > 10 else []) + chunks[-3:]
        text_sample = "\n\n".join(f"[{c.section_title or 'Section'}]: {c.content}" for c in sample_chunks[:15])

        prompt = (
            f"Document Title: {doc.file_name}\n"
            f"Type: {doc.doc_type.value}\n\n"
            f"Key excerpts:\n{text_sample}\n\n"
            f"Task: Provide a {summary_type} summary of this document. "
            f"Include the main objective, key methodology or points, findings, and conclusion."
        )

        res = await self.model_router.generate_response(
            prompt=prompt,
            system_instruction=SYSTEM_PROMPT_RAG,
            temperature=0.2,
        )

        answer_text = res.text
        if res.error and sample_chunks:
            answer_text = (
                f"Sir, here is a summary from {doc.file_name}:\n\n"
                + "\n\n".join(f"- {c.content[:250]}..." if len(c.content) > 250 else f"- {c.content}" for c in sample_chunks[:4])
            )

        self.active_document_id = document_id
        return RAGResponse(
            query=f"Summarize {doc.file_name}",
            answer=answer_text,
            citations=[SourceCitation(document_id=doc.document_id, document_name=doc.file_name, snippet="Full document overview")],
            model_used=res.model if not res.error else "Offline Extractive Summary",
            provider_used=res.provider if not res.error else "victor/local",
            latency_ms=res.latency_ms,
        )

    async def compare_documents(self, doc_id_1: str, doc_id_2: str) -> RAGResponse:
        """Compares two documents: similarities, differences, methodologies, and conclusions."""
        d1 = self.store.get_document(doc_id_1)
        d2 = self.store.get_document(doc_id_2)
        if not d1 or not d2:
            return RAGResponse(query="Compare", answer="One or both documents could not be found.")

        c1 = self.store.get_chunks_for_document(doc_id_1)[:6]
        c2 = self.store.get_chunks_for_document(doc_id_2)[:6]

        t1 = "\n\n".join(c.content for c in c1)
        t2 = "\n\n".join(c.content for c in c2)

        prompt = (
            f"Document 1: {d1.file_name}\n"
            f"Excerpts:\n{t1}\n\n"
            f"Document 2: {d2.file_name}\n"
            f"Excerpts:\n{t2}\n\n"
            f"Task: Compare these two documents in detail. Highlight:\n"
            f"1. Core objectives & themes\n"
            f"2. Methodologies / Approaches\n"
            f"3. Key Findings & Data Differences\n"
            f"4. Comparative Conclusions"
        )

        res = await self.model_router.generate_response(
            prompt=prompt,
            system_instruction=SYSTEM_PROMPT_RAG,
            temperature=0.2,
        )

        answer_text = res.text
        if res.error and (c1 or c2):
            answer_text = (
                f"Comparison between {d1.file_name} and {d2.file_name}:\n\n"
                f"1. {d1.file_name} Key Findings:\n" + ("\n".join(f"- {c.content[:200]}" for c in c1[:2]) if c1 else "N/A") + "\n\n"
                f"2. {d2.file_name} Key Findings:\n" + ("\n".join(f"- {c.content[:200]}" for c in c2[:2]) if c2 else "N/A")
            )

        return RAGResponse(
            query=f"Compare {d1.file_name} and {d2.file_name}",
            answer=answer_text,
            citations=[
                SourceCitation(document_id=d1.document_id, document_name=d1.file_name, snippet="Document 1 Excerpt"),
                SourceCitation(document_id=d2.document_id, document_name=d2.file_name, snippet="Document 2 Excerpt"),
            ],
            model_used=res.model if not res.error else "Offline Extractive Comparison",
            provider_used=res.provider if not res.error else "victor/local",
            latency_ms=res.latency_ms,
        )

    async def generate_revision_notes(self, document_id: str) -> RAGResponse:
        """Creates structured revision notes, key concepts, formulas, and definitions."""
        doc = self.store.get_document(document_id)
        if not doc:
            return RAGResponse(query="Revision Notes", answer="Document not found.")

        chunks = self.store.get_chunks_for_document(document_id)[:15]
        content = "\n\n".join(f"[{c.section_title or 'Section'}]: {c.content}" for c in chunks)

        prompt = (
            f"Document: {doc.file_name}\n\n"
            f"Content:\n{content}\n\n"
            f"Task: Generate high-yield revision notes from this document:\n"
            f"- Key Definitions & Concepts\n"
            f"- Core Principles / Steps / Formulas\n"
            f"- Crucial Takeaways for quick recall"
        )

        res = await self.model_router.generate_response(
            prompt=prompt,
            system_instruction=SYSTEM_PROMPT_RAG,
            temperature=0.2,
        )

        answer_text = res.text
        if res.error and chunks:
            answer_text = (
                f"# Revision Notes: {doc.file_name}\n\n"
                f"## Key Highlights & High-Yield Summary\n"
                + "\n\n".join(f"- {c.content}" for c in chunks[:5])
            )

        return RAGResponse(
            query=f"Revision notes for {doc.file_name}",
            answer=answer_text,
            citations=[SourceCitation(document_id=doc.document_id, document_name=doc.file_name, snippet="Document revision content")],
            model_used=res.model if not res.error else "Offline High-Yield Notes",
            provider_used=res.provider if not res.error else "victor/local",
            latency_ms=res.latency_ms,
        )
