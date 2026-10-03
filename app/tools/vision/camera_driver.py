"""
Camera Driver for Victor.

Provides hardware lifecycle management, frame capture, photo saving,
and video recording with strict privacy controls:
- Explicit user initiation required.
- Hardware handle released when closed or inactive.
- Non-saved captures treated as temporary in-memory buffers or ephemeral tempfiles.
- Zero raw image data or sensitive content logged.
- Real-time state event notification callback for UI status reporting.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from enum import Enum
import logging
import os
from pathlib import Path
import threading
import time
from typing import Callable, Optional, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    RECORDING = "RECORDING"
    ANALYZING = "ANALYZING"


class CameraDriver:
    """Singleton camera hardware controller for Victor."""

    _instance: Optional[CameraDriver] = None
    _lock = threading.Lock()

    def __new__(cls) -> CameraDriver:
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self._cap: Optional[cv2.VideoCapture] = None
        self._state: CameraState = CameraState.CLOSED
        self._device_index: int = 0
        self._ui_callback: Optional[Callable[[dict], None]] = None
        self._state_lock = threading.Lock()
        self._last_frame: Optional[np.ndarray] = None
        self._last_frame_time: float = 0.0

        # Output folders
        self._pictures_dir = Path.home() / "Pictures" / "Victor_Captures"
        self._videos_dir = Path.home() / "Videos" / "Victor_Captures"

    def set_ui_callback(self, callback: Optional[Callable[[dict], None]]) -> None:
        """Sets callback to notify UI/WebSocket of camera state shifts."""
        self._ui_callback = callback

    def _notify_state_change(self) -> None:
        if self._ui_callback is not None:
            try:
                res = self._ui_callback({
                    "type": "camera_state",
                    "state": self._state.value,
                    "timestamp": time.time(),
                })
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as e:
                logger.debug(f"[CameraDriver] UI state dispatch error: {e}")

    @property
    def state(self) -> CameraState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state != CameraState.CLOSED and self._cap is not None and self._cap.isOpened()

    def _open_capture(self, device_index: int) -> bool:
        """Low-level helper to open cv2.VideoCapture using DirectShow or MSMF."""
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

        # Prefer CAP_DSHOW on Windows for fast hardware hook
        cap = cv2.VideoCapture(device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            # Fallback to default backend
            cap = cv2.VideoCapture(device_index)

        if cap.isOpened():
            # Warm up sensor and discard initial dark frames
            for _ in range(3):
                cap.read()
            self._cap = cap
            self._device_index = device_index
            return True
        else:
            try:
                cap.release()
            except Exception:
                pass
            return False

    async def open_camera(self, device_index: int = 0) -> Tuple[bool, str]:
        """Explicitly activates the camera hardware."""
        def _do_open():
            with self._state_lock:
                if self.is_open and self._device_index == device_index:
                    return True, "Camera is already active."

                success = self._open_capture(device_index)
                if success:
                    self._state = CameraState.OPEN
                    logger.info(f"[Camera] Hardware opened on device index {device_index}")
                    self._notify_state_change()
                    return True, f"Camera device {device_index} initialized successfully."
                else:
                    self._state = CameraState.CLOSED
                    self._notify_state_change()
                    return False, f"Could not access camera device {device_index}. Please check device permissions and connections."

        return await asyncio.to_thread(_do_open)

    async def close_camera(self) -> Tuple[bool, str]:
        """Explicitly deactivates the camera and releases the hardware."""
        def _do_close():
            with self._state_lock:
                if self._cap is not None:
                    try:
                        self._cap.release()
                    except Exception as e:
                        logger.debug(f"[Camera] Error releasing capture: {e}")
                    self._cap = None

                self._state = CameraState.CLOSED
                self._last_frame = None
                logger.info("[Camera] Hardware deactivated and released.")
                self._notify_state_change()
                return True, "Camera closed and hardware released."

        return await asyncio.to_thread(_do_close)

    async def capture_frame(self, auto_open: bool = True) -> Tuple[bool, Optional[np.ndarray], str]:
        """
        Captures a single frame from the camera.
        If camera was not explicitly open and auto_open is True, opens temporarily and closes after.
        """
        def _do_capture():
            with self._state_lock:
                was_closed = not self.is_open
                if was_closed:
                    if not auto_open:
                        return False, None, "Camera is not currently open."
                    opened = self._open_capture(self._device_index)
                    if not opened:
                        return False, None, "Failed to initialize camera for frame capture."

                try:
                    ret, frame = self._cap.read()
                    if not ret or frame is None:
                        return False, None, "Failed to read frame from camera sensor."

                    self._last_frame = frame.copy()
                    self._last_frame_time = time.time()
                    h, w, _ = frame.shape
                    logger.info(f"[Camera] Captured frame ({w}x{h})")
                    return True, frame, f"Successfully captured frame ({w}x{h})."
                finally:
                    if was_closed:
                        # Ephemeral capture: clean up immediately to protect privacy
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None

        return await asyncio.to_thread(_do_capture)

    async def save_photo(
        self,
        frame: Optional[np.ndarray] = None,
        filename: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Saves a captured frame to the user's Pictures directory.
        Only called when explicitly requested by user.
        """
        if frame is None:
            success, captured_frame, msg = await self.capture_frame(auto_open=True)
            if not success or captured_frame is None:
                return False, f"Could not capture photo: {msg}"
            frame = captured_frame

        def _do_save():
            try:
                self._pictures_dir.mkdir(parents=True, exist_ok=True)
                if filename:
                    clean_name = Path(filename).name
                    if not clean_name.lower().endswith((".png", ".jpg", ".jpeg")):
                        clean_name += ".jpg"
                else:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    clean_name = f"victor_photo_{timestamp}.jpg"

                target_path = self._pictures_dir / clean_name
                success = cv2.imwrite(str(target_path), frame, [int(cv2.IMWRITE_JPEG_QUALITY), 95])
                if success:
                    logger.info(f"[Camera] Saved photo to {target_path}")
                    return True, str(target_path)
                return False, "Failed to encode photo to disk."
            except Exception as e:
                logger.error(f"[Camera] Error saving photo: {e}")
                return False, f"Failed to save photo: {str(e)}"

        return await asyncio.to_thread(_do_save)

    async def record_video(
        self,
        duration_seconds: int = 5,
        save: bool = True,
        filename: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Records a short video clip (1-30s) from the camera.
        Only saves to disk when requested.
        """
        # Clamp duration
        duration = max(1, min(int(duration_seconds), 30))

        def _do_record():
            with self._state_lock:
                was_closed = not self.is_open
                if was_closed:
                    opened = self._open_capture(self._device_index)
                    if not opened:
                        return False, "Could not open camera to record video."

                prev_state = self._state
                self._state = CameraState.RECORDING
                self._notify_state_change()

                try:
                    self._videos_dir.mkdir(parents=True, exist_ok=True)
                    if filename:
                        clean_name = Path(filename).name
                        if not clean_name.lower().endswith(".mp4"):
                            clean_name += ".mp4"
                    else:
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        clean_name = f"victor_video_{timestamp}.mp4"

                    target_path = self._videos_dir / clean_name

                    # Determine frame dimensions
                    width = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                    height = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
                    fps = 20.0

                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out = cv2.VideoWriter(str(target_path), fourcc, fps, (width, height))

                    start_time = time.time()
                    total_frames = 0

                    while (time.time() - start_time) < duration:
                        ret, frame = self._cap.read()
                        if ret and frame is not None:
                            out.write(frame)
                            total_frames += 1
                        time.sleep(1.0 / fps)

                    out.release()
                    logger.info(f"[Camera] Recorded {total_frames} frames ({duration}s) to {target_path}")

                    if not save:
                        try:
                            target_path.unlink(missing_ok=True)
                        except Exception:
                            pass
                        return True, f"Video recorded successfully for {duration} seconds (ephemeral capture)."

                    return True, str(target_path)
                except Exception as e:
                    logger.error(f"[Camera] Video recording failed: {e}")
                    return False, f"Video recording error: {str(e)}"
                finally:
                    if was_closed:
                        try:
                            self._cap.release()
                        except Exception:
                            pass
                        self._cap = None
                        self._state = CameraState.CLOSED
                    else:
                        self._state = prev_state
                    self._notify_state_change()

        return await asyncio.to_thread(_do_record)


def get_camera_driver() -> CameraDriver:
    """Retrieve singleton CameraDriver instance."""
    return CameraDriver()
