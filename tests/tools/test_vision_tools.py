"""
Comprehensive test suite for Victor's Camera & Visual Intelligence Module.

Covers:
1. CameraDriver lifecycle, capture, photo save, and video recording.
2. WindowsClipboardManager text and image copy/paste operations.
3. CodeScanner local QR/barcode detection, classification, and URL safety validation.
4. VisualAnalyzer OCR extraction and semantic visual analysis.
5. LiveCameraAnalyzer periodic sampled analysis and motion-aware throttling.
6. Concrete BaseTool implementations (CameraOpen, CameraClose, CameraCapture,
   CameraRecordVideo, CameraAnalyze, CameraLiveAnalysis, VisualScanCode,
   VisualCopy, VisualPaste).
7. DecisionEngine intent routing for visual and camera commands.
8. ToolGateway integration and execution.
"""

import asyncio
import io
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import numpy as np
from PIL import Image
import pytest

from app.tools.vision.camera_driver import CameraDriver, CameraState
from app.tools.vision.clipboard_manager import WindowsClipboardManager
from app.tools.vision.code_scanner import CodeScanner, CodeType, UrlSafetyValidator
from app.tools.vision.visual_analyzer import VisualAnalyzer
from app.tools.vision.live_analyzer import LiveCameraAnalyzer
from app.tools.vision.tools import (
    CameraAnalyzeTool,
    CameraCaptureTool,
    CameraCloseTool,
    CameraLiveAnalysisTool,
    CameraOpenTool,
    CameraRecordVideoTool,
    VisualCopyTool,
    VisualPasteTool,
    VisualScanCodeTool,
)
from app.gateway.tool_gateway import ToolGateway
from app.gateway.models import GatewayRequest, RiskLevel
from app.decision.engine import DecisionEngine


# ---------------------------------------------------------------------------
# 1. Camera Driver Lifecycle & Privacy Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_camera_driver_open_and_close():
    """Verify camera driver properly opens, updates state, and closes hardware."""
    driver = CameraDriver()

    with patch.object(driver, "_open_capture", return_value=True), \
         patch.object(driver, "_cap", MagicMock(isOpened=MagicMock(return_value=True))):
        ok, msg = await driver.open_camera(device_index=0)
        assert ok is True
        assert driver.state == CameraState.OPEN
        assert driver.is_open is True

        # Test duplicate open is idempotent
        ok2, msg2 = await driver.open_camera(device_index=0)
        assert ok2 is True
        assert "already active" in msg2

        # Close
        ok_close, msg_close = await driver.close_camera()
        assert ok_close is True
        assert driver.state == CameraState.CLOSED
        assert driver.is_open is False


@pytest.mark.asyncio
async def test_camera_driver_capture_frame():
    """Verify capturing a frame returns numpy array with valid dimensions."""
    driver = CameraDriver()
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.read.return_value = (True, dummy_frame)

    with patch.object(driver, "_open_capture", return_value=True), \
         patch.object(driver, "_cap", mock_cap):
        driver._state = CameraState.OPEN
        ok, frame, msg = await driver.capture_frame(auto_open=False)
        assert ok is True
        assert frame is not None
        assert frame.shape == (480, 640, 3)
        assert "640x480" in msg

    await driver.close_camera()


@pytest.mark.asyncio
async def test_camera_driver_save_photo(tmp_path):
    """Verify saving photo to disk creates a valid image file."""
    driver = CameraDriver()
    driver._pictures_dir = tmp_path
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    ok, file_path = await driver.save_photo(frame=dummy_frame, filename="test_capture.jpg")
    assert ok is True
    p = Path(file_path)
    assert p.exists()
    assert p.name == "test_capture.jpg"
    assert p.stat().st_size > 0


@pytest.mark.asyncio
async def test_camera_driver_ui_callback():
    """Verify state change callback notifies UI."""
    driver = CameraDriver()
    events = []

    def mock_ui_cb(evt):
        events.append(evt)

    driver.set_ui_callback(mock_ui_cb)
    with patch.object(driver, "_open_capture", return_value=True):
        await driver.open_camera(0)
        await driver.close_camera()

    assert any(e.get("state") == "OPEN" for e in events)
    assert any(e.get("state") == "CLOSED" for e in events)


# ---------------------------------------------------------------------------
# 2. Windows Clipboard Manager Tests
# ---------------------------------------------------------------------------

def test_clipboard_manager_text_copy_and_get():
    """Verify text copy and retrieval via Windows clipboard."""
    test_str = "Victor AI Assistant - Visual Intelligence Clipboard Test"
    ok = WindowsClipboardManager.set_text(test_str)
    assert ok is True

    retrieved = WindowsClipboardManager.get_text()
    assert retrieved == test_str


