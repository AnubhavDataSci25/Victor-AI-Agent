"""
Windows Clipboard Manager for Victor.

Reuses existing Windows OS clipboard infrastructure via win32clipboard / ctypes:
- Text copy (CF_UNICODETEXT)
- Image copy (CF_DIB)
- Clipboard text & image retrieval
- Native paste simulation (Ctrl+V) into active application
- Ephemeral retry handling if clipboard is briefly held by another Windows process
"""

from __future__ import annotations

import ctypes
import io
import logging
import time
from typing import Optional

from PIL import Image
try:
    import win32clipboard
    import win32con
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False

logger = logging.getLogger(__name__)

VK_CONTROL = 0x11
VK_V = 0x56
KEYEVENTF_KEYUP = 0x0002


class WindowsClipboardManager:
    """Provides safe, robust access to Windows clipboard without duplicate systems."""

    @staticmethod
    def _open_clipboard_with_retry(max_retries: int = 5, delay: float = 0.05) -> bool:
        """Attempts to open clipboard with short exponential backoff for OS contention."""
        if not HAS_WIN32:
            return False
        for attempt in range(max_retries):
            try:
                win32clipboard.OpenClipboard()
                return True
            except Exception:
                time.sleep(delay * (attempt + 1))
        return False

    @classmethod
    def set_text(cls, text: str) -> bool:
        """Places text onto the Windows clipboard as CF_UNICODETEXT."""
        if not HAS_WIN32:
            logger.warning("[Clipboard] pywin32 not available for set_text.")
            return False

        if not cls._open_clipboard_with_retry():
            logger.error("[Clipboard] Unable to open Windows clipboard.")
            return False

        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
            logger.info(f"[Clipboard] Successfully copied {len(text)} characters to clipboard.")
            return True
        except Exception as e:
            logger.error(f"[Clipboard] Failed to set text: {e}")
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    @classmethod
    def get_text(cls) -> Optional[str]:
        """Retrieves text from the Windows clipboard."""
        if not HAS_WIN32:
            return None

        if not cls._open_clipboard_with_retry():
            return None

        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
                data = win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
                return str(data)
            return None
        except Exception as e:
            logger.error(f"[Clipboard] Failed to get text: {e}")
            return None
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    @classmethod
    def set_image(cls, image: Image.Image) -> bool:
        """Places a PIL Image onto the Windows clipboard as CF_DIB."""
        if not HAS_WIN32:
            logger.warning("[Clipboard] pywin32 not available for set_image.")
            return False

        try:
            # Convert image to RGB DIB format (BMP without 14-byte header)
            output = io.BytesIO()
            image.convert("RGB").save(output, "BMP")
            data = output.getvalue()[14:]  # Slice out 14-byte BITMAPFILEHEADER
            output.close()
        except Exception as e:
            logger.error(f"[Clipboard] Failed to serialize image to DIB: {e}")
            return False

        if not cls._open_clipboard_with_retry():
            logger.error("[Clipboard] Unable to open Windows clipboard.")
            return False

        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardData(win32con.CF_DIB, data)
            logger.info(f"[Clipboard] Successfully copied image ({image.width}x{image.height}) to clipboard.")
            return True
        except Exception as e:
            logger.error(f"[Clipboard] Failed to set image: {e}")
            return False
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    @classmethod
    def get_image(cls) -> Optional[Image.Image]:
        """Retrieves an image from the Windows clipboard if present."""
        if not HAS_WIN32:
            return None

        if not cls._open_clipboard_with_retry():
            return None

        try:
            if win32clipboard.IsClipboardFormatAvailable(win32con.CF_DIB):
                dib_data = win32clipboard.GetClipboardData(win32con.CF_DIB)
                # Reconstruct full BMP with standard 14-byte BITMAPFILEHEADER
                file_size = len(dib_data) + 14
                header = (
                    b"BM"  # Signature
                    + file_size.to_bytes(4, "little")  # File size
                    + b"\x00\x00\x00\x00"  # Reserved
                    + (14 + 40).to_bytes(4, "little")  # Offset to pixel data (14 header + 40 BITMAPINFOHEADER)
                )
                img = Image.open(io.BytesIO(header + dib_data))
                return img
            return None
        except Exception as e:
            logger.error(f"[Clipboard] Failed to get image: {e}")
            return None
        finally:
            try:
                win32clipboard.CloseClipboard()
            except Exception:
                pass

    @classmethod
    def paste_into_active_window(cls) -> bool:
        """Simulates native Windows Ctrl+V paste into the focused application."""
        try:
            user32 = ctypes.windll.user32
            # Key down Ctrl
            user32.keybd_event(VK_CONTROL, 0, 0, 0)
            time.sleep(0.02)
            # Key down V
            user32.keybd_event(VK_V, 0, 0, 0)
            time.sleep(0.02)
            # Key up V
            user32.keybd_event(VK_V, 0, KEYEVENTF_KEYUP, 0)
            time.sleep(0.02)
            # Key up Ctrl
            user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
            logger.info("[Clipboard] Simulated paste (Ctrl+V) into active application.")
            return True
        except Exception as e:
            logger.error(f"[Clipboard] Failed to simulate paste: {e}")
            return False
