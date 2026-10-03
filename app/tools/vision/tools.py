"""
Concrete Visual Intelligence & Camera Tools for Victor.

Integrates with Victor's BaseTool architecture:
- camera_open: Explicitly open camera hardware.
- camera_close: Deactivate camera and release hardware.
- camera_capture: Snapshot frame or photo.
- camera_record_video: Record short video clip.
- camera_analyze: Semantic visual understanding (what am I doing?).
- camera_live_analysis: Periodic frame-rate throttled visual analysis mode.
- visual_scan_code: Local QR and Barcode detection with URL safety verification.
- visual_copy: Visual OCR text extraction or image copy to Windows clipboard.
- visual_paste: Paste clipboard content into active application.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from PIL import Image, ImageGrab

from app.tools.base import BaseTool
from app.tools.permissions import PermissionLevel
from app.tools.vision.camera_driver import CameraDriver, get_camera_driver
from app.tools.vision.clipboard_manager import WindowsClipboardManager
from app.tools.vision.code_scanner import CodeScanner, CodeType, get_code_scanner
from app.tools.vision.live_analyzer import LiveCameraAnalyzer, get_live_camera_analyzer
from app.tools.vision.visual_analyzer import VisualAnalyzer, get_visual_analyzer

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 1. Camera Lifecycle Tools
# ---------------------------------------------------------------------------

class CameraOpenTool(BaseTool):
    name = "camera_open"
    description = (
        "Explicitly opens Victor's camera hardware and prepares it for capture or visual analysis. "
        "Camera access is strictly user-initiated and clearly indicated in the UI. "
        "Use when user commands: 'open camera', 'turn on camera', 'activate camera'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "device_index": {
                "type": "integer",
                "default": 0,
                "description": "Camera device index on Windows (default: 0)."
            }
        }
    }

    def __init__(self, driver: Optional[CameraDriver] = None) -> None:
        self.driver = driver or get_camera_driver()

    async def execute(self, args: dict) -> str:
        idx = int(args.get("device_index", 0))
        success, msg = await self.driver.open_camera(device_index=idx)
        return msg


class CameraCloseTool(BaseTool):
    name = "camera_close"
    description = (
        "Explicitly closes the camera hardware, halts any active live visual analysis, "
        "releases device access, and turns off the camera indicator. "
        "Use when user commands: 'close camera', 'turn off camera', 'stop camera'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {"type": "object", "properties": {}}

    def __init__(
        self,
        driver: Optional[CameraDriver] = None,
        live_analyzer: Optional[LiveCameraAnalyzer] = None
    ) -> None:
        self.driver = driver or get_camera_driver()
        self.live_analyzer = live_analyzer or get_live_camera_analyzer()

    async def execute(self, args: dict) -> str:
        # Halt live analysis if running
        if self.live_analyzer.is_running:
            await self.live_analyzer.stop()
        success, msg = await self.driver.close_camera()
        return msg


class CameraCaptureTool(BaseTool):
    name = "camera_capture"
    description = (
        "Captures a photo or frame from the camera. Use when the user says: 'capture this', "
        "'take a photo', 'take a picture', or requests a snapshot. "
        "By default, media is temporary and not permanently stored unless save is true or user asked to save it."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "save": {
                "type": "boolean",
                "default": False,
                "description": "Whether to permanently save the photo to the user's Pictures directory (default: false unless user explicitly asked to save)."
            },
            "filename": {
                "type": "string",
                "description": "Optional custom filename if saving."
            }
        }
    }

    def __init__(self, driver: Optional[CameraDriver] = None) -> None:
        self.driver = driver or get_camera_driver()

    async def execute(self, args: dict) -> str:
        save = bool(args.get("save", False))
        filename = args.get("filename")

        if save:
            ok, result = await self.driver.save_photo(filename=filename)
            if ok:
                return f"Photo successfully captured and saved to: {result}"
            return f"Failed to save photo: {result}"

        ok, frame, msg = await self.driver.capture_frame(auto_open=True)
        if ok and frame is not None:
            h, w, _ = frame.shape
            return f"Frame successfully captured ({w}x{h}). Ready for analysis or visual copy."
        return f"Camera capture failed: {msg}"


class CameraRecordVideoTool(BaseTool):
    name = "camera_record_video"
    description = (
        "Records a short video clip from the camera (up to 30 seconds). "
        "By default, media is saved to the user's Videos directory if save is true or user asked to record a video."
    )
    permission_level = PermissionLevel.LOW
    parameters = {
        "type": "object",
        "properties": {
            "duration_seconds": {
                "type": "integer",
                "default": 5,
                "description": "Duration of video to record in seconds (between 1 and 30, default 5)."
            },
            "save": {
                "type": "boolean",
                "default": True,
                "description": "Whether to save the recorded video to the user's Videos directory (default: true)."
            },
            "filename": {
                "type": "string",
                "description": "Optional custom filename for the video."
            }
        }
    }

    def __init__(self, driver: Optional[CameraDriver] = None) -> None:
        self.driver = driver or get_camera_driver()

    async def execute(self, args: dict) -> str:
        dur = int(args.get("duration_seconds", 5))
        save = bool(args.get("save", True))
        filename = args.get("filename")

        ok, result = await self.driver.record_video(duration_seconds=dur, save=save, filename=filename)
        if ok:
            if save:
                return f"Video recorded successfully ({dur}s) and saved to: {result}"
            return f"Video recorded successfully ({dur}s)."
        return f"Video recording failed: {result}"


# ---------------------------------------------------------------------------
# 2. Camera Analysis & Live Monitoring Tools
# ---------------------------------------------------------------------------

class CameraAnalyzeTool(BaseTool):
    name = "camera_analyze"
    description = (
        "Analyzes what is currently in front of the camera or a specific captured image using vision AI. "
        "Use when user asks: 'what am I doing?', 'analyze what is in front of me', 'what does this image contain?', "
        "'what is this?', or 'describe what you see'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Specific question or analysis prompt (e.g. 'What am I doing?', 'What object is in front of me?')."
            },
            "source": {
                "type": "string",
                "enum": ["camera", "screen", "image_path"],
                "default": "camera",
                "description": "Visual source to analyze: 'camera' (default), 'screen', or 'image_path'."
            },
            "image_path": {
                "type": "string",
                "description": "Optional local filepath to an image if source is 'image_path'."
            }
        }
    }

    def __init__(
        self,
        driver: Optional[CameraDriver] = None,
        analyzer: Optional[VisualAnalyzer] = None
    ) -> None:
        self.driver = driver or get_camera_driver()
        self.analyzer = analyzer or get_visual_analyzer()

    async def execute(self, args: dict) -> str:
        query = args.get("query")
        source = str(args.get("source", "camera")).lower()
        image_path = args.get("image_path")

        if source == "image_path":
            if not image_path:
                return "Error: image_path is required when source is 'image_path'."
            ok, result = await self.analyzer.analyze_visual(image_path, query=query)
            return result if ok else f"Visual analysis failed: {result}"

        elif source == "screen":
            try:
                screen_img = ImageGrab.grab()
                ok, result = await self.analyzer.analyze_visual(screen_img, query=query)
                return result if ok else f"Screen analysis failed: {result}"
            except Exception as e:
                return f"Failed to capture screen: {str(e)}"

        else:
            # Camera source
            ok, frame, msg = await self.driver.capture_frame(auto_open=True)
            if not ok or frame is None:
                return f"Could not acquire camera frame for visual analysis: {msg}"

            ok, result = await self.analyzer.analyze_visual(frame, query=query)
            return result if ok else f"Camera visual analysis failed: {result}"


class CameraLiveAnalysisTool(BaseTool):
    name = "camera_live_analysis"
    description = (
        "Controls periodic camera analysis mode ('start', 'stop', or 'status'). "
        "In live analysis mode, Victor periodically samples camera frames (throttled to reduce CPU and bandwidth) "
        "to observe changes or monitor activities until stopped by the user."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["start", "stop", "status"],
                "description": "Action to perform: 'start' to begin periodic sampling, 'stop' to end, 'status' to check."
            },
            "interval_seconds": {
                "type": "number",
                "default": 4.0,
                "description": "Sampling interval in seconds between frame evaluations (minimum 2.0s, default 4.0s)."
            },
            "query": {
                "type": "string",
                "default": "Describe what the user is doing and any significant visual changes in front of the camera.",
                "description": "Instruction/focus for periodic analysis."
            }
        },
        "required": ["action"]
    }

    def __init__(self, live_analyzer: Optional[LiveCameraAnalyzer] = None) -> None:
        self.live_analyzer = live_analyzer or get_live_camera_analyzer()

    async def execute(self, args: dict) -> str:
        action = str(args.get("action", "status")).lower()
        if action == "start":
            interval = float(args.get("interval_seconds", 4.0))
            query = args.get("query")
            ok, msg = await self.live_analyzer.start(query=query, interval_seconds=interval)
            return msg
        elif action == "stop":
            ok, msg = await self.live_analyzer.stop()
            return msg
        else:
            active = self.live_analyzer.is_running
            return f"Camera live analysis is currently {'ACTIVE' if active else 'INACTIVE'}."


# ---------------------------------------------------------------------------
# 3. QR / Barcode & Visual Code Scanner
# ---------------------------------------------------------------------------

class VisualScanCodeTool(BaseTool):
    name = "visual_scan_code"
    description = (
        "Scans, detects, and decodes QR codes and common 1D/2D barcodes locally from the camera, "
        "current screen, or an image file. Identifies URLs, Wi-Fi credentials, contact cards (vCard), or plain text. "
        "If a URL is detected, it validates URL safety and reports the URL without blindly opening it."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": ["camera", "screen", "image_path"],
                "default": "camera",
                "description": "Source to scan: 'camera' (default), 'screen', or 'image_path'."
            },
            "image_path": {
                "type": "string",
                "description": "Optional local filepath if source is 'image_path'."
            }
        }
    }

    def __init__(
        self,
        scanner: Optional[CodeScanner] = None,
        driver: Optional[CameraDriver] = None
    ) -> None:
        self.scanner = scanner or get_code_scanner()
        self.driver = driver or get_camera_driver()

    async def execute(self, args: dict) -> str:
        source = str(args.get("source", "camera")).lower()
        image_path = args.get("image_path")

        if source == "image_path":
            if not image_path:
                return "Error: image_path is required when source is 'image_path'."
            results = self.scanner.decode_image_file(image_path)
            return self.scanner.format_scan_summary(results)

        elif source == "screen":
            try:
                screen_img = ImageGrab.grab()
                results = self.scanner.decode_pil_image(screen_img)
                return self.scanner.format_scan_summary(results)
            except Exception as e:
                return f"Failed to scan screen for codes: {str(e)}"

        else:
            # Camera frame
            ok, frame, msg = await self.driver.capture_frame(auto_open=True)
            if not ok or frame is None:
                return f"Could not acquire camera frame to scan for codes: {msg}"

            results = self.scanner.decode_cv2_image(frame)
            return self.scanner.format_scan_summary(results)


# ---------------------------------------------------------------------------
# 4. Visual Copy / Paste Tools
# ---------------------------------------------------------------------------

class VisualCopyTool(BaseTool):
    name = "visual_copy"
    description = (
        "Captures an image, camera frame, screenshot, or selected visual region, performs OCR text "
        "extraction if requested, and places either the extracted text or the captured image into the "
        "Windows clipboard so the user can paste it anywhere. Supports: 'copy this text', "
        "'copy the text from this image', 'copy this QR content', 'copy this image'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "source": {
                "type": "string",
                "enum": ["screen", "camera", "image_path", "qr_content"],
                "default": "screen",
                "description": "Visual source to capture: 'screen' (default), 'camera', 'image_path', or 'qr_content'."
            },
            "mode": {
                "type": "string",
                "enum": ["text", "image", "auto"],
                "default": "text",
                "description": "'text' to extract text via OCR and copy to clipboard; 'image' to place the visual image onto clipboard; 'auto' detects mode."
            },
            "image_path": {
                "type": "string",
                "description": "Optional local filepath if source is 'image_path'."
            },
            "region": {
                "type": "array",
                "items": {"type": "integer"},
                "description": "Optional crop region [x1, y1, x2, y2] in pixels."
            }
        }
    }

    def __init__(
        self,
        driver: Optional[CameraDriver] = None,
        analyzer: Optional[VisualAnalyzer] = None,
        scanner: Optional[CodeScanner] = None
    ) -> None:
        self.driver = driver or get_camera_driver()
        self.analyzer = analyzer or get_visual_analyzer()
        self.scanner = scanner or get_code_scanner()

    async def execute(self, args: dict) -> str:
        source = str(args.get("source", "screen")).lower()
        mode = str(args.get("mode", "text")).lower()
        image_path = args.get("image_path")
        region = args.get("region")

        # 1. Acquire visual source image
        image: Optional[Image.Image] = None

        if source == "qr_content":
            # Scan QR/barcode from camera/screen first, copy content to clipboard
            ok, frame, msg = await self.driver.capture_frame(auto_open=True)
            if ok and frame is not None:
                codes = self.scanner.decode_cv2_image(frame)
            else:
                codes = self.scanner.decode_pil_image(ImageGrab.grab())

            if not codes:
                return "No QR code or barcode found to copy content from."

            content = codes[0]["content"]
            copied = WindowsClipboardManager.set_text(content)
            if copied:
                return f"Successfully copied QR code content to clipboard: '{content}'"
            return "Failed to copy QR code content to Windows clipboard."

        if source == "image_path":
            if not image_path or not Path(image_path).exists():
                return f"Image file not found: {image_path}"
            image = Image.open(image_path)

        elif source == "camera":
            ok, frame, msg = await self.driver.capture_frame(auto_open=True)
            if not ok or frame is None:
                return f"Camera capture failed: {msg}"
            # Convert BGR to RGB PIL
            rgb = frame[:, :, ::-1]
            image = Image.fromarray(rgb)

        else:
            # Default: screen capture
            image = ImageGrab.grab()

        if region and len(region) == 4:
            x1, y1, x2, y2 = region
            image = image.crop((min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)))

        # 2. Mode handling
        if mode == "image":
            copied = WindowsClipboardManager.set_image(image)
            if copied:
                return f"Visual image ({image.width}x{image.height}) successfully copied to Windows clipboard."
            return "Failed to copy image to Windows clipboard."

        else:
            # Mode text: extract via OCR
            ok, text = await self.analyzer.extract_text_ocr(image)
            if not ok:
                return f"OCR text extraction failed: {text}"

            if not text or text.strip() == "No readable text was detected in the visual region.":
                return "No readable text was found in the captured visual area to copy."

            copied = WindowsClipboardManager.set_text(text)
            if copied:
                preview = text[:150] + ("..." if len(text) > 150 else "")
                return f"Successfully extracted and copied text to Windows clipboard:\n\n\"{preview}\""
            return f"Extracted text but failed to place it on the Windows clipboard: {text[:100]}"


class VisualPasteTool(BaseTool):
    name = "visual_paste"
    description = (
        "Pastes the copied text or image from the Windows clipboard into the active application "
        "by simulating paste (Ctrl+V). Use when the user says: 'paste the copied text', "
        "'paste it', 'paste the image'."
    )
    permission_level = PermissionLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "confirm_paste": {
                "type": "boolean",
                "default": True,
                "description": "Confirm paste execution."
            }
        }
    }

    async def execute(self, args: dict) -> str:
        # Check current clipboard contents for informative feedback
        clip_text = WindowsClipboardManager.get_text()
        success = WindowsClipboardManager.paste_into_active_window()
        if success:
            if clip_text:
                preview = clip_text[:60] + ("..." if len(clip_text) > 60 else "")
                return f"Successfully simulated paste into active window. (Clipboard content: '{preview}')"
            return "Successfully simulated paste into active window."
        return "Failed to simulate paste into the active window."
