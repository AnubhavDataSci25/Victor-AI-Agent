"""
Visual Analyzer for Victor.

Provides OCR text extraction and semantic scene understanding using Gemini Vision:
- Text OCR extraction for Visual Copy/Paste
- Semantic answers for 'what am I doing?', 'analyze what is in front of me',
  'what does this image contain?'
- High efficiency JPEG compression before transmission
- Respects privacy: never retains images permanently without explicit command
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Optional, Tuple

import cv2
from google import genai
from google.genai import types
import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


class VisualAnalyzer:
    """Uses Gemini Vision API for OCR and semantic scene comprehension."""

    def __init__(self, model_name: Optional[str] = None) -> None:
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
    def _to_jpeg_bytes(source: Image.Image | np.ndarray | str | Path) -> Tuple[bool, Optional[bytes], str]:
        """Converts various image inputs to optimized JPEG bytes in memory."""
        try:
            if isinstance(source, (str, Path)):
                p = Path(source)
                if not p.exists():
                    return False, None, f"Image file not found: {source}"
                with Image.open(p) as img:
                    buf = io.BytesIO()
                    img.convert("RGB").save(buf, format="JPEG", quality=85)
                    return True, buf.getvalue(), "Success"

            elif isinstance(source, np.ndarray):
                # OpenCV BGR format
                rgb = cv2.cvtColor(source, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=85)
                return True, buf.getvalue(), "Success"

            elif isinstance(source, Image.Image):
                buf = io.BytesIO()
                source.convert("RGB").save(buf, format="JPEG", quality=85)
                return True, buf.getvalue(), "Success"

            return False, None, "Unsupported image type."
        except Exception as e:
            return False, None, f"Image conversion error: {str(e)}"

    async def extract_text_ocr(
        self,
        image_source: Image.Image | np.ndarray | str | Path,
        region: Optional[list[int]] = None,
    ) -> Tuple[bool, str]:
        """
        Performs OCR on an image/frame to extract visible text.
        Optionally crops to [x1, y1, x2, y2] pixel region first.
        """
        if region and len(region) == 4:
            x1, y1, x2, y2 = region
            if isinstance(image_source, Image.Image):
                image_source = image_source.crop((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))
            elif isinstance(image_source, np.ndarray):
                image_source = image_source[min(y1, y2):max(y1, y2), min(x1, x2):max(x1, x2)]

        ok, image_bytes, err = self._to_jpeg_bytes(image_source)
        if not ok or not image_bytes:
            return False, f"Could not process image for OCR: {err}"

        prompt = (
            "You are an accurate, high-fidelity OCR engine. "
            "Extract all readable text from this image exactly as written. "
            "Preserve original line breaks, formatting, punctuation, and numerical data. "
            "Do NOT add any introductory remarks, summary, or commentary. "
            "Output ONLY the raw extracted text."
        )

        try:
            client = self._get_client()
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=[image_part, prompt],
            )
            extracted_text = (response.text or "").strip()
            if not extracted_text:
                return True, "No readable text was detected in the visual region."
            return True, extracted_text
        except Exception as e:
            logger.error(f"[VisualAnalyzer] OCR extraction failed: {e}")
            return False, f"OCR extraction error: {str(e)}"

    async def analyze_visual(
        self,
        image_source: Image.Image | np.ndarray | str | Path,
        query: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Analyzes image content with Gemini Vision.
        Answers user questions like 'what am I doing?', 'analyze what is in front of me'.
        """
        ok, image_bytes, err = self._to_jpeg_bytes(image_source)
        if not ok or not image_bytes:
            return False, f"Could not process image for visual analysis: {err}"

        user_query = (query or "").strip() or "Describe what is currently visible in this camera view or image."

        system_instruction = (
            "You are Victor, a personal AI assistant dedicated exclusively to Anubhav Sir. Address the user as 'Sir'. "
            "Analyze this camera frame or image carefully and answer the user's inquiry concisely, intelligently, and naturally. "
            "Focus on active actions, physical objects, environment context, visible documents, or specific questions asked. "
            "Keep the response to 1-3 crisp, informative sentences suitable for spoken assistant output."
        )

        prompt = f"User inquiry: {user_query}"

        try:
            client = self._get_client()
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=[image_part, system_instruction, prompt],
            )
            analysis_text = (response.text or "").strip()
            return True, analysis_text or "I observed the visual frame, Sir, but found no notable activity."
        except Exception as e:
            logger.error(f"[VisualAnalyzer] Visual analysis failed: {e}")
            return False, f"Visual analysis error: {str(e)}"


_visual_analyzer_instance: Optional[VisualAnalyzer] = None


def get_visual_analyzer() -> VisualAnalyzer:
    global _visual_analyzer_instance
    if _visual_analyzer_instance is None:
        _visual_analyzer_instance = VisualAnalyzer()
    return _visual_analyzer_instance
