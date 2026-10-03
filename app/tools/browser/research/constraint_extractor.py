"""
Constraint extractor for Browser Research Agent.
Extracts hard product specifications, retailer preferences, and budget constraints.
"""

from __future__ import annotations

import re
from typing import Optional
from app.tools.browser.research.models import ProductConstraints


class ConstraintExtractor:
    """Parses raw user queries into structured product specifications and constraints."""

    # Major consumer electronics brands
    KNOWN_BRANDS = [
        "ASUS", "Apple", "Lenovo", "Dell", "HP", "Acer", "Samsung",
        "MSI", "Sony", "LG", "Xiaomi", "Realme", "OnePlus", "Google",
        "Motorola", "Nothing", "Vivo", "Oppo", "Infinix"
    ]

    # Major Indian and global retailers
    KNOWN_RETAILERS = [
        "Amazon", "Flipkart", "Croma", "Reliance Digital", "Vijay Sales",
        "Tata Cliq", "Myntra", "Ajio", "Official Store"
    ]

    @classmethod
    def extract(cls, query: str) -> ProductConstraints:
        """Extract hard constraints from user query deterministically."""
        clean_text = query.strip()
        constraints = ProductConstraints()

        # 1. Brand detection
        for brand in cls.KNOWN_BRANDS:
            if re.search(rf"\b{re.escape(brand)}\b", clean_text, re.IGNORECASE):
                constraints.brand = brand
                break

        # 2. RAM detection (e.g. 8GB, 16 GB, 32GB RAM)
        ram_match = re.search(r"\b(\d{1,2})\s*(?:GB|gb)?\s*(?:RAM|ram|memory)\b", clean_text, re.IGNORECASE)
        if not ram_match:
            ram_match = re.search(r"\b(\d{1,2})\s*GB\b", clean_text, re.IGNORECASE)
        if ram_match:
            try:
                val = int(ram_match.group(1))
                if val in (4, 6, 8, 12, 16, 24, 32, 64, 128):
                    constraints.ram_gb = val
            except ValueError:
                pass

        # 3. Storage detection (e.g. 512GB SSD, 1TB SSD, 256 GB)
        tb_match = re.search(r"\b(\d{1,2})\s*(?:TB|tb)\s*(?:SSD|ssd|storage|ROM|rom)?\b", clean_text, re.IGNORECASE)
        if tb_match:
            try:
                constraints.storage_gb = int(tb_match.group(1)) * 1024
                constraints.storage_type = "SSD"
            except ValueError:
                pass
        else:
            gb_match = re.search(r"\b(128|256|512)\s*(?:GB|gb)?\s*(?:SSD|ssd|storage|ROM|rom)?\b", clean_text, re.IGNORECASE)
            if gb_match:
                try:
                    constraints.storage_gb = int(gb_match.group(1))
                    constraints.storage_type = "SSD"
                except ValueError:
                    pass

        # 4. CPU / Processor detection
        cpu_patterns = [
            (r"\b(Intel\s+Core\s+i[3579](?:[- ]\w+)?)\b", "Intel Core"),
            (r"\b(Core\s+Ultra\s+[579](?:[- ]\w+)?)\b", "Intel Core Ultra"),
            (r"\b(i[3579][- ]\d{4,5}\w*)\b", "Intel Core"),
            (r"\b(i[3579])\b", "Intel Core"),
            (r"\b(Ryzen\s+[3579](?:[- ]\w+)?)\b", "AMD Ryzen"),
            (r"\b(M[1234](?:\s+(?:Pro|Max|Ultra))?)\b", "Apple Silicon"),
            (r"\b(Snapdragon\s+(?:X\s+Elite|\d\w*))\b", "Qualcomm Snapdragon"),
        ]
        for pat, family in cpu_patterns:
            m = re.search(pat, clean_text, re.IGNORECASE)
            if m:
                matched_val = m.group(1).strip()
                if family == "Intel Core" and re.match(r"^i[3579]$", matched_val, re.IGNORECASE):
                    constraints.cpu = f"Intel Core {matched_val.lower()}"
                else:
                    constraints.cpu = matched_val
                break

        # 5. GPU detection
        gpu_match = re.search(r"\b(RTX\s*\d{4}(?:\s*Ti)?|GTX\s*\d{4}|Radeon\s*\w+|Iris\s*Xe)\b", clean_text, re.IGNORECASE)
        if gpu_match:
            constraints.gpu = gpu_match.group(1).strip()

        # 6. Display type & size
        if re.search(r"\bOLED\b", clean_text, re.IGNORECASE):
            constraints.display_type = "OLED"
        elif re.search(r"\bIPS\b", clean_text, re.IGNORECASE):
            constraints.display_type = "IPS"

        disp_match = re.search(r"\b(13\.3|14|15\.6|16|17\.3)\s*(?:inch|[\"'])\b", clean_text, re.IGNORECASE)
        if disp_match:
            constraints.display_size = f"{disp_match.group(1)} inch"

        # 7. Model number / series detection
        # Extract model series (e.g., Zenbook 14, Vivobook 15, MacBook Air, ThinkPad T14, Legion 5 Pro, Pavilion 15)
        series_patterns = [
            r"\b(ZenBook(?:\s*Flip|\s*Duo|\s*Pro)?(?:\s*\d{2})?)\b",
            r"\b(VivoBook(?:\s*Pro|\s*S|\s*Go|\s*Flip)?(?:\s*\d{2})?)\b",
            r"\b(ROG(?:\s*Zephyrus|\s*Strix)?(?:\s*\w+)?)\b",
            r"\b(TUF(?:\s*Gaming)?(?:\s*\w+)?)\b",
            r"\b(MacBook\s*(?:Air|Pro)(?:\s*\d{2})?)\b",
            r"\b(Legion(?:\s*\d)?(?:\s*Pro|\s*Slim)?)\b",
            r"\b(ThinkPad\s*[A-Za-z]\d{1,2})\b",
            r"\b(IdeaPad(?:\s*Slim|\s*Gaming)?(?:\s*\d)?)\b",
            r"\b(Yoga(?:\s*Slim)?(?:\s*\d)?)\b",
            r"\b(XPS\s*\d{2})\b",
            r"\b(Inspiron\s*\d{2,4})\b",
            r"\b(Pavilion(?:\s*Plus|\s*Aero)?(?:\s*\d{2})?)\b",
            r"\b(Spectre(?:\s*x360)?(?:\s*\d{2})?)\b",
            r"\b(Envy(?:\s*x360)?(?:\s*\d{2})?)\b",
            r"\b(Galaxy\s*Book(?:\s*\d)?(?:\s*Pro)?)\b",
            r"\b(Swift(?:\s*Go|\s*X)?(?:\s*\d)?)\b",
            r"\b(Aspire(?:\s*\d)?)\b",
            r"\b(Predator(?:\s*Helios)?(?:\s*\d{2,3})?)\b",
        ]
        for pat in series_patterns:
            m = re.search(pat, clean_text, re.IGNORECASE)
            if m:
                constraints.model_name = m.group(1).strip()
                break

        # Brand inference from model if brand was not explicitly stated
        if not constraints.brand and constraints.model_name:
            m_lower = constraints.model_name.lower()
            if "macbook" in m_lower:
                constraints.brand = "Apple"
            elif any(k in m_lower for k in ("thinkpad", "ideapad", "yoga", "legion")):
                constraints.brand = "Lenovo"
            elif any(k in m_lower for k in ("zenbook", "vivobook", "rog", "tuf")):
                constraints.brand = "ASUS"
            elif any(k in m_lower for k in ("galaxy book",)):
                constraints.brand = "Samsung"
            elif any(k in m_lower for k in ("xps", "inspiron")):
                constraints.brand = "Dell"
            elif any(k in m_lower for k in ("pavilion", "spectre", "envy")):
                constraints.brand = "HP"

        # Check for specific alphanumeric SKU (e.g. UX3405, X1502, 15-fc0026AU)
        sku_match = re.search(r"\b([A-Za-z]{2,5}[- ]?\d{4,5}[A-Za-z0-9]*)\b", clean_text)
        if sku_match:
            candidate_sku = sku_match.group(1).strip()
            # Exclude false positives like "RTX4060", "DDR5", "512GB"
            if not any(k in candidate_sku.upper() for k in ("RTX", "GTX", "DDR", "RAM", "SSD", "ROM")):
                constraints.model_number_or_sku = candidate_sku

        # 8. Budget limit detection (e.g. "under 60000", "under 60k", "budget 75,000")
        budget_match = re.search(r"\b(?:under|below|budget|max|within)\s*(?:₹|Rs\.?|INR)?\s*([\d,]+)\s*(k|thousand|lakh)?\b", clean_text, re.IGNORECASE)
        if budget_match:
            raw_val = budget_match.group(1).replace(",", "")
            multiplier = budget_match.group(2)
            try:
                val = float(raw_val)
                if multiplier:
                    mult_lower = multiplier.lower()
                    if mult_lower in ("k", "thousand"):
                        val *= 1000
                    elif mult_lower == "lakh":
                        val *= 100000
                constraints.max_budget = val
            except ValueError:
                pass

        # 9. Condition detection
        if re.search(r"\b(refurbished|renewed|second hand|used)\b", clean_text, re.IGNORECASE):
            constraints.condition = "refurbished"
        else:
            constraints.condition = "new"

        # 10. Preferred retailer filter
        for ret in cls.KNOWN_RETAILERS:
            if re.search(rf"\b{re.escape(ret)}\b", clean_text, re.IGNORECASE):
                r_name = "Amazon India" if ret.lower() == "amazon" else ret
                if r_name not in constraints.preferred_retailers:
                    constraints.preferred_retailers.append(r_name)

        return constraints

    extract_constraints = extract
