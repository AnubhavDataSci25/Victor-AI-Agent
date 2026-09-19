"""
Tests for Victor's Screen Understanding & Action capability.

Covers:
- ScreenUnderstandTool and ScreenAnalyzer
- Coordinate scaling from normalized [0, 1000] bounding boxes to pixel space
- Answering user queries: 'What is on my screen?', 'Summarize this page',
  'What error am I getting?', 'Is there a form here?'
- Form detection and enforcement of the Form Safety Policy
- Computer control tools (click, type_text, press_key, scroll)
- Form submission safety gating (confirmation required)
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.tools.screen.analyzer import ScreenAnalyzer
from app.tools.screen.tool import ScreenUnderstandTool
from app.tools.computer.tool import (
    ComputerClickTool,
    ComputerTypeTextTool,
    ComputerPressKeyTool,
    ComputerScrollTool,
    ComputerSubmitFormTool,
    ComputerTakeScreenshotTool,
)
from app.tools.computer.windows_driver import WindowsComputerDriver
from app.tools.tool_setup import build_tool_registry


# ---------------------------------------------------------------------------
# 1. Coordinate Scaling & Extraction Tests
# ---------------------------------------------------------------------------

def test_scale_box_to_pixels():
    """Verify conversion of normalized [ymin, xmin, ymax, xmax] to pixel center coordinates."""
    width, height = 1920, 1080
    # Center should be x=500/1000*1920=960, y=250/1000*1080=270
    box = [200, 400, 300, 600]
    coords = ScreenAnalyzer._scale_box_to_pixels(box, width, height)
    assert coords["x"] == 960
    assert coords["y"] == 270

    # Corners
    top_left = ScreenAnalyzer._scale_box_to_pixels([0, 0, 100, 100], width, height)
    assert top_left["x"] == int(50 / 1000 * 1920)
    assert top_left["y"] == int(50 / 1000 * 1080)


def test_extract_screenshot_path(tmp_path):
    """Verify extracting saved screenshot path from ComputerTakeScreenshotTool output string."""
    fake_img = tmp_path / "victor_screenshot_123.png"
    fake_img.write_text("dummy")

    output_str = f"Screenshot successfully taken and saved to {fake_img}."
    extracted = ScreenAnalyzer._extract_screenshot_path(output_str)
    assert extracted == str(fake_img)


def test_parse_json_response_clean():
    """Verify parsing clean JSON and markdown code-fenced JSON."""
    analyzer = ScreenAnalyzer()

    # Plain JSON
    raw_json = json.dumps({"summary": "Dashboard view", "detected_errors": []})
    parsed = analyzer._parse_json_response(raw_json)
    assert parsed["summary"] == "Dashboard view"

    # Markdown fenced JSON
    fenced_json = f"```json\n{raw_json}\n```"
    parsed_fenced = analyzer._parse_json_response(fenced_json)
    assert parsed_fenced["summary"] == "Dashboard view"

    # Malformed text fallback
    fallback = analyzer._parse_json_response("This is not JSON at all.")
    assert "summary" in fallback
    assert fallback["summary"] == "This is not JSON at all."


# ---------------------------------------------------------------------------
# 2. Screen Understanding Queries & Form Detection Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_screen_understand_general_summary(tmp_path):
    """Test 'What is on my screen?' returns active application and summary."""
    fake_img = tmp_path / "victor_screenshot_999.png"
    from PIL import Image
    Image.new("RGB", (800, 600), color="white").save(fake_img)

    mock_gemini_response = MagicMock()
    mock_gemini_response.text = json.dumps({
        "summary": "Visual Studio Code editor is open with Python code.",
        "active_application": "Visual Studio Code",
        "visible_text": "def test_app(): pass",
        "detected_errors": [],
        "form": {"form_detected": False, "fields": []},
        "interactive_elements": [
            {
                "id": "btn_run",
                "element_type": "button",
                "label": "Run Code",
                "box_2d": [50, 100, 90, 180]
            }
        ],
        "answer_to_query": "Your screen shows Visual Studio Code open with Python code."
    })

    analyzer = ScreenAnalyzer()
    analyzer._extract_screenshot_path = MagicMock(return_value=str(fake_img))

    with patch.object(analyzer, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_gemini_response)
        mock_get_client.return_value = mock_client

        tool = ScreenUnderstandTool(analyzer=analyzer)
        result = await tool.execute({"query": "What is on my screen?"})

        assert "Visual Studio Code" in result
        assert "Summary" in result
        assert "Run Code" in result
        assert "Actionable UI Elements" in result


@pytest.mark.asyncio
async def test_screen_understand_error_detection(tmp_path):
    """Test 'What error am I getting?' highlights detected errors."""
    fake_img = tmp_path / "victor_screenshot_err.png"
    from PIL import Image
    Image.new("RGB", (800, 600), color="white").save(fake_img)

    mock_gemini_response = MagicMock()
    mock_gemini_response.text = json.dumps({
        "summary": "A fatal exception dialog is displayed on screen.",
        "active_application": "System Error Dialog",
        "visible_text": "Error 0x80004005: Unspecified error occurred",
        "detected_errors": [
            "Error 0x80004005: Unspecified error occurred in module kernel32.dll",
            "Connection timeout to server 192.168.1.1"
        ],
        "form": {"form_detected": False, "fields": []},
        "interactive_elements": [],
        "answer_to_query": "You are seeing an error dialog with code 0x80004005."
    })

    analyzer = ScreenAnalyzer()
    analyzer._extract_screenshot_path = MagicMock(return_value=str(fake_img))

    with patch.object(analyzer, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_gemini_response)
        mock_get_client.return_value = mock_client

        tool = ScreenUnderstandTool(analyzer=analyzer)
        result = await tool.execute({"query": "What error am I getting?"})

        assert "Detected Errors/Warnings" in result
        assert "0x80004005" in result
        assert "kernel32.dll" in result


@pytest.mark.asyncio
async def test_screen_understand_form_detection_and_safety_notice(tmp_path):
    """Test 'Is there a form here?' detects form, lists fields, and enforces FORM SAFETY POLICY."""
    fake_img = tmp_path / "victor_screenshot_form.png"
    from PIL import Image
    Image.new("RGB", (1000, 800), color="white").save(fake_img)

    mock_gemini_response = MagicMock()
    mock_gemini_response.text = json.dumps({
        "summary": "A user login portal is open.",
        "active_application": "Google Chrome",
        "visible_text": "Sign In to your account",
        "detected_errors": [],
        "form": {
            "form_detected": True,
            "form_title_or_purpose": "User Login Form",
            "fields": [
                {
                    "field_name": "username",
                    "field_label": "Email Address",
                    "field_type": "email",
                    "current_value": None,
                    "is_required": True,
                    "box_2d": [300, 400, 350, 600]
                },
                {
                    "field_name": "password",
                    "field_label": "Password",
                    "field_type": "password",
                    "current_value": None,
                    "is_required": True,
                    "box_2d": [400, 400, 450, 600]
                }
            ],
            "submit_button": {
                "label": "Sign In",
                "box_2d": [500, 450, 540, 550]
            }
        },
        "interactive_elements": [],
        "answer_to_query": "Yes, there is a login form on the page with Email Address and Password fields."
    })

    analyzer = ScreenAnalyzer()
    analyzer._extract_screenshot_path = MagicMock(return_value=str(fake_img))

    with patch.object(analyzer, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_client.aio.models.generate_content = AsyncMock(return_value=mock_gemini_response)
        mock_get_client.return_value = mock_client

        tool = ScreenUnderstandTool(analyzer=analyzer)
        result = await tool.execute({"query": "Is there a form here?"})

        # Verify form detection output
        assert "Form Detected (User Login Form)" in result
        assert "Email Address [email]" in result
        assert "Password [password]" in result
        assert "Submit Button: 'Sign In'" in result

        # Verify pixel coordinate mapping (width=1000, height=800)
        assert "x=500" in result
        assert "y=260" in result

        # Verify strict Form Safety Policy notice is included
        assert "FORM SAFETY POLICY" in result
        assert "ask the user for the required information" in result
        assert "explicit user confirmation" in result


# ---------------------------------------------------------------------------
# 3. Computer Control Tools Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_computer_click_tool():
    """Verify ComputerClickTool delegates to WindowsComputerDriver.click."""
    with patch.object(WindowsComputerDriver, "click", return_value="Clicked left button at (100, 200).") as mock_click:
        tool = ComputerClickTool()
        res = await tool.execute({"x": 100, "y": 200, "button": "left"})
        assert "Clicked left button at (100, 200)" in res
        mock_click.assert_called_once_with(100, 200, button="left")


@pytest.mark.asyncio
async def test_computer_type_text_tool():
    """Verify ComputerTypeTextTool delegates to WindowsComputerDriver.type_text."""
    with patch.object(WindowsComputerDriver, "type_text", return_value="Successfully typed 10 characters.") as mock_type:
        tool = ComputerTypeTextTool()
        res = await tool.execute({"text": "test input", "click_x": 150, "click_y": 250})
        assert "Successfully typed 10 characters" in res
        mock_type.assert_called_once_with("test input", click_x=150, click_y=250)


@pytest.mark.asyncio
async def test_computer_scroll_tool():
    """Verify ComputerScrollTool delegates to WindowsComputerDriver.scroll."""
    with patch.object(WindowsComputerDriver, "scroll", return_value="Scrolled down by 5 steps.") as mock_scroll:
        tool = ComputerScrollTool()
        res = await tool.execute({"direction": "down", "amount": 5})
        assert "Scrolled down by 5 steps" in res
        mock_scroll.assert_called_once_with(direction="down", amount=5)


@pytest.mark.asyncio
async def test_computer_press_key_tool_normal():
    """Verify ComputerPressKeyTool handles normal keys."""
    with patch.object(WindowsComputerDriver, "press_key", return_value="Pressed key 'tab'.") as mock_press:
        tool = ComputerPressKeyTool()
        res = await tool.execute({"key": "tab"})
        assert "Pressed key 'tab'" in res
        mock_press.assert_called_once_with("tab")


@pytest.mark.asyncio
async def test_computer_press_key_tool_form_submission_safety():
    """Verify ComputerPressKeyTool enforces confirmation when is_form_submission is True."""
    tool = ComputerPressKeyTool()

    # Unconfirmed attempt
    unconfirmed = await tool.execute({"key": "enter", "is_form_submission": True, "user_confirmed": False})
    assert "CONFIRMATION REQUIRED" in unconfirmed

    # Confirmed attempt
    with patch.object(WindowsComputerDriver, "press_key", return_value="Pressed key 'enter'."):
        confirmed = await tool.execute({"key": "enter", "is_form_submission": True, "user_confirmed": True})
        assert "Pressed key 'enter'" in confirmed


@pytest.mark.asyncio
async def test_computer_submit_form_safety():
    """Verify ComputerSubmitFormTool strictly enforces user_confirmed."""
    tool = ComputerSubmitFormTool()

    # 1. Unconfirmed attempt: Must refuse to submit
    res_unconfirmed = await tool.execute({"user_confirmed": False})
    assert "CONFIRMATION REQUIRED" in res_unconfirmed
    assert "Are you ready for me to submit this form?" in res_unconfirmed

    # 2. Confirmed attempt with coordinates: Clicks submit button
    with patch.object(WindowsComputerDriver, "click", return_value="Clicked left button."):
        res_confirmed = await tool.execute({
            "user_confirmed": True,
            "submit_x": 500,
            "submit_y": 600
        })
        assert "Form submitted successfully by clicking submit button at (500, 600)" in res_confirmed

    # 3. Confirmed attempt without coordinates: Presses Enter
    with patch.object(WindowsComputerDriver, "press_key", return_value="Pressed key 'enter'."):
        res_enter = await tool.execute({"user_confirmed": True})
        assert "Form submitted successfully by pressing Enter" in res_enter


# ---------------------------------------------------------------------------
# 4. Registry Integration Test
# ---------------------------------------------------------------------------

def test_tool_registry_contains_screen_and_action_tools():
    """Verify all new tools are registered in the Victor tool registry."""
    registry = build_tool_registry()
    tools = registry.list_tools()
    tool_names = [t["name"] for t in tools]

    expected = [
        "screen_understand",
        "computer_take_screenshot",
        "computer_click",
        "computer_type_text",
        "computer_press_key",
        "computer_scroll",
        "computer_submit_form",
    ]

    for exp in expected:
        assert exp in tool_names, f"Expected tool '{exp}' to be registered in ToolRegistry"
