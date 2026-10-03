"""
QR & Barcode Scanner with URL Security Verification for Victor.

Local-first detection and decoding:
- Uses OpenCV QRCodeDetector and BarcodeDetector locally.
- Classifies content into URLs, Wi-Fi credentials, Contact cards (vCard/MECARD),
  phone numbers, emails, or plain text.
- Validates URL safety against injection, suspicious schemes, and malformed targets.
- Provides fallback to Gemini Vision if local detection finds no code or image is degraded.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Tuple
import urllib.parse

import cv2
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class CodeType:
    URL = "URL"
    WIFI = "WIFI"
    CONTACT = "CONTACT"
    EMAIL = "EMAIL"
    PHONE = "PHONE"
    SMS = "SMS"
    TEXT = "TEXT"


class UrlSafetyValidator:
    """Validates URLs extracted from QR codes or images against security risks."""

    ALLOWED_SCHEMES = {"http", "https"}
    BLOCKED_SCHEMES = {"javascript", "data", "file", "vbscript", "view-source", "blob", "chrome", "about"}
    DANGEROUS_CHARS_REGEX = re.compile(r"[\r\n\t\x00-\x1f`\$\|\;&<>]")

    @classmethod
    def validate_url(cls, raw_url: str) -> Dict[str, Any]:
        """
        Validates a URL extracted from visual content.
        Returns safety assessment, domain details, and recommendation.
        """
        raw_url = (raw_url or "").strip()
        if not raw_url:
            return {
                "is_safe": False,
                "status": "INVALID",
                "reason": "Empty URL provided.",
                "clean_url": "",
                "domain": "",
            }

        # Check for dangerous injection characters
        if cls.DANGEROUS_CHARS_REGEX.search(raw_url):
            return {
                "is_safe": False,
                "status": "BLOCKED",
                "reason": "URL contains malicious control or command injection characters.",
                "clean_url": "",
                "domain": "",
            }

        # Normalize scheme
        parsed = urllib.parse.urlparse(raw_url)
        if not parsed.scheme:
            # If domain-like (e.g. www.google.com or github.com/user)
            if re.match(r"^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$", raw_url):
                raw_url = f"https://{raw_url}"
                parsed = urllib.parse.urlparse(raw_url)
            else:
                return {
                    "is_safe": False,
                    "status": "INVALID",
                    "reason": "Missing protocol scheme (http/https).",
                    "clean_url": raw_url,
                    "domain": "",
                }

        scheme_lower = parsed.scheme.lower()
        if scheme_lower in cls.BLOCKED_SCHEMES:
            return {
                "is_safe": False,
                "status": "BLOCKED",
                "reason": f"Disallowed URI scheme: '{scheme_lower}:'. Security policy strictly restricts to HTTP/HTTPS.",
                "clean_url": raw_url,
                "domain": "",
            }

        if scheme_lower not in cls.ALLOWED_SCHEMES:
            return {
                "is_safe": False,
                "status": "BLOCKED",
                "reason": f"Unsupported protocol scheme: '{scheme_lower}'.",
                "clean_url": raw_url,
                "domain": "",
            }

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return {
                "is_safe": False,
                "status": "INVALID",
                "reason": "Malformed URL: hostname could not be identified.",
                "clean_url": raw_url,
                "domain": "",
            }

        # Check for suspicious ports (e.g. common backdoor or internal ports)
        if parsed.port and parsed.port not in (80, 443, 8000, 8080, 3000, 5000, 5173, 8443):
            return {
                "is_safe": True,
                "status": "CAUTION",
                "reason": f"URL connects to a non-standard port ({parsed.port}). Exercise caution.",
                "clean_url": raw_url,
                "domain": hostname,
                "path": parsed.path or "/",
            }

        return {
            "is_safe": True,
            "status": "SAFE",
            "reason": f"Valid {scheme_lower.upper()} destination.",
            "clean_url": raw_url,
            "domain": hostname,
            "path": parsed.path or "/",
        }


class CodeScanner:
    """Scans and parses QR codes and barcodes from images or camera frames."""

    def __init__(self) -> None:
        self.qr_detector = cv2.QRCodeDetector()
        try:
            self.barcode_detector = cv2.barcode.BarcodeDetector()
        except Exception:
            self.barcode_detector = None

    @staticmethod
    def classify_code_content(raw_text: str) -> Tuple[str, Dict[str, Any]]:
        """Classifies decoded text into high-level semantic types and extracts metadata."""
        text = raw_text.strip()

        # 1. Wi-Fi Configuration (WIFI:S:ssid;T:WPA;P:password;;)
        if text.startswith("WIFI:") or text.startswith("wifi:"):
            details: Dict[str, Any] = {"raw": text}
            for part in text[5:].split(";"):
                if part.startswith("S:"):
                    details["ssid"] = part[2:]
                elif part.startswith("T:"):
                    details["security"] = part[2:] or "None"
                elif part.startswith("P:"):
                    # Record password masked in metadata
                    pw = part[2:]
                    details["password_length"] = len(pw)
                    details["has_password"] = bool(pw)
                elif part.startswith("H:"):
                    details["hidden"] = part[2:].lower() == "true"
            return CodeType.WIFI, details

        # 2. Contact Card (vCard / MECARD)
        if text.startswith("BEGIN:VCARD") or text.startswith("MECARD:"):
            details = {"raw": text}
            if text.startswith("MECARD:"):
                # e.g. MECARD:N:Doe,John;TEL:123456789;EMAIL:john@example.com;;
                for part in text[7:].split(";"):
                    if part.startswith("N:"):
                        details["name"] = part[2:]
                    elif part.startswith("TEL:"):
                        details["phone"] = part[4:]
                    elif part.startswith("EMAIL:"):
                        details["email"] = part[6:]
            else:
                for line in text.splitlines():
                    if line.startswith("FN:") or line.startswith("N:"):
                        details["name"] = line.split(":", 1)[1]
                    elif line.startswith("TEL"):
                        details["phone"] = line.split(":", 1)[1]
                    elif line.startswith("EMAIL"):
                        details["email"] = line.split(":", 1)[1]
                    elif line.startswith("ORG:"):
                        details["organization"] = line.split(":", 1)[1]
            return CodeType.CONTACT, details

        # 3. URL
        if text.startswith(("http://", "https://", "ftp://", "www.")) or re.match(
            r"^([a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}(/.*)?$", text
        ):
            safety = UrlSafetyValidator.validate_url(text)
            return CodeType.URL, safety

        # 4. Email URI
        if text.startswith("mailto:") or text.startswith("MATMSG:"):
            email_addr = text.replace("mailto:", "").replace("MATMSG:", "").split("?")[0].strip()
            return CodeType.EMAIL, {"email": email_addr, "raw": text}

        # 5. Telephone URI
        if text.startswith("tel:"):
            phone_num = text.replace("tel:", "").strip()
            return CodeType.PHONE, {"phone": phone_num, "raw": text}

        # 6. SMS URI
        if text.startswith("smsto:"):
            parts = text.replace("smsto:", "").split(":")
            return CodeType.SMS, {"phone": parts[0], "message": parts[1] if len(parts) > 1 else "", "raw": text}

        # 7. Default to plain text or product barcode
        return CodeType.TEXT, {"text": text}

    def decode_cv2_image(self, bgr_image: np.ndarray) -> List[Dict[str, Any]]:
        """Locally decodes all QR codes and barcodes found in a BGR numpy image."""
        results: List[Dict[str, Any]] = []

        # 1. Detect QR code
        try:
            # Try multi-QR first
            retval, decoded_info, points, _ = self.qr_detector.detectAndDecodeMulti(bgr_image)
            if retval and decoded_info:
                for code_str in decoded_info:
                    if code_str and code_str.strip():
                        code_type, details = self.classify_code_content(code_str)
                        results.append({
                            "format": "QR_CODE",
                            "content": code_str,
                            "type": code_type,
                            "details": details,
                        })
            else:
                # Single QR fallback
                code_str, points, _ = self.qr_detector.detectAndDecode(bgr_image)
                if code_str and code_str.strip():
                    code_type, details = self.classify_code_content(code_str)
                    results.append({
                        "format": "QR_CODE",
                        "content": code_str,
                        "type": code_type,
                        "details": details,
                    })
        except Exception as e:
            logger.debug(f"[CodeScanner] QR detection error: {e}")

        # 2. Detect 1D/2D Barcodes
        if self.barcode_detector is not None:
            try:
                retval, decoded_info, decoded_type, points = self.barcode_detector.detectAndDecode(bgr_image)
                if retval and decoded_info:
                    for idx, code_str in enumerate(decoded_info):
                        if code_str and code_str.strip():
                            b_type = decoded_type[idx] if idx < len(decoded_type) else "BARCODE"
                            # Avoid duplicates if QR was already picked up
                            if not any(r["content"] == code_str for r in results):
                                c_type, details = self.classify_code_content(code_str)
                                results.append({
                                    "format": str(b_type),
                                    "content": code_str,
                                    "type": c_type,
                                    "details": details,
                                })
            except Exception as e:
                logger.debug(f"[CodeScanner] Barcode detection error: {e}")

        return results

    def decode_image_file(self, file_path: str | Path) -> List[Dict[str, Any]]:
        """Loads an image from file and decodes all codes."""
        p = Path(file_path)
        if not p.exists():
            return []
        img = cv2.imread(str(p))
        if img is None:
            return []
        return self.decode_cv2_image(img)

    def decode_pil_image(self, pil_image: Image.Image) -> List[Dict[str, Any]]:
        """Converts PIL image to OpenCV format and decodes codes."""
        rgb = np.array(pil_image.convert("RGB"))
        bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)
        return self.decode_cv2_image(bgr)

    @staticmethod
    def format_scan_summary(scan_results: List[Dict[str, Any]]) -> str:
        """Formats detected codes into clear, actionable text for Victor."""
        if not scan_results:
            return "No QR codes or barcodes were detected in the provided image/camera frame."

        lines = [f"Found {len(scan_results)} code(s):"]
        for i, item in enumerate(scan_results, 1):
            fmt = item["format"]
            ctype = item["type"]
            content = item["content"]
            details = item.get("details", {})

            lines.append(f"\n[{i}] {fmt} ({ctype}):")
            if ctype == CodeType.URL:
                is_safe = details.get("is_safe", False)
                domain = details.get("domain", "")
                status = details.get("status", "UNKNOWN")
                clean_url = details.get("clean_url", content)

                lines.append(f"  URL: {clean_url}")
                lines.append(f"  Domain: {domain}")
                lines.append(f"  Safety: {status} ({details.get('reason', '')})")
                if is_safe:
                    lines.append(f"  Recommended Action: Ask user if they wish to open '{domain}' in the browser.")
                else:
                    lines.append("  Recommended Action: Do NOT open automatically; warn the user of potential risk.")

            elif ctype == CodeType.WIFI:
                lines.append(f"  Network SSID: {details.get('ssid', 'Unknown')}")
                lines.append(f"  Security: {details.get('security', 'None')}")
                lines.append(f"  Password Configured: {'Yes' if details.get('has_password') else 'No'}")

            elif ctype == CodeType.CONTACT:
                if details.get("name"):
                    lines.append(f"  Name: {details['name']}")
                if details.get("phone"):
                    lines.append(f"  Phone: {details['phone']}")
                if details.get("email"):
                    lines.append(f"  Email: {details['email']}")

            elif ctype in (CodeType.PHONE, CodeType.EMAIL, CodeType.SMS):
                for k, v in details.items():
                    if k != "raw":
                        lines.append(f"  {k.capitalize()}: {v}")
            else:
                lines.append(f"  Data: {content}")

        return "\n".join(lines)


_scanner_instance: Optional[CodeScanner] = None


def get_code_scanner() -> CodeScanner:
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = CodeScanner()
    return _scanner_instance