def test_clipboard_manager_image_copy_and_get():
    """Verify image copy and retrieval in CF_DIB format."""
    img = Image.new("RGB", (50, 50), color=(0, 128, 255))
    ok = WindowsClipboardManager.set_image(img)
    assert ok is True

    retrieved_img = WindowsClipboardManager.get_image()
    assert retrieved_img is not None
    assert retrieved_img.size == (50, 50)


def test_clipboard_manager_paste():
    """Verify paste triggers key events without raising exceptions."""
    with patch("ctypes.windll.user32.keybd_event") as mock_keybd:
        ok = WindowsClipboardManager.paste_into_active_window()
        assert ok is True
        assert mock_keybd.call_count == 4  # Ctrl down, V down, V up, Ctrl up


# ---------------------------------------------------------------------------
# 3. QR / Barcode & URL Safety Tests
# ---------------------------------------------------------------------------

def test_url_safety_validator_safe_urls():
    """Verify safe HTTP/HTTPS URLs pass validation."""
    safe_cases = [
        "https://github.com/AnubhavDataSci25",
        "https://www.google.com/search?q=victor",
        "http://example.com/page",
        "en.wikipedia.org/wiki/Artificial_intelligence",
    ]
    for url in safe_cases:
        res = UrlSafetyValidator.validate_url(url)
        assert res["is_safe"] is True
        assert res["status"] in ("SAFE", "CAUTION")
        assert res["domain"] != ""


def test_url_safety_validator_blocked_schemes():
    """Verify malicious or disallowed URL schemes are blocked."""
    dangerous_cases = [
        "javascript:alert(1)",
        "data:text/html,<script>alert('xss')</script>",
        "file:///C:/Windows/System32/calc.exe",
        "vbscript:msgbox(1)",
    ]
    for url in dangerous_cases:
        res = UrlSafetyValidator.validate_url(url)
        assert res["is_safe"] is False
        assert res["status"] == "BLOCKED"


def test_url_safety_validator_command_injection():
    """Verify shell metacharacters and control codes are blocked."""
    injection_cases = [
        "https://example.com; rm -rf /",
        "https://example.com/test?q=`whoami`",
        "https://example.com|calc.exe",
        "https://example.com\r\nX-Injected-Header: true",
    ]
    for url in injection_cases:
        res = UrlSafetyValidator.validate_url(url)
        assert res["is_safe"] is False
        assert res["status"] == "BLOCKED"


def test_code_scanner_classification():
    """Verify classification of Wi-Fi, Contact cards, URLs, and plain text."""
    scanner = CodeScanner()

    # Wi-Fi
    wifi_str = "WIFI:S:MyOfficeNetwork;T:WPA;P:SuperSecretPassword123;;;;"
    c_type, details = scanner.classify_code_content(wifi_str)
    assert c_type == CodeType.WIFI
    assert details["ssid"] == "MyOfficeNetwork"
    assert details["security"] == "WPA"
    assert details["has_password"] is True
    # Verify password is not printed in plaintext in details
    assert "password" not in details

    # Contact (MECARD)
    contact_str = "MECARD:N:Anubhav;TEL:+919876543210;EMAIL:anubhav@example.com;;"
    c_type, details = scanner.classify_code_content(contact_str)
    assert c_type == CodeType.CONTACT
    assert details["name"] == "Anubhav"
    assert details["phone"] == "+919876543210"

    # URL
    url_str = "https://github.com/torvalds/linux"
    c_type, details = scanner.classify_code_content(url_str)
    assert c_type == CodeType.URL
    assert details["domain"] == "github.com"
    assert details["is_safe"] is True

    # Plain text / barcode
    barcode_str = "8901030383829"
    c_type, details = scanner.classify_code_content(barcode_str)
    assert c_type == CodeType.TEXT
    assert details["text"] == barcode_str


def test_code_scanner_format_summary():
    """Verify formatted human-readable summary of scan results."""
    scanner = CodeScanner()
    scan_results = [
        {
            "format": "QR_CODE",
            "content": "https://example.com",
            "type": CodeType.URL,
            "details": {
                "is_safe": True,
                "domain": "example.com",
                "clean_url": "https://example.com",
                "status": "SAFE",
                "reason": "Valid HTTPS destination."
            }
        }
    ]
    summary = scanner.format_scan_summary(scan_results)
    assert "Found 1 code(s):" in summary
    assert "example.com" in summary
    assert "Ask user if they wish to open" in summary


# ---------------------------------------------------------------------------
# 4. Visual Analyzer & OCR Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_visual_analyzer_ocr():
    """Verify OCR extracts text cleanly using mocked Gemini client."""
    analyzer = VisualAnalyzer()
    img = Image.new("RGB", (100, 100), color="white")

    mock_resp = MagicMock()
    mock_resp.text = "VICTOR AI SYSTEM STATUS: ALL GREEN"

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch.object(analyzer, "_get_client", return_value=mock_client):
        ok, text = await analyzer.extract_text_ocr(img)
        assert ok is True
        assert "VICTOR AI SYSTEM STATUS" in text


