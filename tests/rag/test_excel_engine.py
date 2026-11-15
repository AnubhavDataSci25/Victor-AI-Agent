"""
Unit tests for Victor Excel Intelligence Engine.

Tests deterministic numerical calculations, formula aggregations, and query answering.
"""

from pathlib import Path
import tempfile
import openpyxl
import pytest

from app.rag.excel_engine import ExcelIntelligenceEngine


@pytest.fixture
def sample_workbook():
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "finances.xlsx"
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Transactions"
        ws.append(["Transaction_ID", "Category", "Amount", "Status"])
        ws.append(["T001", "Food", 450.0, "Completed"])
        ws.append(["T002", "Travel", 1200.0, "Completed"])
        ws.append(["T003", "Food", 600.0, "Completed"])
        ws.append(["T004", "Shopping", 3500.0, "Pending"])
        ws.append(["T005", "Utilities", 1800.0, "Completed"])
        wb.save(str(p))
        wb.close()
        yield str(p)


def test_excel_structure(sample_workbook):
    engine = ExcelIntelligenceEngine()
    struct = engine.get_structure(sample_workbook)

    assert "error" not in struct
    assert "Transactions" in struct["sheets"]
    details = struct["sheets"]["Transactions"]
    assert details["row_count"] == 5
    assert "Amount" in details["numerical_columns"]


def test_excel_summary_metrics(sample_workbook):
    engine = ExcelIntelligenceEngine()
    metrics = engine.compute_summary_metrics(sample_workbook)

    assert "metrics" in metrics
    amt = metrics["metrics"]["Amount"]
    assert amt["sum"] == 450.0 + 1200.0 + 600.0 + 3500.0 + 1800.0  # 7550.0
    assert amt["count"] == 5
    assert amt["min"] == 450.0
    assert amt["max"] == 3500.0


def test_filtered_aggregation(sample_workbook):
    engine = ExcelIntelligenceEngine()
    # Sum of Amount where Category is Food
    res = engine.execute_filtered_aggregation(
        file_path=sample_workbook,
        target_column="Amount",
        aggregation="sum",
        filter_column="Category",
        filter_value="Food",
    )

    assert "result" in res
    assert res["result"] == 1050.0  # 450 + 600
    assert res["matched_rows"] == 2


def test_natural_language_query_answering(sample_workbook):
    engine = ExcelIntelligenceEngine()

    # Query: Total expenditure
    res = engine.answer_numerical_query(sample_workbook, "What is the total expenditure?")
    assert res is not None
    assert res["result"] == 7550.0
    assert res["operation"] == "Sum"

    # Query: Highest amount
    res_max = engine.answer_numerical_query(sample_workbook, "What was the highest amount spent?")
    assert res_max is not None
    assert res_max["result"] == 3500.0
    assert res_max["operation"] == "Maximum"
