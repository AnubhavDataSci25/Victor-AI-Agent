"""
Victor Personal Finance, Expense & Bill Management Agent — Receipt & Invoice Intelligence.

Extracts structured financial details (merchant, date, total amount, taxes/GST, line items,
payment method, suggested category) from receipts and PDF invoices using OCR / vision
and deterministic deduplication.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
from pathlib import Path
import re
from typing import Any, Optional, Tuple

from google import genai
from google.genai import types
from PIL import Image

from app.finance.models import DEFAULT_CATEGORIES, ReceiptScanResult
from app.finance.store import FinanceStore

logger = logging.getLogger(__name__)


class ReceiptProcessor:
    def __init__(self, store: Optional[FinanceStore] = None, model_name: Optional[str] = None) -> None:
        self.store = store or FinanceStore()
        self.model_name = model_name or os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
        self._client: Optional[genai.Client] = None

    def _get_client(self) -> genai.Client:
        if self._client is None:
            api_key = os.getenv("GEMINI_API_KEY")
            if api_key:
                self._client = genai.Client(api_key=api_key)
            else:
                self._client = genai.Client()
        return self._client

    @staticmethod
    def compute_file_hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    async def process_receipt_file(
        self,
        file_path_or_bytes: str | Path | bytes,
        filename: Optional[str] = None,
    ) -> ReceiptScanResult:
        """
        Processes a receipt image (JPEG, PNG, WebP) or PDF file.
        Detects duplicates and extracts merchant, amounts, items, and tax info.
        """
        raw_bytes: bytes
        ext: str = ""

        if isinstance(file_path_or_bytes, (str, Path)):
            p = Path(file_path_or_bytes)
            if not p.exists():
                return ReceiptScanResult(
                    raw_text=f"File not found: {p}",
                    confidence=0.0,
                    duplicate_reason="File not found",
                )
            raw_bytes = p.read_bytes()
            ext = p.suffix.lower()
        else:
            raw_bytes = file_path_or_bytes
            ext = Path(filename).suffix.lower() if filename else ".jpg"

        file_hash = self.compute_file_hash(raw_bytes)

        # Step 1: Instant duplicate check by byte hash
        dup = self.store.check_duplicate_receipt(file_hash=file_hash)
        if dup:
            return ReceiptScanResult(
                merchant=dup["receipt"].get("merchant"),
                invoice_number=dup["receipt"].get("invoice_number"),
                invoice_date=dup["receipt"].get("invoice_date"),
                total_amount=dup["receipt"].get("amount"),
                confidence=1.0,
                is_duplicate=True,
                duplicate_reason=dup["reason"],
            )

        # Step 2: Determine MIME type
        mime_type = "application/pdf" if ext == ".pdf" else "image/jpeg"
        if mime_type != "application/pdf":
            # Normalize image to clean JPEG bytes
            try:
                with Image.open(io.BytesIO(raw_bytes)) as img:
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=85)
                    raw_bytes = buf.getvalue()
                    mime_type = "image/jpeg"
            except Exception as e:
                logger.warning(f"[ReceiptProcessor] Image normalization warning: {e}")

        # Step 3: Extract structured receipt data using Gemini Vision / Document understanding
        structured_data, raw_ocr_text = await self._extract_with_gemini(raw_bytes, mime_type)

        # Step 4: Map and validate fields deterministically
        merchant = structured_data.get("merchant") or "Unknown Merchant"
        invoice_num = structured_data.get("invoice_number")
        invoice_date = structured_data.get("invoice_date") or None
        total_amount = structured_data.get("total_amount")
        currency = structured_data.get("currency") or "INR"
        tax_or_gst = structured_data.get("tax_or_gst")
        items = structured_data.get("items") or []
        payment_method = structured_data.get("payment_method") or "UPI"
        suggested_category = self._normalize_category(structured_data.get("suggested_category"))

        try:
            total_float = float(total_amount) if total_amount is not None else None
            if total_float is not None and total_float < 0:
                total_float = abs(total_float)
        except (ValueError, TypeError):
            total_float = None

        confidence = 0.95 if (total_float and merchant != "Unknown Merchant") else 0.50

        # Step 5: Duplicate check by invoice number or merchant+date+amount
        dup_record = self.store.check_duplicate_receipt(
            invoice_number=invoice_num,
            merchant=merchant,
            amount=total_float,
            date=invoice_date,
        )
        is_dup = False
        dup_reason = None
        if dup_record:
            is_dup = True
            dup_reason = dup_record["reason"]

        result = ReceiptScanResult(
            merchant=merchant,
            invoice_number=invoice_num,
            invoice_date=invoice_date,
            total_amount=total_float,
            currency=currency,
            tax_or_gst=float(tax_or_gst) if tax_or_gst is not None else None,
            items=items,
            payment_method=payment_method,
            suggested_category=suggested_category,
            confidence=confidence,
            raw_text=raw_ocr_text,
            is_duplicate=is_dup,
            duplicate_reason=dup_reason,
        )

        return result

    async def _extract_with_gemini(self, data: bytes, mime_type: str) -> Tuple[dict[str, Any], str]:
        prompt = (
            "You are Victor's high-precision receipt, bill, and invoice analysis engine.\n"
            "Analyze this document/image and extract the following financial fields into a strictly valid JSON object:\n"
            "{\n"
            '  "merchant": "Business or store name (e.g. Swiggy, Amazon, Reliance Fresh, BESCOM, Airtel)",\n'
            '  "invoice_number": "Invoice, order, or receipt ID if present, else null",\n'
            '  "invoice_date": "Date of transaction formatted as YYYY-MM-DD if found, else null",\n'
            '  "total_amount": 123.45,\n'
            '  "currency": "INR",\n'
            '  "tax_or_gst": 18.00,\n'
            '  "items": [{"name": "Item description", "quantity": 1, "price": 100.0}],\n'
            '  "payment_method": "UPI, Credit Card, Cash, or NetBanking if identifiable, else null",\n'
            '  "suggested_category": "One of [Food, Shopping, Travel, Education, Healthcare, Bills, Rent, Utilities, Entertainment, Subscriptions, Personal Care, Electronics, Investments, Others]"\n'
            "}\n"
            "Requirements:\n"
            "1. Extract the actual final payable total amount as a number.\n"
            "2. Never hallucinate amounts or merchant names.\n"
            "3. Output ONLY the JSON object, with no markdown code fences or conversational text."
        )

        try:
            client = self._get_client()
            doc_part = types.Part.from_bytes(data=data, mime_type=mime_type)
            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=[doc_part, prompt],
            )
            raw_text = (response.text or "").strip()
            # Clean markdown codeblocks if model wraps output
            cleaned = re.sub(r"^```(?:json)?\s*", "", raw_text)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            data_json = json.loads(cleaned)
            return data_json, raw_text
        except Exception as e:
            logger.warning(f"[ReceiptProcessor] Gemini extraction error: {e}. Falling back to regex.")
            # Regex heuristic fallback
            return self._regex_heuristic_fallback(str(data[:2000]))

    def _regex_heuristic_fallback(self, text: str) -> Tuple[dict[str, Any], str]:
        # Fallback heuristic parser for offline/mock environments
        amount_match = re.search(r"(?:total|grand total|amount|rs\.?|inr|₹)\s*[:=]?\s*([0-9,]+(?:\.[0-9]{1,2})?)", text, re.I)
        total_amount = float(amount_match.group(1).replace(",", "")) if amount_match else None

        date_match = re.search(r"(\d{4}-\d{2}-\d{2}|\d{2}/\d{2}/\d{4})", text)
        invoice_date = date_match.group(1) if date_match else None

        inv_match = re.search(r"(?:invoice|receipt|order)\s*(?:#|no\.?|id)?\s*[:=]?\s*([A-Za-z0-9\-]+)", text, re.I)
        invoice_num = inv_match.group(1) if inv_match else None

        return {
            "merchant": "Scanned Merchant",
            "invoice_number": invoice_num,
            "invoice_date": invoice_date,
            "total_amount": total_amount,
            "currency": "INR",
            "tax_or_gst": None,
            "items": [],
            "payment_method": "UPI",
            "suggested_category": "Shopping",
        }, text

    @staticmethod
    def _normalize_category(cat: Optional[str]) -> str:
        if not cat:
            return "Others"
        for standard in DEFAULT_CATEGORIES:
            if standard.lower() == cat.strip().lower():
                return standard
        return cat.strip().title()
