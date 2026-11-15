"""
Victor Conversational Document Intelligence & RAG Agent — Tool Gateway Tools.

Defines user-facing and Gemini Live callable tools for document reading,
semantic querying, Excel calculations, multi-document comparisons, summaries,
and library management.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.rag.events import broadcast_document_summary, emit_rag_event_sync
from app.rag.models import RAGQueryRequest
from app.rag.path_resolver import resolve_document_path
from app.rag.rag_engine import RAGEngine
from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# Shared engine instance
_shared_rag_engine: Optional[RAGEngine] = None


def get_rag_engine() -> RAGEngine:
    global _shared_rag_engine
    if _shared_rag_engine is None:
        _shared_rag_engine = RAGEngine()
    return _shared_rag_engine


class DocumentReadAndExplainTool(BaseTool):
    name = "document_read_and_explain"
    description = (
        "Ingests or reads a local document (PDF, Word docx, Excel xlsx/xls, PowerPoint pptx, "
        "CSV, TXT, Markdown, or JSON), extracts its structure, and answers questions or "
        "explains its findings, methodology, and conclusions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Full or relative path to the document file on the computer.",
            },
            "question": {
                "type": "string",
                "description": "Specific question to answer about the document. If omitted, Victor explains the main findings and structure.",
            },
            "collection_id": {
                "type": "string",
                "description": "Optional collection identifier (defaults to 'default').",
            },
        },
        "required": ["file_path"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        file_path = args.get("file_path", "").strip()
        question = args.get("question", "").strip()
        collection_id = args.get("collection_id", "default")

        if not file_path:
            return "Please provide a valid file_path or filename to read."

        try:
            # 1. Resolve path intelligently across Downloads, Desktop, Documents, CWD
            resolved_p = resolve_document_path(file_path)
            doc = None
            if resolved_p and resolved_p.exists():
                doc = engine.ingest_document(str(resolved_p), collection_id=collection_id)
            else:
                # Check existing library in store
                all_docs = engine.store.list_documents()
                doc = next((d for d in all_docs if file_path.lower() in d.file_name.lower()), None)
                if not doc:
                    return (
                        f"Sir, I could not find '{file_path}' in your Downloads, Desktop, "
                        f"Documents, or workspace folders. Please specify the exact file location."
                    )

            if doc.status.value == "FAILED":
                return f"Sir, I could not read '{doc.file_name}': {doc.error_message}"

            # 2. Answer question or provide explanation
            if question:
                req = RAGQueryRequest(
                    query=question,
                    collection_id=collection_id,
                    document_ids=[doc.document_id],
                )
                res = await engine.query(req)
                cit_str = "\n".join(f"- {c.format_citation()}" for c in res.citations)
                cit_block = f"\n\n**Sources Cited:**\n{cit_str}" if cit_str else ""
                return f"{res.answer}{cit_block}"
            else:
                summary_res = await engine.summarize_document(doc.document_id, summary_type="comprehensive")
                doc.metadata["latest_summary"] = summary_res.answer
                engine.store.upsert_document(doc)
                await broadcast_document_summary(
                    doc.document_id, doc.file_name, summary_res.answer, summary_type="comprehensive", auto_navigate=True
                )
                return (
                    f"Sir, I have analyzed and indexed '{doc.file_name}' ({doc.total_pages or 1} pages, {doc.total_chunks} chunks). "
                    f"Here is the comprehensive summary:\n\n{summary_res.answer}\n\n"
                    f"I have also updated your Document Intelligence dashboard with this summary."
                )

        except Exception as e:
            logger.error("Error in document_read_and_explain: %s", e, exc_info=True)
            return f"Error reading document: {str(e)}"


class DocumentSearchAndQueryTool(BaseTool):
    name = "document_search_and_query"
    description = (
        "Queries the indexed document library using semantic retrieval and returns "
        "grounded answers with exact citations (page, section, sheet, slide numbers)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Natural language query or question about the documents.",
            },
            "document_name_or_path": {
                "type": "string",
                "description": "Optional document filename or path to narrow the search scope.",
            },
            "collection_id": {
                "type": "string",
                "description": "Optional collection identifier to query.",
            },
            "top_k": {
                "type": "integer",
                "description": "Number of relevant chunks to retrieve (default 5).",
            },
        },
        "required": ["query"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        query = args.get("query", "").strip()
        doc_filter = args.get("document_name_or_path")
        collection_id = args.get("collection_id", "default")
        top_k = args.get("top_k", 5)

        if not query:
            return "Please provide a query."

        target_ids = None
        if doc_filter:
            # Look up matching documents
            all_docs = engine.store.list_documents()
            matched = [
                d.document_id
                for d in all_docs
                if doc_filter.lower() in d.file_name.lower() or doc_filter.lower() in d.file_path.lower()
            ]
            if matched:
                target_ids = matched

        req = RAGQueryRequest(
            query=query,
            collection_id=collection_id,
            document_ids=target_ids,
            top_k=top_k,
        )
        res = await engine.query(req)
        cit_str = "\n".join(f"- {c.format_citation()}" for c in res.citations)
        cit_block = f"\n\n**Sources:**\n{cit_str}" if cit_str else ""
        return f"{res.answer}{cit_block}"


class DocumentCompareTool(BaseTool):
    name = "document_compare"
    description = (
        "Compares two documents (PDF, Word, etc.) side-by-side, analyzing differences "
        "in methodology, results, data, or conclusions."
    )
    parameters = {
        "type": "object",
        "properties": {
            "document_1": {
                "type": "string",
                "description": "Path or filename of the first document.",
            },
            "document_2": {
                "type": "string",
                "description": "Path or filename of the second document.",
            },
        },
        "required": ["document_1", "document_2"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        d1_input = args.get("document_1", "").strip()
        d2_input = args.get("document_2", "").strip()

        # Ingest both if needed
        def _resolve_or_ingest(inp: str):
            p = Path(inp).resolve()
            if p.exists():
                return engine.ingest_document(str(p))
            # Search by name in store
            all_docs = engine.store.list_documents()
            for d in all_docs:
                if inp.lower() in d.file_name.lower():
                    return d
            return None

        doc1 = _resolve_or_ingest(d1_input)
        doc2 = _resolve_or_ingest(d2_input)

        if not doc1:
            return f"Could not find or load document 1: '{d1_input}'"
        if not doc2:
            return f"Could not find or load document 2: '{d2_input}'"

        res = await engine.compare_documents(doc1.document_id, doc2.document_id)
        return res.answer


class DocumentSummarizeTool(BaseTool):
    name = "document_summarize"
    description = "Generates an executive, comprehensive, or bulleted summary of a specific document."
    parameters = {
        "type": "object",
        "properties": {
            "document_name_or_path": {
                "type": "string",
                "description": "Path, filename, or spoken name of the document to summarize.",
            },
            "summary_type": {
                "type": "string",
                "enum": ["comprehensive", "executive", "bullet_points"],
                "description": "Type of summary desired (default: comprehensive).",
            },
        },
        "required": ["document_name_or_path"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        doc_input = args.get("document_name_or_path", "").strip()
        summary_type = args.get("summary_type", "comprehensive")

        resolved_p = resolve_document_path(doc_input)
        if resolved_p and resolved_p.exists():
            doc = engine.ingest_document(str(resolved_p))
        else:
            all_docs = engine.store.list_documents()
            doc = next((d for d in all_docs if doc_input.lower() in d.file_name.lower()), None)

        if not doc:
            return f"Sir, I could not locate '{doc_input}' in your Downloads, Desktop, Documents, or document library."

        res = await engine.summarize_document(doc.document_id, summary_type=summary_type)
        doc.metadata["latest_summary"] = res.answer
        engine.store.upsert_document(doc)
        await broadcast_document_summary(doc.document_id, doc.file_name, res.answer, summary_type=summary_type, auto_navigate=True)
        return (
            f"Sir, here is the {summary_type} summary of '{doc.file_name}':\n\n{res.answer}\n\n"
            f"I have also updated your Document Intelligence dashboard with this summary."
        )


class DocumentRevisionNotesTool(BaseTool):
    name = "document_generate_notes"
    description = "Generates high-yield revision notes, key concepts, formulas, and definitions from a document."
    parameters = {
        "type": "object",
        "properties": {
            "document_name_or_path": {
                "type": "string",
                "description": "Path or filename of the document to create revision notes from.",
            },
        },
        "required": ["document_name_or_path"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        doc_input = args.get("document_name_or_path", "").strip()

        resolved_p = resolve_document_path(doc_input)
        if resolved_p and resolved_p.exists():
            doc = engine.ingest_document(str(resolved_p))
        else:
            all_docs = engine.store.list_documents()
            doc = next((d for d in all_docs if doc_input.lower() in d.file_name.lower()), None)

        if not doc:
            return f"Sir, I could not locate '{doc_input}' in your Downloads, Desktop, Documents, or document library."

        res = await engine.generate_revision_notes(doc.document_id)
        doc.metadata["latest_revision_notes"] = res.answer
        engine.store.upsert_document(doc)
        await broadcast_document_summary(doc.document_id, doc.file_name, res.answer, summary_type="revision_notes", auto_navigate=True)
        return (
            f"Sir, here are the structured revision notes for '{doc.file_name}':\n\n{res.answer}\n\n"
            f"I have loaded these notes into your Study Notes dashboard."
        )


class DocumentVoiceUploadAndSummarizeTool(BaseTool):
    name = "document_voice_upload_and_summarize"
    description = (
        "Locates a document from voice instructions, path, or filename (e.g. 'xyz.pdf in downloads folder', "
        "'report on desktop'), uploads/indexes it, generates a comprehensive summary, displays it on the "
        "Document Intelligence dashboard, and speaks the summary."
    )
    parameters = {
        "type": "object",
        "properties": {
            "document_query_or_path": {
                "type": "string",
                "description": "Spoken description, filename, or path of the document (e.g. 'xyz.pdf in downloads folder', 'quarterly_report.pdf', 'Desktop/notes.docx').",
            },
            "summary_type": {
                "type": "string",
                "enum": ["comprehensive", "executive", "bullet_points"],
                "description": "Type of summary desired (defaults to 'comprehensive').",
            },
            "collection_id": {
                "type": "string",
                "description": "Optional collection identifier (defaults to 'default').",
            },
        },
        "required": ["document_query_or_path"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        query_path = args.get("document_query_or_path", "").strip()
        summary_type = args.get("summary_type", "comprehensive")
        collection_id = args.get("collection_id", "default")

        if not query_path:
            return "Sir, please tell me which document or file path you would like me to analyse."

        # 1. Resolve path
        resolved_p = resolve_document_path(query_path)
        doc = None
        if resolved_p and resolved_p.exists():
            doc = engine.ingest_document(str(resolved_p), collection_id=collection_id)
        else:
            # Check existing library
            all_docs = engine.store.list_documents()
            doc = next((d for d in all_docs if query_path.lower() in d.file_name.lower()), None)
            if not doc:
                return (
                    f"Sir, I searched your Downloads, Desktop, Documents, and workspace folders, "
                    f"but could not find '{query_path}'. Please check the filename or provide the full path."
                )

        if doc.status.value == "FAILED":
            return f"Sir, I encountered an issue reading '{doc.file_name}': {doc.error_message}"

        # 2. Generate summary
        res = await engine.summarize_document(doc.document_id, summary_type=summary_type)
        doc.metadata["latest_summary"] = res.answer
        engine.store.upsert_document(doc)

        # 3. Broadcast to dashboard UI
        await broadcast_document_summary(
            doc.document_id, doc.file_name, res.answer, summary_type=summary_type, auto_navigate=True
        )

        # 4. Spoken response for Gemini Live / TTS
        return (
            f"Sir, I have located and indexed '{doc.file_name}' ({doc.total_pages or 1} pages, {doc.total_chunks} chunks). "
            f"Here is the {summary_type} summary:\n\n{res.answer}\n\n"
            f"The full summary is now displayed on your Document Intelligence dashboard."
        )

        res = await engine.generate_revision_notes(doc.document_id)
        return res.answer


class DocumentExcelQueryTool(BaseTool):
    name = "document_excel_query"
    description = (
        "Performs deterministic numerical calculations on an Excel workbook (.xlsx, .xls) "
        "or CSV file (e.g. sum, average, min, max, row count, filtered category sums) "
        "without LLM hallucination."
    )
    parameters = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Full or relative path to the Excel (.xlsx/.xls) or CSV file.",
            },
            "question": {
                "type": "string",
                "description": "Calculation instruction or question (e.g. 'total expenditure', 'average sales in Q3').",
            },
            "sheet_name": {
                "type": "string",
                "description": "Optional worksheet name.",
            },
        },
        "required": ["file_path", "question"],
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        file_path = args.get("file_path", "").strip()
        question = args.get("question", "").strip()
        sheet_name = args.get("sheet_name")

        p = Path(file_path).resolve()
        if not p.exists():
            return f"File not found: '{file_path}'"

        # Check structure first
        struct = engine.excel_engine.get_structure(str(p))
        if "error" in struct:
            return f"Error reading Excel/CSV: {struct['error']}"

        # Answer numerical query
        num_res = engine.excel_engine.answer_numerical_query(str(p), question)
        if num_res and "result" in num_res:
            return (
                f"Sir, based on direct calculation on '{p.name}' (Sheet: '{num_res.get('sheet_name', 'Sheet1')}'):\n"
                f"- Operation: {num_res.get('operation')} on `{num_res.get('target_column')}`\n"
                f"- Filter: {num_res.get('filter')}\n"
                f"- Rows Evaluated: {num_res.get('matched_rows')}\n"
                f"- Calculated Result: **{num_res.get('formatted_result')}**"
            )

        # Fallback to metrics summary
        summary = engine.excel_engine.compute_summary_metrics(str(p), sheet_name=sheet_name)
        if "metrics" in summary:
            lines = [f"Summary metrics for '{p.name}' (Sheet: {summary.get('sheet_name')}):"]
            for col, m in summary["metrics"].items():
                lines.append(f"- {col}: Sum = {m['sum']:,.2f}, Avg = {m['mean']:,.2f}, Min = {m['min']:,.2f}, Max = {m['max']:,.2f}")
            return "\n".join(lines)

        return f"Could not perform calculation on '{p.name}'."


class DocumentListLibraryTool(BaseTool):
    name = "document_list_library"
    description = "Lists all documents currently indexed in Victor's document intelligence library."
    parameters = {
        "type": "object",
        "properties": {
            "collection_id": {
                "type": "string",
                "description": "Optional collection filter.",
            },
        },
    }

    async def execute(self, args: dict) -> str:
        engine = get_rag_engine()
        col_id = args.get("collection_id")
        docs = engine.store.list_documents(col_id)

        if not docs:
            return "Sir, no documents are currently indexed in your document library."

        lines = [f"Sir, you have {len(docs)} document(s) in your library:"]
        for d in docs:
            pages = f"{d.total_pages} page(s)" if d.total_pages else "N/A"
            lines.append(f"- **{d.file_name}** ({d.doc_type.value}, {pages}, {d.total_chunks} chunks, Status: {d.status.value})")
        return "\n".join(lines)
