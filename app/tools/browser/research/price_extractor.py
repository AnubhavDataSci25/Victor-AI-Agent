"""
Price extractor and normalizer for Browser Research Agent.
Extracts selling price, MRP, EMI, conditional discounts, and stock availability.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple
from app.tools.browser.research.models import PriceDetail


class PriceExtractor:
    """Extracts and normalizes product pricing, distinguishing unconditional, conditional, and EMI figures."""

    @classmethod
    def parse_price(cls, text: str, html: Optional[str] = None) -> PriceDetail:
        """Analyze text and optional HTML snippet to construct an accurate PriceDetail record."""
        clean_text = text or ""
        detail = PriceDetail()

        # 1. Detect and isolate EMI installments to avoid corrupting product prices
        emi_patterns = [
            r"(?:EMI|monthly|installment)\s*(?:from|starts? at)?\s*(?:₹|Rs\.?|INR)?\s*([\d,]{3,6})(?:\s*/\s*(?:month|mo)|per\s*month)?",
            r"(?:₹|Rs\.?|INR)?\s*([\d,]{3,6})\s*/\s*(?:month|mo)",
        ]
        for pat in emi_patterns:
            emi_match = re.search(pat, clean_text, re.IGNORECASE)
            if emi_match:
                try:
                    detail.emi_per_month = float(emi_match.group(1).replace(",", ""))
                except ValueError:
                    pass

        # 2. Identify discount/cashback/bonus/exchange amounts to avoid treating them as product selling price
        discount_amounts: set[float] = set()
        discount_patterns = [
            r"(?:discount|off|cashback|bonus|save|savings|coupon|exchange)\s*(?:of|up to|worth)?\s*(?:₹|Rs\.?|INR)?\s*([\d,]{3,6})",
            r"(?:₹|Rs\.?|INR)\s*([\d,]{3,6})\s*(?:Instant\s+)?(?:discount|off|cashback|bonus|savings|coupon)",
        ]
        for pat in discount_patterns:
            for dm in re.finditer(pat, clean_text, re.IGNORECASE):
                try:
                    discount_amounts.add(float(dm.group(1).replace(",", "")))
                except ValueError:
                    pass

        # 3. Check for explicit price indicators (e.g. Price: ₹59,990, Deal Price: ₹62,490)
        explicit_price: Optional[float] = None
        explicit_match = re.search(
            r"(?:Price|Our Price|Deal Price|Special Price|Selling Price|Offer Price)\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]{4,8})",
            clean_text,
            re.IGNORECASE,
        )
        if explicit_match:
            try:
                explicit_price = float(explicit_match.group(1).replace(",", ""))
            except ValueError:
                pass

        # 4. Extract potential price numbers (e.g. ₹59,999, Rs. 62,490, INR 74,990)
        price_patterns = [
            r"(?:₹|Rs\.?|INR)\s*([\d,]{4,8})(?:\.\d{2})?",
            r"\b([\d,]{4,8})\s*(?:₹|Rs\.?|INR)",
        ]

        found_prices: List[float] = []
        for pat in price_patterns:
            for m in re.finditer(pat, clean_text):
                raw = m.group(1).replace(",", "").strip()
                try:
                    val = float(raw)
                    # Ignore tiny numbers that look like dates or PIN codes
                    if 1500.0 <= val <= 2000000.0:
                        # Ensure this value is not the isolated EMI installment
                        if detail.emi_per_month and abs(val - detail.emi_per_month) < 1.0:
                            continue
                        # Ensure this value is not a discount or exchange bonus amount
                        if val in discount_amounts and (explicit_price is None or val != explicit_price):
                            continue
                        found_prices.append(val)
                except ValueError:
                    continue

        # 5. Distinguish MRP (listed price) vs selling price
        mrp_match = re.search(
            r"(?:MRP|M\.R\.P\.?|List Price|Original Price)\s*[:\-]?\s*(?:₹|Rs\.?|INR)?\s*([\d,]{4,8})",
            clean_text,
            re.IGNORECASE,
        )
        if mrp_match:
            try:
                detail.listed_price = float(mrp_match.group(1).replace(",", ""))
            except ValueError:
                pass

        if explicit_price is not None:
            detail.selling_price = explicit_price
            if detail.listed_price is None and found_prices:
                higher = [p for p in found_prices if p > explicit_price]
                if higher:
                    detail.listed_price = max(higher)
        elif found_prices:
            unique_prices = sorted(list(set(found_prices)))
            if len(unique_prices) == 1:
                detail.selling_price = unique_prices[0]
            else:
                detail.selling_price = unique_prices[0]
                if detail.listed_price is None and len(unique_prices) > 1:
                    detail.listed_price = unique_prices[-1]

        detail.unconditional_price = detail.selling_price
        detail.effective_price = detail.selling_price

        # 4. Extract conditional discounts (Bank offers, exchange bonuses, coupons)
        conditions: List[str] = []

        # Bank offers
        bank_matches = re.finditer(
            r"((?:Get|Flat|Up to|Extra)?\s*(?:₹|Rs\.?|INR)?\s*[\d,]+\s*(?:Instant\s+)?(?:off|discount|cashback)\s*(?:on|with)\s*[A-Za-z\s]+(?:Bank|Card|Cards|Credit Card|Debit Card))",
            clean_text,
            re.IGNORECASE,
        )
        for bm in bank_matches:
            c_text = bm.group(1).strip()
            if c_text not in conditions:
                conditions.append(c_text)

        # Exchange offers
        exchange_match = re.search(
            r"(Up to\s*(?:₹|Rs\.?|INR)?\s*[\d,]+\s*off\s*on\s*exchange|Exchange\s*bonus\s*up to\s*(?:₹|Rs\.?|INR)?\s*[\d,]+)",
            clean_text,
            re.IGNORECASE,
        )
        if exchange_match:
            conditions.append(exchange_match.group(1).strip())

        # Coupon offers
        coupon_match = re.search(
            r"(Apply\s*coupon\s*(?:for|worth)?\s*(?:₹|Rs\.?|INR)?\s*[\d,]+|[\d,]+\s*coupon\s*applied)",
            clean_text,
            re.IGNORECASE,
        )
        if coupon_match:
            conditions.append(coupon_match.group(1).strip())

        if conditions:
            detail.discount_conditions = conditions
            detail.is_conditional = True

            # If there's a specific bank discount amount, calculate effective price
            for c in conditions:
                amt_match = re.search(r"(?:₹|Rs\.?|INR)\s*([\d,]+)", c)
                if amt_match:
                    try:
                        disc_amt = float(amt_match.group(1).replace(",", ""))
                        if 100 <= disc_amt <= (detail.selling_price * 0.35):
                            detail.effective_price = max(0.0, detail.selling_price - disc_amt)
                            break
                    except ValueError:
                        pass

        return detail

    @classmethod
    def check_availability(cls, text: str) -> str:
        """Determine stock availability status from webpage text."""
        lower = text.lower()
        if any(k in lower for k in ("out of stock", "sold out", "currently unavailable", "item unavailable")):
            return "out_of_stock"
        if any(k in lower for k in ("in stock", "left in stock", "available to ship", "add to cart", "buy now")):
            return "in_stock"
        return "unknown"

    detect_availability = check_availability