@pytest.mark.asyncio
async def test_visual_analyzer_semantic_query():
    """Verify visual analysis answers queries like 'what am I doing?'."""
    analyzer = VisualAnalyzer()
    img = Image.new("RGB", (100, 100), color="white")

    mock_resp = MagicMock()
    mock_resp.text = "Sir, you appear to be reviewing code on your monitor."

    mock_client = MagicMock()
    mock_client.aio.models.generate_content = AsyncMock(return_value=mock_resp)

    with patch.object(analyzer, "_get_client", return_value=mock_client):
        ok, response = await analyzer.analyze_visual(img, query="What am I doing?")
        assert ok is True
        assert "reviewing code" in response


# ---------------------------------------------------------------------------
# 5. Live Camera Analyzer & Motion Throttling Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_live_camera_analyzer_start_and_stop():
    """Verify starting and stopping live periodic camera analysis."""
    analyzer = LiveCameraAnalyzer()
    mock_driver = MagicMock()
    mock_driver.is_open = True
    mock_driver.capture_frame = AsyncMock(return_value=(True, np.zeros((100, 100, 3), dtype=np.uint8), "ok"))
    analyzer.camera_driver = mock_driver

    ok, start_msg = await analyzer.start(query="Watch front view", interval_seconds=2.0)
    assert ok is True
    assert analyzer.is_running is True

    ok_stop, stop_msg = await analyzer.stop()
    assert ok_stop is True
    assert analyzer.is_running is False


def test_live_camera_analyzer_motion_detection():
    """Verify frame difference calculation detects significant visual changes."""
    frame1 = np.zeros((100, 100, 3), dtype=np.uint8)
    diff1, thumb1 = LiveCameraAnalyzer._compute_frame_difference(frame1, None)
    assert diff1 == 100.0  # Initial frame always flags change

    # Identical frame: zero difference
    frame2 = np.zeros((100, 100, 3), dtype=np.uint8)
    diff2, thumb2 = LiveCameraAnalyzer._compute_frame_difference(frame2, thumb1)
    assert diff2 == 0.0

    # Radically changed frame (white): large difference
    frame3 = np.ones((100, 100, 3), dtype=np.uint8) * 255
    diff3, thumb3 = LiveCameraAnalyzer._compute_frame_difference(frame3, thumb2)
    assert diff3 > 200.0


# ---------------------------------------------------------------------------
# 6. Concrete BaseTool Implementations Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_camera_open_and_close_tools():
    """Test CameraOpenTool and CameraCloseTool execution."""
    open_tool = CameraOpenTool()
    close_tool = CameraCloseTool()

    with patch.object(open_tool.driver, "open_camera", AsyncMock(return_value=(True, "Camera opened."))), \
         patch.object(close_tool.driver, "close_camera", AsyncMock(return_value=(True, "Camera closed."))):
        res_open = await open_tool.execute({})
        assert "Camera opened" in res_open

        res_close = await close_tool.execute({})
        assert "Camera closed" in res_close


@pytest.mark.asyncio
async def test_camera_capture_tool():
    """Test CameraCaptureTool with temporary and permanent save modes."""
    capture_tool = CameraCaptureTool()

    # Temporary capture (save=False)
    dummy_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    with patch.object(capture_tool.driver, "capture_frame", AsyncMock(return_value=(True, dummy_frame, "ok"))):
        res = await capture_tool.execute({"save": False})
        assert "640x480" in res

    # Permanent save (save=True)
    with patch.object(capture_tool.driver, "save_photo", AsyncMock(return_value=(True, "C:/Pictures/photo.jpg"))):
        res_save = await capture_tool.execute({"save": True})
        assert "photo.jpg" in res_save


@pytest.mark.asyncio
async def test_camera_analyze_tool():
    """Test CameraAnalyzeTool executing visual analysis from camera source."""
    tool = CameraAnalyzeTool()
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    with patch.object(tool.driver, "capture_frame", AsyncMock(return_value=(True, dummy_frame, "ok"))), \
         patch.object(tool.analyzer, "analyze_visual", AsyncMock(return_value=(True, "Sir, you are holding a coffee mug."))):
        res = await tool.execute({"query": "What is in front of me?"})
        assert "coffee mug" in res


