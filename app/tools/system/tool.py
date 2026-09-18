import platform
import datetime
import logging
from app.tools.base import BaseTool
from app.tools.computer.windows_driver import WindowsComputerDriver

logger = logging.getLogger(__name__)

class SystemGetTimeTool(BaseTool):
    name = "system_get_time"
    description = "Gets the current system time and date."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        now = datetime.datetime.now()
        return now.strftime("Current System Time: %A, %B %d, %Y at %I:%M:%S %p")

class SystemGetInfoTool(BaseTool):
    name = "system_get_info"
    description = "Retrieves basic system information (OS, version, architecture)."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        try:
            os_name = platform.system()
            release = platform.release()
            arch = platform.machine()
            return f"System Info: {os_name} {release} ({arch})"
        except Exception as e:
            return f"Error retrieving system info: {str(e)}"

class SystemVolumeTool(BaseTool):
    name = "system_adjust_volume"
    description = "Adjusts the system volume (mute, up, or down). Provide 'steps' for up/down to define how many increments."
    parameters = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["mute", "up", "down"], "description": "The volume action to perform."},
            "steps": {"type": "integer", "description": "Number of volume increments (default is 1).", "default": 1}
        },
        "required": ["action"]
    }

    async def execute(self, args: dict) -> str:
        action = args.get("action", "")
        try:
            steps = int(args.get("steps", 1))
        except (ValueError, TypeError):
            steps = 1
        return WindowsComputerDriver.adjust_volume(action, steps)

class SystemLockWindowsTool(BaseTool):
    name = "system_lock_windows"
    description = "Locks the Windows operating system workstation securely. Note: This locks Windows itself, not Victor."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        return WindowsComputerDriver.lock_windows()

class SystemLockVictorTool(BaseTool):
    name = "lock_victor"
    description = "Locks the Victor agent session securely. Call this when the user explicitly asks to 'lock yourself', 'shut down', or 'lock the session'. This terminates the AI connection."
    parameters = {"type": "object", "properties": {}}

    async def execute(self, args: dict) -> str:
        # We return a simple confirmation; the Tool Gateway intercepts this to perform the actual shutdown.
        return "Initiating session lock protocol."