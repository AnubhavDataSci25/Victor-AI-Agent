"""
Screen Analyzer — Vision-based screen understanding layer for Victor.

Uses the existing ComputerTakeScreenshotTool to capture the current screen,
submits the image to a vision-capable Gemini model, extracts structured
information (visible text, UI elements, forms, buttons, errors, applications,
and user query answers), maps coordinates to pixel space, and formats a safe,
actionable understanding for Victor.
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from PIL import Image
from google import genai
from google.genai import types

from app.tools.computer.tool import ComputerTakeScreenshotTool

logger = logging.getLogger(__name__)


class ScreenAnalyzer:
    """Lightweight screen analysis using existing screenshot tool and Gemini vision."""

    def __init__(self, model_name: Optional[str] = None):
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
    def _extract_screenshot_path(tool_output: str) -> Optional[str]:
        """Extracts the saved screenshot filepath from ComputerTakeScreenshotTool output."""
        prefix = "saved to "
        idx = tool_output.find(prefix)
        if idx != -1:
            raw_path = tool_output[idx + len(prefix):].rstrip(". \r\n")
            if Path(raw_path).exists():
                return raw_path

        # Fallback: search for victor_screenshot_*.png in ~/Pictures
        pictures_dir = Path.home() / "Pictures"
        if pictures_dir.exists():
            matches = sorted(pictures_dir.glob("victor_screenshot_*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
            if matches:
                return str(matches[0])

        return None

    @staticmethod
    def _scale_box_to_pixels(box: list[float | int], width: int, height: int) -> dict[str, int]:
        """Converts normalized [ymin, xmin, ymax, xmax] (0-1000) to pixel center {x, y}."""
        if len(box) == 4:
            ymin, xmin, ymax, xmax = box
            center_x = int(((xmin + xmax) / 2) / 1000.0 * width)
            center_y = int(((ymin + ymax) / 2) / 1000.0 * height)
            return {"x": center_x, "y": center_y}
        return {"x": width // 2, "y": height // 2}

    async def analyze_screen(
        self,
        query: Optional[str] = None,
        focus: Optional[str] = None
    ) -> dict[str, Any]:
        """
        Captures the screen and asks Gemini Vision to analyze it.
        Returns a structured dictionary with analysis results.
        """
        # 1. Capture screen using existing ComputerTakeScreenshotTool
        screenshot_tool = ComputerTakeScreenshotTool()
        capture_result = await screenshot_tool.execute({})

        screenshot_path = self._extract_screenshot_path(capture_result)
        if not screenshot_path:
            return {
                "success": False,
                "error": f"Could not locate captured screenshot. Screenshot output: {capture_result}",
                "formatted_text": f"Error: Screen capture could not be retrieved. {capture_result}"
            }

        # 2. Load and prepare image
        try:
            with Image.open(screenshot_path) as img:
                img_width, img_height = img.size
                # Convert to RGB and compress as JPEG to ensure fast transmission
                buffer = io.BytesIO()
                img.convert("RGB").save(buffer, format="JPEG", quality=85)
                image_bytes = buffer.getvalue()
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to load screenshot image: {e}",
                "formatted_text": f"Error loading captured image: {str(e)}"
            }

        # 3. Formulate structured vision prompt
        prompt = self._build_prompt(query=query, focus=focus)

        # 4. Call Gemini Vision
        try:
            client = self._get_client()
            image_part = types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")

            config = types.GenerateContentConfig(
                response_mime_type="application/json"
            )

            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=[image_part, prompt],
                config=config
            )

            raw_text = response.text or ""
            parsed = self._parse_json_response(raw_text)

            # 5. Post-process coordinates to actual pixel values
            self._enrich_coordinates(parsed, img_width, img_height)

            # 6. Format human-readable and agent-friendly response
            formatted_text = self._format_understanding(parsed, query=query)

            return {
                "success": True,
                "data": parsed,
                "image_path": screenshot_path,
                "screen_dimensions": {"width": img_width, "height": img_height},
                "formatted_text": formatted_text
            }

        except Exception as e:
            logger.error(f"Gemini vision analysis failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "image_path": screenshot_path,
                "formatted_text": f"Screen understanding encountered an error: {str(e)}"
            }

    def _build_prompt(self, query: Optional[str] = None, focus: Optional[str] = None) -> str:
        query_instruction = (
            f"The user specifically asked: \"{query}\". Please address this directly in the answer_to_query field."
            if query else "Provide a comprehensive analysis of the screen."
        )

        focus_instruction = (
            f"Focus particularly on: {focus}."
            if focus else ""
        )

        return (
            "You are Victor's screen understanding vision system. Analyze this screenshot in detail.\n"
            f"{query_instruction}\n"
            f"{focus_instruction}\n\n"
            "Return a JSON object strictly following this JSON schema:\n"
            "{\n"
            "  \"summary\": \"High-level summary of what is currently on the screen (1-3 sentences)\",\n"
            "  \"active_application\": \"The primary active application or window visible (e.g. Chrome, VS Code, Notepad, Terminal)\",\n"
            "  \"visible_text\": \"Key textual content, headings, or messages visible\",\n"
            "  \"detected_errors\": [\"Any visible error dialogs, error messages, warning banners, crash notifications, or red alert text\"],\n"
            "  \"form\": {\n"
            "    \"form_detected\": true,\n"
            "    \"form_title_or_purpose\": \"Purpose of the form (e.g., Login, Registration, Contact Us, Search)\",\n"
            "    \"fields\": [\n"
            "      {\n"
            "        \"field_name\": \"name or label of field\",\n"
            "        \"field_label\": \"visible label for field\",\n"
            "        \"field_type\": \"text | password | email | number | select | checkbox\",\n"
            "        \"current_value\": \"current text in field or null\",\n"
            "        \"is_required\": true,\n"
            "        \"box_2d\": [ymin, xmin, ymax, xmax]\n"
            "      }\n"
            "    ],\n"
            "    \"submit_button\": {\n"
            "      \"label\": \"Submit / Sign In / Send\",\n"
            "      \"box_2d\": [ymin, xmin, ymax, xmax]\n"
            "    }\n"
            "  },\n"
            "  \"interactive_elements\": [\n"
            "    {\n"
            "      \"id\": \"element_id\",\n"
            "      \"element_type\": \"button | menu | link | tab | dropdown | icon\",\n"
            "      \"label\": \"visible text on the element\",\n"
            "      \"box_2d\": [ymin, xmin, ymax, xmax]\n"
            "    }\n"
            "  ],\n"
            "  \"answer_to_query\": \"Direct, concise, and helpful answer to the user's specific request\"\n"
            "}\n\n"
            "IMPORTANT: All box_2d coordinates must be normalized integers [ymin, xmin, ymax, xmax] on a scale of 0 to 1000.\n"
            "If no form is present, set form.form_detected to false and fields to [].\n"
            "If no errors are visible, set detected_errors to []."
        )

    def _parse_json_response(self, text: str) -> dict[str, Any]:
        """Cleans and parses model JSON output, handling code fences or extraneous text."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try to extract the first JSON object using regex
            match = re.search(r"\{.*\}", cleaned, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(0))
                except Exception:
                    pass
            return {"summary": text, "detected_errors": [], "interactive_elements": []}

    def _enrich_coordinates(self, data: dict[str, Any], width: int, height: int) -> None:
        """Converts all box_2d entries in the parsed data to absolute pixel {x, y} coordinates."""
        # Process interactive elements
        elements = data.get("interactive_elements", [])
        if isinstance(elements, list):
            for elem in elements:
                if isinstance(elem, dict) and "box_2d" in elem:
                    elem["coordinates"] = self._scale_box_to_pixels(elem["box_2d"], width, height)

        # Process form fields
        form = data.get("form", {})
        if isinstance(form, dict):
            fields = form.get("fields", [])
            if isinstance(fields, list):
                for field in fields:
                    if isinstance(field, dict) and "box_2d" in field:
                        field["coordinates"] = self._scale_box_to_pixels(field["box_2d"], width, height)

            submit_btn = form.get("submit_button")
            if isinstance(submit_btn, dict) and "box_2d" in submit_btn:
                submit_btn["coordinates"] = self._scale_box_to_pixels(submit_btn["box_2d"], width, height)

    def _format_understanding(self, data: dict[str, Any], query: Optional[str] = None) -> str:
        """Constructs an intelligent, actionable text report for the agent and user."""
        lines = []

        summary = data.get("summary", "Screen analyzed.")
        active_app = data.get("active_application")
        if active_app:
            lines.append(f"🖥️ **Active Application**: {active_app}")
        lines.append(f"📋 **Summary**: {summary}")

        answer = data.get("answer_to_query")
        if answer:
            lines.append(f"💬 **Direct Answer**: {answer}")

        # Errors section
        errors = data.get("detected_errors", [])
        if errors and len(errors) > 0:
            lines.append("\n⚠️ **Detected Errors/Warnings**:")
            for err in errors:
                lines.append(f"  • {err}")

        # Form section
        form = data.get("form", {})
        if isinstance(form, dict) and form.get("form_detected"):
            purpose = form.get("form_title_or_purpose", "Form")
            lines.append(f"\n📝 **Form Detected ({purpose})**:")
            fields = form.get("fields", [])
            if fields:
                for idx, f in enumerate(fields, 1):
                    label = f.get("field_label") or f.get("field_name") or f"Field {idx}"
                    ftype = f.get("field_type", "text")
                    coords = f.get("coordinates", {})
                    coord_str = f"(at x={coords.get('x')}, y={coords.get('y')})" if "x" in coords else ""
                    lines.append(f"  {idx}. {label} [{ftype}] {coord_str}")

            submit_btn = form.get("submit_button")
            if submit_btn and isinstance(submit_btn, dict):
                btn_label = submit_btn.get("label", "Submit")
                btn_coords = submit_btn.get("coordinates", {})
                btn_coord_str = f"(at x={btn_coords.get('x')}, y={btn_coords.get('y')})" if "x" in btn_coords else ""
                lines.append(f"  • Submit Button: '{btn_label}' {btn_coord_str}")

            # Critical Safety Reminder for the Agent
            lines.append(
                "\n🔒 **FORM SAFETY POLICY**: A form has been detected on screen. "
                "You MUST ask the user for the required information to fill each field BEFORE calling any typing or clicking tool. "
                "Do NOT enter information into form fields without asking the user first. "
                "Do NOT submit the form without explicit user confirmation."
            )

        # Interactive elements section
        interactive = data.get("interactive_elements", [])
        if interactive and isinstance(interactive, list):
            visible_btns = [e for e in interactive if isinstance(e, dict) and e.get("label")]
            if visible_btns:
                lines.append("\n🎯 **Visible Actionable UI Elements**:")
                for item in visible_btns[:8]:  # Top 8 most relevant elements
                    label = item.get("label", "")
                    etype = item.get("element_type", "element")
                    coords = item.get("coordinates", {})
                    coord_str = f"at ({coords.get('x')}, {coords.get('y')})" if "x" in coords else ""
                    lines.append(f"  • [{etype}] '{label}' {coord_str}")

        return "\n".join(lines)
