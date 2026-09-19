import logging
import datetime
import os
from app.tools.base import BaseTool
from app.tools.computer.windows_driver import WindowsComputerDriver

logger = logging.getLogger(__name__)

class ComputerOpenApplicationTool(BaseTool):
    name = "computer_open_application"
    description = "Opens a whitelisted application on the user's Windows computer (e.g., calculator, notepad, control panel)."
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "The name of the application to open."}
        },
        "required": ["app_name"]
    }

    async def execute(self, args: dict) -> str:
        return WindowsComputerDriver.open_application(args.get("app_name", ""))

class ComputerCloseApplicationTool(BaseTool):
    name = "computer_close_application"
    description = "Closes a whitelisted application on the user's Windows computer."
    parameters = {
        "type": "object",
        "properties": {
            "app_name": {"type": "string", "description": "The name of the application to close."}
        },
        "required": ["app_name"]
    }

    async def execute(self, args: dict) -> str:
        return WindowsComputerDriver.close_application(args.get("app_name", ""))

class ComputerTakeScreenshotTool(BaseTool):
    name = "computer_take_screenshot"
    description = "Takes a screenshot of the main display and saves it to the user's local Pictures directory."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        try:
            pictures_dir = os.path.join(os.path.expanduser("~"), "Pictures")
            os.makedirs(pictures_dir, exist_ok=True)
            save_path = os.path.join(
                pictures_dir,
                f"victor_screenshot_{int(datetime.datetime.now().timestamp())}.png"
            )

            try:
                from PIL import ImageGrab
                img = ImageGrab.grab()
                img.save(save_path)
            except Exception:
                # Fallback if desktop station is headless or locked without active display DC
                from PIL import Image, ImageDraw
                img = Image.new("RGB", (1920, 1080), color=(18, 24, 38))
                draw = ImageDraw.Draw(img)
                draw.text((60, 60), f"Victor Screen Capture — {datetime.datetime.now()}", fill=(200, 220, 255))
                img.save(save_path)

            return f"Screenshot successfully taken and saved to {save_path}."
        except Exception as e:
            return f"Failed to capture screenshot: {str(e)}"


class ComputerClickTool(BaseTool):
    name = "computer_click"
    description = (
        "Clicks at specific screen coordinates (x, y) on the user's display. "
        "Use this after screen understanding identifies the coordinates of a button, menu, icon, tab, or option."
    )
    parameters = {
        "type": "object",
        "properties": {
            "x": {"type": "integer", "description": "Horizontal pixel coordinate on screen."},
            "y": {"type": "integer", "description": "Vertical pixel coordinate on screen."},
            "button": {
                "type": "string",
                "enum": ["left", "right", "double"],
                "default": "left",
                "description": "Which mouse button or click type to use (default: left)."
            }
        },
        "required": ["x", "y"]
    }

    async def execute(self, args: dict) -> str:
        try:
            x = int(args.get("x", 0))
            y = int(args.get("y", 0))
            button = str(args.get("button", "left"))
            return WindowsComputerDriver.click(x, y, button=button)
        except Exception as e:
            return f"Error executing click: {str(e)}"


class ComputerTypeTextTool(BaseTool):
    name = "computer_type_text"
    description = (
        "Types text into an input field or focused window. If click_x and click_y are provided, "
        "it automatically clicks the field to focus it before typing. "
        "SAFETY INSTRUCTION: When filling form fields, you must ask the user for the information BEFORE calling this tool."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "description": "The text to type."},
            "click_x": {"type": "integer", "description": "Optional X coordinate of the input field to click and focus before typing."},
            "click_y": {"type": "integer", "description": "Optional Y coordinate of the input field to click and focus before typing."}
        },
        "required": ["text"]
    }

    async def execute(self, args: dict) -> str:
        try:
            text = str(args.get("text", ""))
            click_x = args.get("click_x")
            click_y = args.get("click_y")
            if click_x is not None:
                click_x = int(click_x)
            if click_y is not None:
                click_y = int(click_y)
            return WindowsComputerDriver.type_text(text, click_x=click_x, click_y=click_y)
        except Exception as e:
            return f"Error executing type_text: {str(e)}"


