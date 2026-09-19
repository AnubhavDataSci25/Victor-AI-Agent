"""
VS Code automation integration for Victor 2.0.

Locates the VS Code executable on Windows and opens workspaces and files visibly
using detached process execution.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from app.logging import get_logger

logger = get_logger("coding.vscode")


class VSCodeLauncher:
    """Manages launching VS Code with workspaces and specific files."""

    def __init__(self, custom_path: str | None = None) -> None:
        self.code_executable = self._find_code_executable(custom_path)

    @classmethod
    def _find_code_executable(cls, custom_path: str | None = None) -> str | None:
        if custom_path and Path(custom_path).exists():
            return custom_path

        # Check PATH
        which_code = shutil.which("code") or shutil.which("code.cmd")
        if which_code:
            return which_code

        # Common Windows paths
        common_candidates = [
            r"E:\VS Code\Microsoft VS Code\bin\code.cmd",
            r"E:\VS Code\Microsoft VS Code\code.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\bin\code.cmd"),
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\code.exe"),
            r"C:\Program Files\Microsoft VS Code\bin\code.cmd",
            r"C:\Program Files\Microsoft VS Code\code.exe",
            r"C:\Program Files (x86)\Microsoft VS Code\bin\code.cmd",
        ]

        for cand in common_candidates:
            if Path(cand).exists():
                return str(Path(cand).resolve())

        return None

    def is_available(self) -> bool:
        return self.code_executable is not None

    def open_workspace(self, workspace_path: Path) -> tuple[bool, str]:
        """Opens the specified workspace folder in VS Code."""
        if not self.code_executable:
            return False, "VS Code executable ('code') was not found on this system."

        if not workspace_path.exists():
            return False, f"Workspace path does not exist: {workspace_path}"

        try:
            cmd = [self.code_executable, str(workspace_path)]
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = (
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )

            # If it's a .cmd on Windows, run with shell=True or call directly
            use_shell = sys.platform == "win32" and self.code_executable.lower().endswith((".cmd", ".bat"))
            subprocess.Popen(
                cmd,
                creationflags=creation_flags if not use_shell else 0,
                shell=use_shell,
            )
            logger.info(f"Opened VS Code workspace: {workspace_path}")
            return True, f"VS Code opened for workspace: {workspace_path}"
        except Exception as exc:
            logger.error(f"Failed to launch VS Code for {workspace_path}: {exc}")
            return False, f"Failed to launch VS Code: {exc}"

    def open_file(self, file_path: Path, line: int | None = None) -> tuple[bool, str]:
        """Opens a specific file in VS Code, optionally at a target line."""
        if not self.code_executable:
            return False, "VS Code executable ('code') was not found on this system."

        try:
            target = f"{file_path}:{line}" if line else str(file_path)
            cmd = [self.code_executable, "-g", target]
            creation_flags = 0
            if sys.platform == "win32":
                creation_flags = (
                    subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                )

            use_shell = sys.platform == "win32" and self.code_executable.lower().endswith((".cmd", ".bat"))
            subprocess.Popen(
                cmd,
                creationflags=creation_flags if not use_shell else 0,
                shell=use_shell,
            )
            logger.info(f"Opened file in VS Code: {target}")
            return True, f"Opened {file_path.name} in VS Code."
        except Exception as exc:
            logger.error(f"Failed to open file in VS Code: {exc}")
            return False, f"Failed to open file in VS Code: {exc}"

    def close_workspace_window(self, workspace_path_or_name: str | Path) -> tuple[bool, str]:
        """
        Locates and gracefully closes the VS Code window associated with the specified workspace.
        Uses Windows WM_CLOSE message to close only that specific window without killing other
        VS Code instances or unrelated applications.
        """
        if sys.platform != "win32":
            return False, "Closing specific VS Code windows is only supported on Windows in this build."

        workspace_name = Path(workspace_path_or_name).name.lower()
        closed_count = 0

        try:
            import win32gui
            import win32con

            def enum_windows_callback(hwnd, _):
                nonlocal closed_count
                if not win32gui.IsWindow(hwnd) or not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd).lower()
                # VS Code window title pattern: "[filename] - [workspace_name] - Visual Studio Code"
                # or "[workspace_name] - Visual Studio Code"
                if ("visual studio code" in title or " - code" in title) and workspace_name in title:
                    logger.info(f"Sending WM_CLOSE to VS Code window: {win32gui.GetWindowText(hwnd)} (hwnd: {hwnd})")
                    win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
                    closed_count += 1

            win32gui.EnumWindows(enum_windows_callback, None)

        except ImportError:
            # Fallback using ctypes
            import ctypes
            from ctypes import wintypes

            user32 = ctypes.windll.user32
            WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

            def enum_proc(hwnd, _):
                nonlocal closed_count
                if not user32.IsWindowVisible(hwnd):
                    return True
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    title = buff.value.lower()
                    if ("visual studio code" in title or " - code" in title) and workspace_name in title:
                        logger.info(f"Sending WM_CLOSE to VS Code window (ctypes): {buff.value}")
                        user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE = 0x0010
                        closed_count += 1
                return True

            user32.EnumWindows(WNDENUMPROC(enum_proc), 0)

        except Exception as exc:
            logger.error(f"Error enumerating or closing VS Code windows: {exc}")
            return False, f"Failed to close VS Code window: {exc}"

        if closed_count > 0:
            return True, f"Successfully closed VS Code window for workspace '{Path(workspace_path_or_name).name}'."
        else:
            return False, f"No open VS Code window found for workspace '{Path(workspace_path_or_name).name}'."

