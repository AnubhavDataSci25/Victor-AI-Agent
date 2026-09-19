import os
import subprocess
import ctypes
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Strict Whitelist to prevent arbitrary path execution
APP_WHITELIST = {
    "notepad": "notepad.exe",
    "stremio": r"C:\Users\anu52\AppData\Local\Programs\LNV\Stremio-4\stremio.exe",
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

    @staticmethod
    def click(x: int, y: int, button: str = "left") -> str:
        """Moves cursor to (x, y) and performs a mouse click."""
        try:
            x, y = int(x), int(y)
            button = button.lower()
            try:
                import win32api
                import win32con
                win32api.SetCursorPos((x, y))
                if button == "right":
                    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)
                elif button == "double":
                    import time
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                    time.sleep(0.05)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
                else:
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
                    win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)
            except ImportError:
                ctypes.windll.user32.SetCursorPos(x, y)
                if button == "right":
                    ctypes.windll.user32.mouse_event(0x0008, 0, 0, 0, 0)  # RIGHTDOWN
                    ctypes.windll.user32.mouse_event(0x0010, 0, 0, 0, 0)  # RIGHTUP
                elif button == "double":
                    import time
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
                    time.sleep(0.05)
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)
                else:
                    ctypes.windll.user32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
                    ctypes.windll.user32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP

            return f"Clicked {button} button at ({x}, {y})."
        except Exception as e:
            logger.error(f"Failed to click at ({x}, {y}): {e}")
            return f"Failed to click at ({x}, {y}). Error: {str(e)}"

    @staticmethod
    def scroll(direction: str = "down", amount: int = 3) -> str:
        """Scrolls the active window up or down."""
        try:
            direction = direction.lower()
            amount = int(amount)
            wheel_delta = 120 * amount if direction == "up" else -120 * amount
            try:
                import win32api
                import win32con
                win32api.mouse_event(win32con.MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)
            except ImportError:
                ctypes.windll.user32.mouse_event(0x0800, 0, 0, wheel_delta, 0)  # MOUSEEVENTF_WHEEL
            return f"Scrolled {direction} by {amount} steps."
        except Exception as e:
            logger.error(f"Failed to scroll {direction}: {e}")
            return f"Failed to scroll {direction}. Error: {str(e)}"

    @staticmethod
    def press_key(key: str) -> str:
        """Presses and releases a virtual key (e.g. enter, tab, escape, backspace)."""
        key_name = key.lower().strip()
        key_map = {
            "enter": 0x0D,
            "return": 0x0D,
            "tab": 0x09,
            "escape": 0x1B,
            "esc": 0x1B,
            "backspace": 0x08,
            "space": 0x20,
            "delete": 0x2E,
            "del": 0x2E,
            "up": 0x26,
            "down": 0x28,
            "left": 0x25,
            "right": 0x27,
            "home": 0x24,
            "end": 0x23,
            "pageup": 0x21,
            "pagedown": 0x22,
        }

        try:
            if key_name in key_map:
                WindowsComputerDriver.trigger_virtual_key(key_map[key_name])
                return f"Pressed key '{key}'."
            elif len(key) == 1:
                try:
                    import win32api
                    import win32con
                    win32api.keybd_event(0, ord(key), win32con.KEYEVENTF_UNICODE, 0)
                    win32api.keybd_event(0, ord(key), win32con.KEYEVENTF_UNICODE | win32con.KEYEVENTF_KEYUP, 0)
                except ImportError:
                    ctypes.windll.user32.keybd_event(0, ord(key), 0x0004, 0)
                    ctypes.windll.user32.keybd_event(0, ord(key), 0x0004 | 0x0002, 0)
                return f"Pressed key '{key}'."
            else:
                return f"Unsupported key: '{key}'."
        except Exception as e:
            logger.error(f"Failed to press key '{key}': {e}")
            return f"Failed to press key '{key}'. Error: {str(e)}"

    @staticmethod
    def type_text(text: str, click_x: Optional[int] = None, click_y: Optional[int] = None) -> str:
        """Types unicode text, optionally clicking (click_x, click_y) first to focus the field."""
        try:
            import time
            if click_x is not None and click_y is not None:
                WindowsComputerDriver.click(click_x, click_y, button="left")
                time.sleep(0.15)

            try:
                import win32api
                import win32con
                for char in text:
                    if char == "\n":
                        WindowsComputerDriver.trigger_virtual_key(0x0D)
                    else:
                        win32api.keybd_event(0, ord(char), win32con.KEYEVENTF_UNICODE, 0)
                        win32api.keybd_event(0, ord(char), win32con.KEYEVENTF_UNICODE | win32con.KEYEVENTF_KEYUP, 0)
                    time.sleep(0.01)
            except ImportError:
                for char in text:
                    if char == "\n":
                        WindowsComputerDriver.trigger_virtual_key(0x0D)
                    else:
                        ctypes.windll.user32.keybd_event(0, ord(char), 0x0004, 0)
                        ctypes.windll.user32.keybd_event(0, ord(char), 0x0004 | 0x0002, 0)
                    time.sleep(0.01)

            return f"Successfully typed {len(text)} characters."
        except Exception as e:
            logger.error(f"Failed to type text: {e}")
            return f"Failed to type text. Error: {str(e)}"