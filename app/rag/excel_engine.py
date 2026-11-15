"""
Victor Conversational Document Intelligence & RAG Agent — Excel Intelligence Engine.

Performs deterministic numerical calculations, aggregations, statistical summaries,
and formula executions on Excel spreadsheets (.xlsx, .xls) and CSV files.
Prevents LLM numerical hallucinations by using real pandas/python execution.
"""

from __future__ import annotations

import logging
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple

import openpyxl
import pandas as pd

logger = logging.getLogger(__name__)


class ExcelIntelligenceEngine:
    """Deterministic calculation and query engine for Excel and CSV files."""

    def __init__(self):
        pass

    def get_structure(self, file_path: str) -> Dict[str, Any]:
        """Returns sheets, columns, dtypes, and basic stats for each sheet."""
        p = Path(file_path).resolve()
        if not p.exists():
            return {"error": f"File not found: {file_path}"}

        structure: Dict[str, Any] = {
            "file_name": p.name,
            "sheets": {},
        }

        try:
            if p.suffix.lower() == ".csv":
                df = pd.read_csv(p)
                structure["sheets"]["Sheet1"] = self._analyze_dataframe(df)
            else:
                excel_file = pd.ExcelFile(p)
                for sheet in excel_file.sheet_names:
                    df = pd.read_excel(excel_file, sheet_name=sheet)
                    structure["sheets"][sheet] = self._analyze_dataframe(df)
                excel_file.close()

            return structure
        except Exception as e:
            logger.error("Error reading structure of %s: %s", file_path, e, exc_info=True)
            return {"error": str(e)}

    def _analyze_dataframe(self, df: pd.DataFrame) -> Dict[str, Any]:
        """Analyzes a dataframe for columns, row count, and numerical summaries."""
        rows, cols = df.shape
        columns_info = {}
        numerical_cols = []

        for col in df.columns:
            col_name = str(col)
            dtype_str = str(df[col].dtype)
            is_num = pd.api.types.is_numeric_dtype(df[col])
            info: Dict[str, Any] = {
                "dtype": dtype_str,
                "null_count": int(df[col].isna().sum()),
                "is_numeric": is_num,
            }
            if is_num:
                numerical_cols.append(col_name)
                s = df[col].dropna()
                if not s.empty:
                    info["sum"] = float(s.sum())
                    info["mean"] = float(s.mean())
                    info["min"] = float(s.min())
                    info["max"] = float(s.max())
                    info["count"] = int(len(s))

            columns_info[col_name] = info

        return {
            "row_count": rows,
            "col_count": cols,
            "columns": list(columns_info.keys()),
            "column_details": columns_info,
            "numerical_columns": numerical_cols,
        }

    def compute_summary_metrics(self, file_path: str, sheet_name: Optional[str] = None) -> Dict[str, Any]:
        """Computes all standard aggregations (sums, averages, min, max) for numerical columns."""
        p = Path(file_path).resolve()
        try:
            if p.suffix.lower() == ".csv":
                df = pd.read_csv(p)
                actual_sheet = "Sheet1"
            else:
                excel_file = pd.ExcelFile(p)
                actual_sheet = sheet_name or excel_file.sheet_names[0]
                df = pd.read_excel(excel_file, sheet_name=actual_sheet)
                excel_file.close()

            num_df = df.select_dtypes(include=["number"])
            metrics: Dict[str, Dict[str, float]] = {}

            for col in num_df.columns:
                series = num_df[col].dropna()
                if not series.empty:
                    metrics[str(col)] = {
                        "sum": float(series.sum()),
                        "mean": float(series.mean()),
                        "median": float(series.median()),
                        "min": float(series.min()),
                        "max": float(series.max()),
                        "count": float(len(series)),
                        "std": float(series.std()) if len(series) > 1 else 0.0,
                    }

            return {
                "file_name": p.name,
                "sheet_name": actual_sheet,
                "total_rows": len(df),
                "metrics": metrics,
            }
        except Exception as e:
            return {"error": str(e)}

    def execute_filtered_aggregation(
        self,
        file_path: str,
        target_column: str,
        aggregation: str = "sum",
        filter_column: Optional[str] = None,
        filter_value: Optional[Any] = None,
        sheet_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Executes a deterministic aggregation with optional filtering.
        aggregation: 'sum', 'mean', 'avg', 'min', 'max', 'count'
        """
        p = Path(file_path).resolve()
        try:
            if p.suffix.lower() == ".csv":
                df = pd.read_csv(p)
                actual_sheet = "Sheet1"
            else:
                excel_file = pd.ExcelFile(p)
                actual_sheet = sheet_name or excel_file.sheet_names[0]
                df = pd.read_excel(excel_file, sheet_name=actual_sheet)
                excel_file.close()

            # Find matching target column (case-insensitive)
            matched_target = None
            for c in df.columns:
                if str(c).strip().lower() == target_column.strip().lower():
                    matched_target = c
                    break

            if matched_target is None:
                # Substring match
                for c in df.columns:
                    if target_column.strip().lower() in str(c).strip().lower():
                        matched_target = c
                        break

            if matched_target is None:
                return {
                    "error": f"Column '{target_column}' not found. Available columns: {list(df.columns)}"
                }

            # Filter if requested
            filtered_df = df
            filter_description = "None"
            if filter_column and filter_value is not None:
                matched_filter = None
                for c in df.columns:
                    if str(c).strip().lower() == filter_column.strip().lower():
                        matched_filter = c
                        break
                if matched_filter:
                    # String or exact match
                    if isinstance(filter_value, str):
                        mask = filtered_df[matched_filter].astype(str).str.contains(filter_value, case=False, na=False)
                    else:
                        mask = filtered_df[matched_filter] == filter_value
                    filtered_df = filtered_df[mask]
                    filter_description = f"{matched_filter} == '{filter_value}'"

            series = pd.to_numeric(filtered_df[matched_target], errors="coerce").dropna()

            agg_op = aggregation.lower()
            if agg_op in ("sum", "total"):
                val = float(series.sum())
                op_name = "Sum"
            elif agg_op in ("mean", "avg", "average"):
                val = float(series.mean()) if not series.empty else 0.0
                op_name = "Average"
            elif agg_op in ("min", "minimum", "lowest"):
                val = float(series.min()) if not series.empty else 0.0
                op_name = "Minimum"
            elif agg_op in ("max", "maximum", "highest"):
                val = float(series.max()) if not series.empty else 0.0
                op_name = "Maximum"
            elif agg_op in ("count", "rows"):
                val = float(len(series))
                op_name = "Count"
            else:
                return {"error": f"Unsupported aggregation '{aggregation}'"}

            return {
                "file_name": p.name,
                "sheet_name": actual_sheet,
                "target_column": str(matched_target),
                "operation": op_name,
                "filter": filter_description,
                "matched_rows": len(series),
                "result": val,
                "formatted_result": f"{val:,.2f}" if abs(val) >= 1 else f"{val:.4f}",
            }
        except Exception as e:
            logger.error("Failed to execute filtered aggregation: %s", e, exc_info=True)
            return {"error": str(e)}

    def answer_numerical_query(self, file_path: str, question: str) -> Optional[Dict[str, Any]]:
        """
        Attempts to heuristically answer common natural-language numerical questions
        (e.g., 'total expenditure', 'highest sale', 'average revenue') deterministically.
        """
        q = question.lower()
        struct = self.get_structure(file_path)
        if "error" in struct or not struct.get("sheets"):
            return None

        # Determine target aggregation (priority: extrema -> averages -> counts -> totals)
        agg = None
        if any(w in q for w in ["highest", "max", "maximum", "most", "peak", "largest", "greatest"]):
            agg = "max"
        elif any(w in q for w in ["lowest", "min", "minimum", "least", "smallest"]):
            agg = "min"
        elif any(w in q for w in ["average", "mean", "avg"]):
            agg = "mean"
        elif any(w in q for w in ["how many", "count", "number of rows"]):
            agg = "count"
        elif any(w in q for w in ["total", "sum", "overall", "expenditure", "spending", "spent", "cost", "revenue"]):
            agg = "sum"

        if not agg:
            return None

        # Search across all sheets for numerical columns matching question keywords
        for sheet_name, sheet_info in struct["sheets"].items():
            num_cols = sheet_info.get("numerical_columns", [])
            for col in num_cols:
                col_clean = str(col).lower()
                # Check if column name keywords overlap with question
                col_words = [w for w in re.split(r"[_\s]+", col_clean) if len(w) > 2]
                if any(w in q for w in col_words) or ("expenditure" in q and "amount" in col_clean) or ("sale" in q and "sale" in col_clean):
                    res = self.execute_filtered_aggregation(
                        file_path=file_path,
                        target_column=col,
                        aggregation=agg,
                        sheet_name=sheet_name,
                    )
                    if "result" in res:
                        return res

        return None
