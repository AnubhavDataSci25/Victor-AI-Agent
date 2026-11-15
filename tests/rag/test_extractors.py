"""
Unit tests for Victor Document Extractors.

Tests structure-aware extraction for PDF, DOCX, XLSX, PPTX, CSV, TXT, MD, and JSON.
"""

import json
from pathlib import Path
import tempfile
import pytest

from app.rag.extractors.factory import ExtractorFactory
from app.rag.models import Document, DocumentType


@pytest.fixture
def temp_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


def test_text_and_md_extraction(temp_dir):
    txt_file = temp_dir / "sample.txt"
    txt_file.write_text("Hello Victor. This is a document intelligence test.", encoding="utf-8")

    doc = Document.create_new(str(txt_file))
    extractor = ExtractorFactory.get_extractor(doc)
    res = extractor.extract(doc)

    assert res.error is None
    assert len(res.chunks) >= 1
    assert "Hello Victor" in res.chunks[0].content

    # Markdown with headings
    md_file = temp_dir / "notes.md"
    md_file.write_text("# Chapter 1\nThis is section 1.\n\n# Chapter 2\nThis is section 2.", encoding="utf-8")

    md_doc = Document.create_new(str(md_file))
    md_extractor = ExtractorFactory.get_extractor(md_doc)
    md_res = md_extractor.extract(md_doc)

    assert md_res.error is None
    assert len(md_res.chunks) >= 1


def test_csv_extraction(temp_dir):
    csv_file = temp_dir / "sales.csv"
    csv_file.write_text("item,price,quantity\nApple,10.5,5\nBanana,5.0,10\nOrange,8.2,3\n", encoding="utf-8")

    doc = Document.create_new(str(csv_file))
    extractor = ExtractorFactory.get_extractor(doc)
    res = extractor.extract(doc)

    assert res.error is None
    assert res.metadata["row_count"] == 3
    assert "item" in res.metadata["columns"]
    assert len(res.chunks) >= 1


def test_json_extraction(temp_dir):
    json_file = temp_dir / "config.json"
    data = {"system": "Victor", "features": ["rag", "finance", "vision"], "active": True}
    json_file.write_text(json.dumps(data), encoding="utf-8")

    doc = Document.create_new(str(json_file))
    extractor = ExtractorFactory.get_extractor(doc)
    res = extractor.extract(doc)

    assert res.error is None
    assert "Victor" in res.chunks[0].content


def test_excel_extraction(temp_dir):
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Expenses"
    ws.append(["Category", "Amount", "Month"])
    ws.append(["Food", 1200, "Nov"])
    ws.append(["Travel", 800, "Nov"])
    ws.append(["Utilities", 1500, "Nov"])

    xlsx_path = temp_dir / "budget.xlsx"
    wb.save(str(xlsx_path))
    wb.close()

    doc = Document.create_new(str(xlsx_path))
    extractor = ExtractorFactory.get_extractor(doc)
    res = extractor.extract(doc)

    assert res.error is None
    assert res.metadata["sheet_count"] == 1
    assert "Expenses" in res.metadata["sheets"]
    assert len(res.chunks) >= 1
    assert "1,200.00" in res.chunks[0].content or "1200" in res.chunks[0].content


def test_docx_extraction(temp_dir):
    import docx

    d = docx.Document()
    d.add_heading("Research Findings", level=1)
    d.add_paragraph("We evaluated stroke prediction models using machine learning techniques.")
    d.add_heading("Methodology", level=2)
    d.add_paragraph("Logistic regression and Random Forest were benchmarked.")

    docx_path = temp_dir / "paper.docx"
    d.save(str(docx_path))

    doc = Document.create_new(str(docx_path))
    extractor = ExtractorFactory.get_extractor(doc)
    res = extractor.extract(doc)

    assert res.error is None
    assert len(res.chunks) >= 1
    sections = [c.section_title for c in res.chunks if c.section_title]
    assert any("Methodology" in s or "Research" in s for s in sections)


def test_pptx_extraction(temp_dir):
    from pptx import Presentation

    prs = Presentation()
    slide_layout = prs.slide_layouts[0]
    slide = prs.slides.add_slide(slide_layout)
    title = slide.shapes.title
    subtitle = slide.placeholders[1]
    title.text = "Victor AI Agent"
    subtitle.text = "Document Intelligence Presentation"

    pptx_path = temp_dir / "slides.pptx"
    prs.save(str(pptx_path))

    doc = Document.create_new(str(pptx_path))
    extractor = ExtractorFactory.get_extractor(doc)
    res = extractor.extract(doc)

    assert res.error is None
    assert res.metadata["slide_count"] == 1
    assert len(res.chunks) >= 1
    assert "Victor AI Agent" in res.chunks[0].content
