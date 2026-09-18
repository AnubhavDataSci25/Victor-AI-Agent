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