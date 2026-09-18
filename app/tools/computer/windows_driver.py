import os
import subprocess
import ctypes
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Strict Whitelist to prevent arbitrary path execution
APP_WHITELIST = {
    "notepad": "notepad.exe",
    "stremio": "stremio.exe",
    "calculator": "calc.exe",
    "command_prompt": "cmd.exe",
    "task_manager": "taskmgr.exe",
    "control_panel": "control.exe",
    "system_information": "msinfo32.exe",
    "on_screen_keyboard": "osk.exe"
}

# Virtual Key Codes for System Volume Control
VK_VOLUME_MUTE = 0xAD
VK_VOLUME_DOWN = 0xAE
VK_VOLUME_UP = 0xAF

class WindowsComputerDriver:
    @staticmethod
    def open_application(app_name: str) -> str:
        app_name_lower = app_name.lower().replace(" ", "_")
        if app_name_lower not in APP_WHITELIST:
            return f"Error: Application '{app_name}' is not in the approved whitelist."
        
        executable = APP_WHITELIST[app_name_lower]
        try:
            # shell=False prevents shell injection. 
            # DETACHED_PROCESS ensures Victor 2.0 does not hang waiting for the app to close.
            subprocess.Popen(
                [executable], 
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
            )
            return f"Successfully opened {app_name}."
        except Exception as e:
            logger.error(f"Failed to open {app_name}: {e}")
            return f"Failed to open {app_name}. Error: {str(e)}"

    @staticmethod
    def close_application(app_name: str) -> str:
        app_name_lower = app_name.lower().replace(" ", "_")
        if app_name_lower not in APP_WHITELIST:
            return f"Error: Application '{app_name}' is not in the approved whitelist."
            
        executable = APP_WHITELIST[app_name_lower]
        try:
            # taskkill is safe here because 'executable' is strictly fetched from the hardcoded dictionary
            subprocess.run(["taskkill", "/IM", executable, "/F"], check=True, capture_output=True)
            return f"Successfully closed {app_name}."
        except subprocess.CalledProcessError:
            return f"Could not close {app_name}. It may not be currently running."
        except Exception as e:
            logger.error(f"Failed to close {app_name}: {e}")
            return f"Failed to close {app_name}. Error: {str(e)}"

    @staticmethod
    def trigger_virtual_key(vk_code: int):
        """Triggers a secure virtual key press and release via ctypes."""
        ctypes.windll.user32.keybd_event(vk_code, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk_code, 0, 2, 0) # KEYEVENTF_KEYUP

    @staticmethod
    def adjust_volume(action: str, steps: int = 1) -> str:
        action = action.lower()
        if action == "mute":
            WindowsComputerDriver.trigger_virtual_key(VK_VOLUME_MUTE)
            return "Toggled system mute."
        elif action == "up":
            for _ in range(steps):
                WindowsComputerDriver.trigger_virtual_key(VK_VOLUME_UP)
            return f"Increased system volume by {steps} steps."
        elif action == "down":
            for _ in range(steps):
                WindowsComputerDriver.trigger_virtual_key(VK_VOLUME_DOWN)
            return f"Decreased system volume by {steps} steps."
        return "Unknown volume action requested."

    @staticmethod
    def lock_windows() -> str:
        try:
            ctypes.windll.user32.LockWorkStation()
            return "Windows workstation has been locked."
        except Exception as e:
            logger.error(f"Failed to lock Windows: {e}")
            return f"Failed to lock Windows. Error: {str(e)}"