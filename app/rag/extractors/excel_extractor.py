"""
Victor Conversational Document Intelligence & RAG Agent — Excel (XLSX, XLS) Extractor.

Extracts worksheets, cell structures, dimensions, formulas, data types, and summaries
from Excel workbooks using openpyxl and pandas.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import openpyxl
import pandas as pd

from app.rag.extractors.base import BaseExtractor
from app.rag.models import Document, DocumentChunk, ExtractionResult

logger = logging.getLogger(__name__)


class ExcelExtractor(BaseExtractor):
    """Structure-aware Excel (.xlsx, .xls) extractor."""

    def extract(self, document: Document) -> ExtractionResult:
        file_path = Path(document.file_path)
        if not file_path.exists():
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"File not found: {document.file_path}",
            )

        try:
            wb = openpyxl.load_workbook(str(file_path), data_only=True, read_only=True)
            sheet_names = wb.sheetnames
            wb.close()

            meta: Dict[str, Any] = {
                "title": file_path.name,
                "sheet_count": len(sheet_names),
                "sheets": sheet_names,
            }

            chunks: List[DocumentChunk] = []
            chunk_idx = 0
            total_text_length = 0

            # Inspect each sheet with pandas
            excel_file = pd.ExcelFile(str(file_path))

            for sheet_name in sheet_names:
                try:
                    df = pd.read_excel(excel_file, sheet_name=sheet_name)
                except Exception as se:
                    logger.warning("Could not parse sheet %s: %s", sheet_name, se)
                    continue

                if df.empty:
                    continue

                rows, cols = df.shape
                col_names = [str(c) for c in df.columns]

                sheet_summary = [
                    f"Worksheet: '{sheet_name}' in {file_path.name}",
                    f"Dimensions: {rows} rows x {cols} columns",
                    f"Columns: {', '.join(col_names)}",
                ]

                # Statistical summary of numerical columns
                num_df = df.select_dtypes(include=["number"])
                if not num_df.empty:
                    sheet_summary.append("\nNumerical Column Summaries:")
                    for col in num_df.columns:
                        col_series = num_df[col].dropna()
                        if not col_series.empty:
                            sheet_summary.append(
                                f"- {col}: Sum = {col_series.sum():,.2f}, Mean = {col_series.mean():,.2f}, "
                                f"Min = {col_series.min():,.2f}, Max = {col_series.max():,.2f}, Count = {len(col_series)}"
                            )

                # Sample data (first 30 rows)
                sample_preview = df.head(30).to_markdown(index=False)
                sheet_summary.append(f"\nSample Rows (1-{min(30, rows)}):\n{sample_preview}")

                sheet_text = "\n".join(sheet_summary)
                total_text_length += len(sheet_text)

                sheet_chunks = self.chunk_text(
                    text=sheet_text,
                    document_id=document.document_id,
                    start_index=chunk_idx,
                    sheet_name=sheet_name,
                    section_title=f"Worksheet '{sheet_name}'",
                    extra_metadata={
                        "sheet_name": sheet_name,
                        "rows": rows,
                        "columns": cols,
                        "col_names": col_names,
                    },
                )
                chunks.extend(sheet_chunks)
                chunk_idx += len(sheet_chunks)

            excel_file.close()

            return ExtractionResult(
                document_id=document.document_id,
                chunks=chunks,
                metadata=meta,
                raw_text_length=total_text_length,
                total_pages=len(sheet_names),
            )

        except Exception as e:
            logger.error("Failed to extract Excel %s: %s", document.file_path, e, exc_info=True)
            return ExtractionResult(
                document_id=document.document_id,
                chunks=[],
                error=f"Excel extraction error: {str(e)}",
            )
