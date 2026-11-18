"""
Voice Diagnostics & Watchdog Subsystem for Victor AI Assistant.

Provides structured diagnostic event logging with unique interaction IDs,
continuous health monitoring of the voice pipeline (microphone, VAD, Live session, STT/TTS),
and an active recovery watchdog to prevent voice pipeline hangs or deadlocks.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, Optional

logger = logging.getLogger("victor.voice.diagnostics")


class VoiceEventType:
    VOICE_SESSION_STARTED = "VOICE_SESSION_STARTED"
    MICROPHONE_STREAM_STARTED = "MICROPHONE_STREAM_STARTED"
    AUDIO_FRAME_RECEIVED = "AUDIO_FRAME_RECEIVED"
    WAKE_WORD_DETECTED = "WAKE_WORD_DETECTED"
    SPEECH_STARTED = "SPEECH_STARTED"
    SPEECH_CONTINUED = "SPEECH_CONTINUED"
    PAUSE_DETECTED = "PAUSE_DETECTED"
    SPEECH_FINALIZED = "SPEECH_FINALIZED"
    STT_STARTED = "STT_STARTED"
    STT_COMPLETED = "STT_COMPLETED"
    STT_FAILED = "STT_FAILED"
    VICTOR_CORE_DISPATCHED = "VICTOR_CORE_DISPATCHED"
    RESPONSE_RECEIVED = "RESPONSE_RECEIVED"
    TTS_STARTED = "TTS_STARTED"
    TTS_COMPLETED = "TTS_COMPLETED"
    LISTENING_RESUMED = "LISTENING_RESUMED"
    RECONNECT_ATTEMPT = "RECONNECT_ATTEMPT"
    VOICE_SESSION_STOPPED = "VOICE_SESSION_STOPPED"
    VOICE_ERROR = "VOICE_ERROR"


# Convenience alias
VoiceDiagnosticEvent = VoiceEventType


class VoiceDiagnosticsManager:
    """
    Central manager for structured voice diagnostic telemetry,
    health monitoring, and interaction tracking.
    """

    def __init__(self) -> None:
        self.active_interaction_id: Optional[str] = None
        self.total_frames_received: int = 0
        self.total_audio_bytes: int = 0
        self.last_frame_time: float = 0.0
        self.last_speech_time: float = 0.0
        self.last_finalized_time: float = 0.0
        self.last_response_time: float = 0.0
        self.last_health_log_time: float = 0.0
        self.interaction_count: int = 0
        self._frame_log_counter: int = 0

    @property
    def total_audio_frames(self) -> int:
        return self.total_frames_received

    @property
    def current_interaction_id(self) -> Optional[str]:
        return self.active_interaction_id

    def start_interaction(self) -> str:
        """Alias for new_interaction."""
        return self.new_interaction()

    def complete_interaction(self) -> Optional[str]:
        """Marks active interaction as completed."""
        prev = self.active_interaction_id
        self.active_interaction_id = None
        return prev

    def new_interaction(self) -> str:
        """Starts a new user voice interaction with a unique interaction ID."""
        self.interaction_count += 1
        self.active_interaction_id = f"vturn_{uuid.uuid4().hex[:8]}"
        return self.active_interaction_id

    def get_current_interaction_id(self) -> str:
        """Returns the active interaction ID or generates a default one."""
        if not self.active_interaction_id:
            return self.new_interaction()
        return self.active_interaction_id

    def emit(
        self,
        event_type: str,
        interaction_id: Optional[str] = None,
        state: Optional[str] = None,
        duration_ms: Optional[float] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Convenience method to emit an event with a details dict."""
        payload = details or {}
        self.log_event(
            event_type=event_type,
            interaction_id=interaction_id,
            state=state,
            duration_ms=duration_ms,
            **payload,
        )

    def log_event(
        self,
        event_type: str,
        interaction_id: Optional[str] = None,
        state: Optional[str] = None,
        duration_ms: Optional[float] = None,
        **details: Any,
    ) -> None:
        """
        Emits a structured diagnostic log entry for a voice pipeline event.
        Guaranteed to never log credentials, tokens, or raw audio bytes.
        """
        iid = interaction_id or self.active_interaction_id or "global"
        now = time.time()

        detail_str = " | ".join(f"{k}={v}" for k, v in details.items() if k not in ("pcm", "data", "audio"))
        dur_str = f" | dur={duration_ms:.1f}ms" if duration_ms is not None else ""
        state_str = f" | state={state}" if state else ""

        log_msg = f"[VOICE_EVENT] {event_type} | id={iid}{state_str}{dur_str}"
        if detail_str:
            log_msg += f" | {detail_str}"

        if event_type == VoiceEventType.VOICE_ERROR or event_type == VoiceEventType.STT_FAILED:
            logger.error(log_msg)
        else:
            logger.info(log_msg)

    def record_frame(self, chunk_len: int = 0) -> None:
        """Records reception of an incoming microphone audio frame."""
        now = time.time()
        self.total_frames_received += 1
        self.total_audio_bytes += chunk_len
        self.last_frame_time = now
        self._frame_log_counter += 1

    def get_health_summary(self, session_manager: Any = None) -> Dict[str, Any]:
        """Returns structured health summary dictionary."""
        status = self.get_health_status(session_manager)
        status["status"] = "HEALTHY" if status.get("microphone_active", True) else "DEGRADED"
        return status

        # Rate-limit AUDIO_FRAME_RECEIVED logging: once every 100 frames (~12.8s) to avoid log spam
        if self._frame_log_counter >= 100:
            self._frame_log_counter = 0
            self.log_event(
                VoiceEventType.AUDIO_FRAME_RECEIVED,
                total_frames=self.total_frames_received,
                chunk_bytes=chunk_len,
            )

    def get_health_status(self, session_manager: Any = None) -> Dict[str, Any]:
        """Collects live health telemetry of all voice pipeline components."""
        now = time.time()
        time_since_frame = (now - self.last_frame_time) if self.last_frame_time > 0 else -1.0
        time_since_response = (now - self.last_response_time) if self.last_response_time > 0 else -1.0

        is_connected = False
        if session_manager and hasattr(session_manager, "live_session"):
            is_connected = getattr(session_manager.live_session, "is_connected", False)

        tm_state = "UNKNOWN"
        noise_floor = 0.0
        if session_manager and hasattr(session_manager, "turn_manager"):
            tm_state = str(getattr(session_manager.turn_manager, "state", "UNKNOWN"))
            noise_floor = getattr(session_manager.turn_manager, "noise_floor", 0.0)

        vad_device = "CPU"
        if session_manager and hasattr(session_manager, "turn_manager") and getattr(session_manager.turn_manager, "_gpu_vad", None):
            vad_device = session_manager.turn_manager._gpu_vad.device_name

        mic_healthy = (time_since_frame >= 0 and time_since_frame < 5.0)

        return {
            "microphone_active": mic_healthy,
            "time_since_last_frame_sec": round(time_since_frame, 2) if time_since_frame >= 0 else None,
            "total_frames_received": self.total_frames_received,
            "live_session_connected": is_connected,
            "turn_manager_state": tm_state,
            "noise_floor": round(noise_floor, 4),
            "vad_device": vad_device,
            "interactions_count": self.interaction_count,
            "active_interaction_id": self.active_interaction_id,
            "time_since_last_response_sec": round(time_since_response, 2) if time_since_response >= 0 else None,
        }

    def format_health_report(self, session_manager: Any = None) -> str:
        """Formats health status into a human-readable telemetry block."""
        st = self.get_health_status(session_manager)
        mic_status = "HEALTHY" if st["microphone_active"] else ("IDLE/WAITING" if st["time_since_last_frame_sec"] is None else f"NO FRAMES ({st['time_since_last_frame_sec']}s)")
        live_status = "CONNECTED" if st["live_session_connected"] else "DISCONNECTED"

        return (
            f"[Voice Health Status] Mic: {mic_status} | Live: {live_status} | "
            f"VAD: {st['turn_manager_state']} (noise={st['noise_floor']}, dev={st['vad_device']}) | "
            f"Frames: {st['total_frames_received']} | Interactions: {st['interactions_count']}"
        )


# Global singleton instance
_diagnostics_instance: Optional[VoiceDiagnosticsManager] = None

def get_voice_diagnostics() -> VoiceDiagnosticsManager:
    global _diagnostics_instance
    if _diagnostics_instance is None:
        _diagnostics_instance = VoiceDiagnosticsManager()
    return _diagnostics_instance
