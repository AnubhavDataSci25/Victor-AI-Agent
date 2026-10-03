"""
Live Periodic Camera Analyzer for Victor.

Implements an explicit, user-initiated camera analysis mode:
- Periodically samples frames instead of continuous streaming.
- Employs local frame-difference / motion-detection throttling: skips external API
  calls if the scene has not changed significantly.
- Minimizes CPU, bandwidth, latency, and API cost.
- Stops immediately upon user request or session lock.
- Emits real-time visual update events via UI WebSocket callback.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable, Optional, Tuple

import cv2
import numpy as np

from app.tools.vision.camera_driver import CameraDriver, CameraState, get_camera_driver
from app.tools.vision.visual_analyzer import VisualAnalyzer, get_visual_analyzer

logger = logging.getLogger(__name__)


class LiveCameraAnalyzer:
    """Manages periodic sampled camera analysis with motion-aware throttling."""

    _instance: Optional[LiveCameraAnalyzer] = None

    def __new__(cls) -> LiveCameraAnalyzer:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True
        self.camera_driver: CameraDriver = get_camera_driver()
        self.visual_analyzer: VisualAnalyzer = get_visual_analyzer()
        self._task: Optional[asyncio.Task] = None
        self._is_running: bool = False
        self._query: str = "Describe what the user is doing and any visual changes in front of the camera."
        self._interval: float = 4.0
        self._update_callback: Optional[Callable[[dict], None]] = None
        self._last_thumbnail: Optional[np.ndarray] = None
        self._last_api_call_time: float = 0.0

    @property
    def is_running(self) -> bool:
        return self._is_running and self._task is not None and not self._task.done()

    def set_update_callback(self, callback: Optional[Callable[[dict], None]]) -> None:
        self._update_callback = callback

    async def start(
        self,
        query: Optional[str] = None,
        interval_seconds: float = 4.0,
        update_callback: Optional[Callable[[dict], None]] = None,
    ) -> Tuple[bool, str]:
        """Activates periodic live visual analysis mode."""
        if self.is_running:
            return True, "Camera live analysis is already running."

        # Ensure camera hardware is opened
        if not self.camera_driver.is_open:
            opened, msg = await self.camera_driver.open_camera()
            if not opened:
                return False, f"Could not open camera for live analysis: {msg}"

        if query:
            self._query = query.strip()
        self._interval = max(2.0, float(interval_seconds))
        if update_callback:
            self._update_callback = update_callback

        self._is_running = True
        self.camera_driver._state = CameraState.ANALYZING
        self.camera_driver._notify_state_change()

        self._task = asyncio.create_task(self._sample_loop())
        logger.info(f"[LiveCameraAnalyzer] Started periodic analysis (interval: {self._interval}s)")
        return True, f"Live visual analysis started (sampling every {self._interval:.1f} seconds). Say 'stop analysis' or 'close camera' to stop."

    async def stop(self) -> Tuple[bool, str]:
        """Deactivates live visual analysis mode immediately."""
        if not self.is_running and not self._is_running:
            return True, "Live camera analysis is not currently active."

        self._is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        self._last_thumbnail = None
        if self.camera_driver.is_open:
            self.camera_driver._state = CameraState.OPEN
        else:
            self.camera_driver._state = CameraState.CLOSED
        self.camera_driver._notify_state_change()

        logger.info("[LiveCameraAnalyzer] Periodic live analysis stopped.")
        return True, "Live camera analysis mode has been stopped."

    @staticmethod
    def _compute_frame_difference(frame: np.ndarray, prev_thumb: Optional[np.ndarray]) -> Tuple[float, np.ndarray]:
        """Computes mean pixel difference between current frame thumbnail and previous thumbnail."""
        small = cv2.resize(frame, (64, 64))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        if prev_thumb is None:
            return 100.0, gray

        diff = float(np.mean(np.abs(gray.astype(float) - prev_thumb.astype(float))))
        return diff, gray

    async def _sample_loop(self) -> None:
        """Background coroutine that samples camera frames periodically."""
        logger.debug("[LiveCameraAnalyzer] Background sampling loop active.")
        try:
            while self._is_running:
                await asyncio.sleep(self._interval)
                if not self._is_running:
                    break

                # 1. Capture current frame from camera
                ok, frame, err = await self.camera_driver.capture_frame(auto_open=False)
                if not ok or frame is None:
                    logger.debug(f"[LiveCameraAnalyzer] Skipped sample: {err}")
                    continue

                # 2. Local change detection: only call external API if motion/change is detected
                diff, current_thumb = self._compute_frame_difference(frame, self._last_thumbnail)
                now = time.time()
                time_since_last_api = now - self._last_api_call_time

                # Threshold of 6.0 in 64x64 grayscale indicates noticeable visual difference
                motion_detected = diff >= 6.0 or self._last_thumbnail is None
                periodic_refresh = time_since_last_api >= 30.0

                self._last_thumbnail = current_thumb

                if not motion_detected and not periodic_refresh:
                    # Scene is static; throttle API calls to save bandwidth & cost
                    logger.debug(f"[LiveCameraAnalyzer] Frame static (diff: {diff:.2f}); skipping external API.")
                    continue

                # 3. Analyze frame with Gemini Vision
                self._last_api_call_time = now
                logger.debug(f"[LiveCameraAnalyzer] Invoking vision model (diff: {diff:.2f})...")
                ok, analysis = await self.visual_analyzer.analyze_visual(frame, query=self._query)
                if ok and analysis:
                    logger.info(f"[LiveCameraAnalyzer] Analysis: {analysis}")
                    if self._update_callback:
                        try:
                            res = self._update_callback({
                                "type": "camera_analysis_update",
                                "text": analysis,
                                "timestamp": now,
                            })
                            if asyncio.iscoroutine(res):
                                asyncio.create_task(res)
                        except Exception as cb_err:
                            logger.debug(f"[LiveCameraAnalyzer] Callback error: {cb_err}")

        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"[LiveCameraAnalyzer] Unexpected error in sampling loop: {e}")
        finally:
            self._is_running = False


_live_analyzer_instance: Optional[LiveCameraAnalyzer] = None


def get_live_camera_analyzer() -> LiveCameraAnalyzer:
    global _live_analyzer_instance
    if _live_analyzer_instance is None:
        _live_analyzer_instance = LiveCameraAnalyzer()
    return _live_analyzer_instance