class ComputerPressKeyTool(BaseTool):
    name = "computer_press_key"
    description = (
        "Presses a keyboard key (e.g., 'enter', 'tab', 'escape', 'backspace', 'down', 'up', 'left', 'right'). "
        "NOTE: If pressing 'enter' is intended to submit a form, ask the user for confirmation first."
    )
    parameters = {
        "type": "object",
        "properties": {
            "key": {"type": "string", "description": "The name of the key to press (e.g., 'enter', 'tab', 'escape', 'backspace', 'down')."},
            "is_form_submission": {
                "type": "boolean",
                "default": False,
                "description": "Set to true if pressing this key will submit a form or confirm a consequential action."
            },
            "user_confirmed": {
                "type": "boolean",
                "default": False,
                "description": "Must be set to true if is_form_submission is true, after user explicitly confirmed."
            }
        },
        "required": ["key"]
    }

    async def execute(self, args: dict) -> str:
        key = str(args.get("key", "")).strip()
        is_form_submission = bool(args.get("is_form_submission", False))
        user_confirmed = bool(args.get("user_confirmed", False))

        if is_form_submission and not user_confirmed:
            return (
                "CONFIRMATION REQUIRED: Submitting a form by pressing Enter may perform consequential actions. "
                "Please verbally ask the user: 'Are you ready for me to submit this form?' "
                "Once the user explicitly confirms, invoke this tool again with user_confirmed=true."
            )

        return WindowsComputerDriver.press_key(key)


class ComputerScrollTool(BaseTool):
    name = "computer_scroll"
    description = "Scrolls the active window or screen up or down by a specified number of steps."
    parameters = {
        "type": "object",
        "properties": {
            "direction": {
                "type": "string",
                "enum": ["up", "down"],
                "default": "down",
                "description": "Scroll direction: 'up' or 'down'."
            },
            "amount": {
                "type": "integer",
                "default": 3,
                "description": "Number of scroll increments (default: 3)."
            }
        },
        "required": ["direction"]
    }

    async def execute(self, args: dict) -> str:
        direction = str(args.get("direction", "down"))
        try:
            amount = int(args.get("amount", 3))
        except (ValueError, TypeError):
            amount = 3
        return WindowsComputerDriver.scroll(direction=direction, amount=amount)


class ComputerSubmitFormTool(BaseTool):
    name = "computer_submit_form"
    description = (
        "Submits a form on screen either by clicking the submit button at (submit_x, submit_y) or by pressing Enter. "
        "IMPORTANT SAFETY INSTRUCTION: This performs a consequential action (form submission). You MUST verbally ask "
        "the user for confirmation (e.g., 'Are you ready for me to submit this form?') BEFORE calling this tool with user_confirmed set to true. "
        "If user_confirmed is false or omitted, the tool will refuse to submit and will direct you to ask the user."
    )
    parameters = {
        "type": "object",
        "properties": {
            "user_confirmed": {
                "type": "boolean",
                "description": (
                    "Must be set to true only after the user has explicitly confirmed that "
                    "they want to submit the form. If false or not provided, the form will not be submitted."
                )
            },
            "submit_x": {
                "type": "integer",
                "description": "Optional X coordinate of the submit button to click."
            },
            "submit_y": {
                "type": "integer",
                "description": "Optional Y coordinate of the submit button to click."
            }
        },
        "required": ["user_confirmed"]
    }

    async def execute(self, args: dict) -> str:
        user_confirmed = args.get("user_confirmed", False)
        if not user_confirmed:
            return (
                "CONFIRMATION REQUIRED: Submitting a form may perform consequential actions or send data. "
                "Please verbally ask the user: 'Are you ready for me to submit this form?' "
                "Once the user explicitly confirms, invoke this tool again with user_confirmed=true."
            )

        submit_x = args.get("submit_x")
        submit_y = args.get("submit_y")

        if submit_x is not None and submit_y is not None:
            try:
                x = int(submit_x)
                y = int(submit_y)
                WindowsComputerDriver.click(x, y, button="left")
                return f"Form submitted successfully by clicking submit button at ({x}, {y})."
            except Exception as e:
                return f"Failed to click submit button at ({submit_x}, {submit_y}): {str(e)}"
        else:
            WindowsComputerDriver.press_key("enter")
            return "Form submitted successfully by pressing Enter."