@pytest.mark.asyncio
async def test_visual_scan_code_tool():
    """Test VisualScanCodeTool scanning for QR/barcodes."""
    tool = VisualScanCodeTool()
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)

    mock_scan_res = [{
        "format": "QR_CODE",
        "content": "https://victor.ai",
        "type": CodeType.URL,
        "details": {
            "is_safe": True,
            "domain": "victor.ai",
            "clean_url": "https://victor.ai",
            "status": "SAFE",
            "reason": "Valid HTTPS target."
        }
    }]

    with patch.object(tool.driver, "capture_frame", AsyncMock(return_value=(True, dummy_frame, "ok"))), \
         patch.object(tool.scanner, "decode_cv2_image", return_value=mock_scan_res):
        res = await tool.execute({"source": "camera"})
        assert "victor.ai" in res
        assert "Found 1 code" in res


@pytest.mark.asyncio
async def test_visual_copy_tool_text():
    """Test VisualCopyTool performing OCR and copying text to Windows clipboard."""
    tool = VisualCopyTool()
    dummy_img = Image.new("RGB", (100, 100), color="white")

    with patch("PIL.ImageGrab.grab", return_value=dummy_img), \
         patch.object(tool.analyzer, "extract_text_ocr", AsyncMock(return_value=(True, "Extracted Invoice #12345"))), \
         patch.object(WindowsClipboardManager, "set_text", return_value=True):
        res = await tool.execute({"source": "screen", "mode": "text"})
        assert "Invoice #12345" in res
        assert "Successfully extracted and copied text" in res


@pytest.mark.asyncio
async def test_visual_copy_tool_image():
    """Test VisualCopyTool placing captured visual image onto Windows clipboard."""
    tool = VisualCopyTool()
    dummy_img = Image.new("RGB", (100, 100), color="white")

    with patch("PIL.ImageGrab.grab", return_value=dummy_img), \
         patch.object(WindowsClipboardManager, "set_image", return_value=True):
        res = await tool.execute({"source": "screen", "mode": "image"})
        assert "100x100" in res
        assert "successfully copied to Windows clipboard" in res


@pytest.mark.asyncio
async def test_visual_paste_tool():
    """Test VisualPasteTool simulating Ctrl+V paste."""
    tool = VisualPasteTool()

    with patch.object(WindowsClipboardManager, "get_text", return_value="Hello Victor"), \
         patch.object(WindowsClipboardManager, "paste_into_active_window", return_value=True):
        res = await tool.execute({})
        assert "Successfully simulated paste" in res
        assert "Hello Victor" in res


# ---------------------------------------------------------------------------
# 7. DecisionEngine Intent Routing Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_decision_engine_camera_and_vision_intents():
    """Verify DecisionEngine routes visual commands to camera_vision and visual_clipboard."""
    engine = DecisionEngine()

    camera_commands = [
        "Victor, open camera",
        "take a photo",
        "capture this",
        "record a video",
        "what am I doing?",
        "analyze what is in front of me",
        "close camera",
        "start camera analysis",
    ]
    for cmd in camera_commands:
        decision = await engine.route_intent(cmd)
        assert decision.intent == "camera_vision", f"Failed to route '{cmd}' to camera_vision"

    qr_commands = [
        "scan this qr code",
        "read qr code",
        "detect barcode on screen",
    ]
    for cmd in qr_commands:
        decision = await engine.route_intent(cmd)
        assert decision.intent == "camera_vision", f"Failed to route '{cmd}' to camera_vision"

    copy_paste_commands = [
        "Victor, copy this text",
        "copy text from this image",
        "extract text",
        "paste the copied text",
        "paste it",
    ]
    for cmd in copy_paste_commands:
        decision = await engine.route_intent(cmd)
        assert decision.intent == "visual_clipboard", f"Failed to route '{cmd}' to visual_clipboard"


# ---------------------------------------------------------------------------
# 8. ToolGateway Integration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tool_gateway_visual_tool_execution():
    """Verify ToolGateway authenticates, evaluates risk, and executes visual tools."""
    gateway = ToolGateway()

    # Mock authenticated session
    mock_session = MagicMock()
    mock_session.is_authenticated.return_value = True
    mock_session.state.value = "ACTIVE"

    # Test camera_open through Gateway
    with patch("app.tools.vision.camera_driver.CameraDriver.open_camera", AsyncMock(return_value=(True, "Camera opened."))):
        req = GatewayRequest(tool_name="camera_open", arguments={"device_index": 0})
        res = await gateway.execute(req, session_manager=mock_session)
        assert res.success is True
        assert "Camera opened" in res.result

    # Test visual_scan_code through Gateway
    dummy_frame = np.zeros((100, 100, 3), dtype=np.uint8)
    with patch("app.tools.vision.camera_driver.CameraDriver.capture_frame", AsyncMock(return_value=(True, dummy_frame, "ok"))), \
         patch("app.tools.vision.code_scanner.CodeScanner.decode_cv2_image", return_value=[]):
        req = GatewayRequest(tool_name="visual_scan_code", arguments={"source": "camera"})
        res = await gateway.execute(req, session_manager=mock_session)
        assert res.success is True
        assert "No QR codes or barcodes were detected" in res.result
