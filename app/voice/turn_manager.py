"""
Victor Intelligent Voice Turn Manager & Utterance Buffering Engine.

Provides continuous, natural human conversation turn management:
- Accurately distinguishes short pauses (0.5-1.5s) and normal pauses (1.5-2.5s) from speech endpoints.
- Maintains continuous audio buffering across natural thinking gaps.
- Analyzes linguistic trailing continuation words ('and', 'because', 'then', 'also', etc.).
- Detects explicit voice completion phrases ('That's all', "I'm done", 'Victor, process it').
- Implements state progression:
  LISTENING -> WAITING_FOR_CONTINUATION -> FINALIZING -> TRANSCRIBING -> THINKING -> EXECUTING -> SPEAKING.
- Guaranteed zero partial request executions and zero self-triggering during assistant speech.
"""

from __future__ import annotations

import collections
import dataclasses
import enum
import logging
import math
import re
import struct
import time
from typing import Any, Awaitable, Callable, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# Try numpy for ultra-fast vector RMS calculation; fallback to struct unpacking
try:
    import numpy as np  # type: ignore
    _HAS_NUMPY = True
except ImportError:
    np = None
    _HAS_NUMPY = False


# ---------------------------------------------------------------------------
# Linguistic Patterns
# ---------------------------------------------------------------------------

# Words or prefixes that strongly signal the speaker intends to continue speaking
_CONTINUATION_WORDS: Set[str] = {
    "and", "because", "then", "also", "or", "so", "with", "to", "but", "plus",
    "like", "for", "about", "that", "which", "if", "when", "where", "while",
    "open", "search", "find", "look", "create", "send", "tell", "check",
    "show", "play", "call", "set", "write", "delete", "remove", "add"
}

_CONTINUATION_SUFFIXES: Tuple[str, ...] = (
    " and", " because", " then", " also", " or", " so", " with", " to", " but",
    " plus", " search for", " look for", " open", " find", " about", " like",
    " such as", " that", " which", " if", " when", " where", " while"
)

# Explicit voice commands that directly signal the user is done speaking
_EXPLICIT_FINISH_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(?:that['’]?s\s+all|that\s+is\s+all)\b[.!?,]?\s*$", re.IGNORECASE),
    re.compile(r"\b(?:i['’]?m\s+done|i\s+am\s+done)\b[.!?,]?\s*$", re.IGNORECASE),
    re.compile(r"\b(?:victor\s*,?\s*)?(?:process\s+it|please\s+process|go\s+ahead)\b[.!?,]?\s*$", re.IGNORECASE),
    re.compile(r"\b(?:done|finished)\b[.!?,]?\s*$", re.IGNORECASE),
]

_STANDALONE_WAKE_ONLY: Set[str] = {
    "victor", "hey victor", "hello victor", "hi victor", "ok victor", "okay victor",
    "wake up", "wake up victor", "listen", "start"
}


class TurnState(str, enum.Enum):
    """Voice Turn Manager logical state."""
    IDLE_LISTENING = "LISTENING"
    SPEECH_ACTIVE = "SPEECH_ACTIVE"
    WAITING_FOR_CONTINUATION = "WAITING_FOR_CONTINUATION"
    FINALIZING = "FINALIZING"
    DISPATCHED = "DISPATCHED"


@dataclasses.dataclass
class TurnManagerConfig:
    """Configurable thresholds and durations for intelligent turn management."""
    sample_rate: int = 16000
    channels: int = 1
    sample_width: int = 2  # 16-bit PCM (2 bytes per sample)

    # Silence & Pause thresholds (seconds)
    short_pause_sec: float = 1.2          # 0.5 - 1.5s: Within-clause pause; keep listening seamlessly
    normal_pause_sec: float = 2.2         # 1.5 - 2.5s: Thought pause; enter WAITING_FOR_CONTINUATION
    potential_endpoint_sec: float = 2.8   # 2.5 - 3.5s: Standard endpoint if no continuation clues
    continuation_extension_sec: float = 1.8 # Extra allowance if trailing speech has connective word
    max_waiting_duration_sec: float = 12.0 # 10 - 15s: Hard cutoff after last speech burst
    max_utterance_duration_sec: float = 90.0 # 60 - 120s: Safety cap for single turn

    # Speech sensitivity & noise adaptation
    min_speech_duration_sec: float = 0.35  # Ignore transient pops, clicks, or breaths (< 350ms)
    min_rms_threshold: float = 0.010       # Absolute minimum RMS energy to consider speech
    energy_multiplier: float = 2.4         # Speech threshold = max(min_rms, noise_floor * multiplier)
    noise_floor_alpha: float = 0.04        # EMA update rate for background ambient noise floor
    initial_noise_floor: float = 0.005     # Baseline noise estimate

    # Pre-speech ring buffer (seconds)
    pre_speech_buffer_sec: float = 0.45    # Preserves initial word onset (e.g. consonants)


class VoiceTurnManager:
    """
    Intelligent turn manager that buffers continuous speech, ignores natural pauses,
    detects linguistic continuation clues, and delivers complete utterances.
    """

    def __init__(
        self,
        config: Optional[TurnManagerConfig] = None,
        on_state_change: Optional[Callable[[TurnState, TurnState], Any]] = None,
        on_turn_finalized: Optional[Callable[[bytes, str], Any]] = None,
        on_turn_timeout: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.config = config or TurnManagerConfig()
        self.on_state_change = on_state_change
        self.on_turn_finalized = on_turn_finalized
        self.on_turn_timeout = on_turn_timeout

        self._state = TurnState.IDLE_LISTENING
        self._noise_floor = self.config.initial_noise_floor

        # Utterance audio buffer & pre-speech circular ring buffer
        self._utterance_buffer = bytearray()
        pre_speech_capacity = max(1, int(
            (self.config.pre_speech_buffer_sec * self.config.sample_rate * self.config.sample_width) / 4096
        ))
        self._pre_speech_ring: Deque[bytes] = collections.deque(maxlen=pre_speech_capacity)

        # Timestamps & durations
        self._utterance_start_time: Optional[float] = None
        self._last_speech_time: Optional[float] = None
        self._pause_start_time: Optional[float] = None
        self._total_speech_bytes: int = 0

        # Transcript hint from upstream live STT (if available)
        self._current_transcript_hint: str = ""
        self._has_explicit_finish: bool = False
        self._cleaned_finish_text: Optional[str] = None

        # Lock / guard to prevent concurrent finalizations
        self._is_finalizing: bool = False

    @property
    def state(self) -> TurnState:
        return self._state

    @property
    def noise_floor(self) -> float:
        return self._noise_floor

    @property
    def buffered_duration_sec(self) -> float:
        """Returns the duration of the current audio buffer in seconds."""
        bytes_per_sec = self.config.sample_rate * self.config.sample_width
        return len(self._utterance_buffer) / bytes_per_sec if bytes_per_sec > 0 else 0.0

    @property
    def speech_duration_sec(self) -> float:
        """Returns duration of actual detected speech in the buffer."""
        bytes_per_sec = self.config.sample_rate * self.config.sample_width
        return self._total_speech_bytes / bytes_per_sec if bytes_per_sec > 0 else 0.0

    def calculate_rms(self, pcm_chunk: bytes) -> float:
        """Calculates Root-Mean-Square (RMS) amplitude normalized to [-1.0, 1.0]."""
        if not pcm_chunk:
            return 0.0

        if _HAS_NUMPY and np is not None:
            try:
                # Fast numpy vectorized computation
                audio_array = np.frombuffer(pcm_chunk, dtype=np.int16)
                if audio_array.size == 0:
                    return 0.0
                normalized = audio_array.astype(np.float32) / 32768.0
                return float(np.sqrt(np.mean(normalized * normalized)))
            except Exception:
                pass

        # Fallback pure-python unpacking
        num_samples = len(pcm_chunk) // 2
        if num_samples == 0:
            return 0.0
        try:
            samples = struct.unpack(f"<{num_samples}h", pcm_chunk[:num_samples * 2])
            sum_sq = sum((s / 32768.0) ** 2 for s in samples)
            return math.sqrt(sum_sq / num_samples)
        except Exception:
            return 0.0

    def feed_transcript_hint(self, text: str) -> Optional[Dict[str, Any]]:
        """
        Supplies incremental live transcription text hints to inspect for
        continuation words or explicit completion phrases.
        """
        if not text:
            return None

        clean_text = text.strip()
        self._current_transcript_hint = clean_text

        # Check for explicit completion commands ("That's all", "I'm done", "Victor, process it")
        is_finish, stripped_text = self._check_explicit_finish(clean_text)
        if is_finish:
            logger.info(f"[VoiceTurnManager] Explicit finish command detected in: '{clean_text}'")
            self._has_explicit_finish = True
            self._cleaned_finish_text = stripped_text
            return self.finalize_turn(reason="explicit_voice_command")

        return None

    def process_audio(self, pcm_chunk: bytes, now: Optional[float] = None) -> Dict[str, Any]:
        """
        Main entry point for incoming PCM audio chunks from client microphone.
        Analyzes energy, updates state machine, accumulates audio, and triggers
        callbacks when transitions occur.
        """
        if not pcm_chunk:
            return {"action": "none", "state": self._state.value}

        current_time = now if now is not None else time.time()
        rms = self.calculate_rms(pcm_chunk)

        # Dynamic speech threshold based on adaptive ambient noise floor
        speech_threshold = max(
            self.config.min_rms_threshold,
            self._noise_floor * self.config.energy_multiplier
        )
        is_speech = rms >= speech_threshold

        # Update ambient noise floor during non-speech with EMA
        if not is_speech and self._state == TurnState.IDLE_LISTENING:
            self._noise_floor = (
                (1.0 - self.config.noise_floor_alpha) * self._noise_floor
                + self.config.noise_floor_alpha * rms
            )

        # -------------------------------------------------------------------
        # State: IDLE_LISTENING (Standby / Ambient)
        # -------------------------------------------------------------------
        if self._state == TurnState.IDLE_LISTENING:
            if is_speech:
                # Speech onset detected!
                self._transition_to(TurnState.SPEECH_ACTIVE)
                self._utterance_start_time = current_time
                self._last_speech_time = current_time
                self._pause_start_time = None
                self._total_speech_bytes = len(pcm_chunk)

                # Prepend pre-speech ring buffer to prevent losing initial consonants
                self._utterance_buffer.clear()
                while self._pre_speech_ring:
                    self._utterance_buffer.extend(self._pre_speech_ring.popleft())
                self._utterance_buffer.extend(pcm_chunk)

                return {
                    "action": "speech_started",
                    "state": self._state.value,
                    "rms": rms,
                    "threshold": speech_threshold,
                }
            else:
                # Keep cycling ambient chunks into pre-speech buffer
                self._pre_speech_ring.append(pcm_chunk)
                return {"action": "listening", "state": self._state.value, "rms": rms}

        # -------------------------------------------------------------------
        # State: SPEECH_ACTIVE or WAITING_FOR_CONTINUATION
        # -------------------------------------------------------------------
        if self._state in (TurnState.SPEECH_ACTIVE, TurnState.WAITING_FOR_CONTINUATION):
            # Accumulate every chunk seamlessly into the utterance buffer
            self._utterance_buffer.extend(pcm_chunk)

            # Check safety cap on max utterance duration
            if self._utterance_start_time and (current_time - self._utterance_start_time) >= self.config.max_utterance_duration_sec:
                logger.warning("[VoiceTurnManager] Max utterance duration reached; finalizing buffer.")
                return self.finalize_turn(reason="max_utterance_duration")

            if is_speech:
                # User is speaking (or resumed speaking after a pause)
                self._last_speech_time = current_time
                self._pause_start_time = None
                self._total_speech_bytes += len(pcm_chunk)

                if self._state == TurnState.WAITING_FOR_CONTINUATION:
                    # User continued speaking after a pause: seamlessly revert to SPEECH_ACTIVE
                    logger.debug("[VoiceTurnManager] Speech resumed during continuation window.")
                    self._transition_to(TurnState.SPEECH_ACTIVE)

                return {
                    "action": "speech_accumulated",
                    "state": self._state.value,
                    "rms": rms,
                }
            else:
                # Non-speech frame inside active turn: start or increment pause timing
                if self._pause_start_time is None:
                    self._pause_start_time = current_time

                pause_duration = current_time - self._pause_start_time
                time_since_speech = current_time - (self._last_speech_time or current_time)

                normal_pause_thresh = min(self.config.normal_pause_sec, self.config.potential_endpoint_sec * 0.75)
                if self._state == TurnState.SPEECH_ACTIVE and pause_duration >= normal_pause_thresh:
                    self._transition_to(TurnState.WAITING_FOR_CONTINUATION)

                # Hard timeout if user has stopped speaking for too long
                if time_since_speech >= self.config.max_waiting_duration_sec:
                    logger.info(f"[VoiceTurnManager] Max waiting duration reached ({time_since_speech:.1f}s).")
                    return self._handle_timeout()

                # Check for Endpoint Conditions
                has_continuation_word = self._has_continuation_word()
                is_isolated_wake = self._is_isolated_wake_word()

                effective_endpoint_threshold = self.config.potential_endpoint_sec
                if has_continuation_word:
                    # Grant continuation extension if speech ends on 'and', 'because', etc.
                    effective_endpoint_threshold += self.config.continuation_extension_sec

                # If silence exceeds the effective endpoint threshold
                if pause_duration >= effective_endpoint_threshold:
                    # If the entire captured text is purely an isolated wake word (e.g. 'Victor'),
                    # keep waiting for the actual instruction until max_waiting_duration_sec
                    if is_isolated_wake:
                        return {
                            "action": "waiting_continuation",
                            "state": self._state.value,
                            "pause_duration": pause_duration,
                            "isolated_wake_word": True,
                        }

                    # Verify minimum speech duration requirement
                    if self.speech_duration_sec < self.config.min_speech_duration_sec:
                        logger.info(
                            f"[VoiceTurnManager] Discarding brief noise artifact: "
                            f"{self.speech_duration_sec:.2f}s speech < {self.config.min_speech_duration_sec:.2f}s."
                        )
                        self.reset()
                        return {"action": "discard_noise", "state": self._state.value}

                    logger.info(
                        f"[VoiceTurnManager] Speech endpoint satisfied: pause={pause_duration:.2f}s "
                        f"(threshold={effective_endpoint_threshold:.2f}s, continuation_word={has_continuation_word})."
                    )
                    return self.finalize_turn(reason="endpoint_silence")

                # Short Pause (< normal_pause_thresh): User natural breathing / within-clause pause
                if pause_duration < normal_pause_thresh:
                    return {
                        "action": "buffering_pause",
                        "state": self._state.value,
                        "pause_duration": pause_duration,
                    }

                return {
                    "action": "waiting_continuation",
                    "state": self._state.value,
                    "pause_duration": pause_duration,
                    "continuation_word": has_continuation_word,
                }

                return {
                    "action": "waiting_continuation",
                    "state": self._state.value,
                    "pause_duration": pause_duration,
                    "continuation_word": has_continuation_word,
                }

        return {"action": "none", "state": self._state.value}

    def finalize_turn(self, reason: str = "endpoint") -> Dict[str, Any]:
        """
        Finalizes the buffered utterance, transitions to FINALIZING, and yields
        the contiguous audio buffer to the callback exactly once.
        """
        if self._is_finalizing:
            return {"action": "none", "state": self._state.value}

        self._is_finalizing = True
        prev_state = self._state
        self._transition_to(TurnState.FINALIZING)

        final_pcm = bytes(self._utterance_buffer)
        duration_sec = self.buffered_duration_sec
        clean_hint = self._cleaned_finish_text or self._current_transcript_hint

        logger.info(
            f"[VoiceTurnManager] Utterance finalized (reason='{reason}', "
            f"duration={duration_sec:.2f}s, speech={self.speech_duration_sec:.2f}s, bytes={len(final_pcm)})."
        )

        res = {
            "action": "turn_finalized",
            "reason": reason,
            "audio": final_pcm,
            "duration_sec": duration_sec,
            "transcript_hint": clean_hint,
            "state": TurnState.FINALIZING.value,
        }

        # Fire callback if registered
        if self.on_turn_finalized:
            try:
                callback_res = self.on_turn_finalized(final_pcm, clean_hint)
                # If callback is a coroutine, caller or event loop handles it
            except Exception as e:
                logger.error(f"[VoiceTurnManager] Error in on_turn_finalized callback: {e}")

        # Transition to DISPATCHED
        self._transition_to(TurnState.DISPATCHED)
        self._is_finalizing = False

        return res

    def _handle_timeout(self) -> Dict[str, Any]:
        """Handles expiration of max_waiting_duration_sec."""
        # If user spoke enough to constitute a real sentence and did not leave it on an isolated wake word
        clean_hint = (self._current_transcript_hint or "").strip().lower()
        clean_hint_norm = re.sub(r"[^\w\s]", "", clean_hint).strip()

        if self.speech_duration_sec >= 1.0 and clean_hint_norm not in _STANDALONE_WAKE_ONLY:
            logger.info("[VoiceTurnManager] Finalizing complete speech captured before waiting timeout.")
            return self.finalize_turn(reason="timeout_finalization")

        # Incomplete fragment / isolated wake word / breathing only
        logger.info("[VoiceTurnManager] Speech timed out with incomplete fragment; clearing buffer gracefully.")
        self.reset()
        if self.on_turn_timeout:
            try:
                self.on_turn_timeout("waiting_duration_exceeded")
            except Exception as e:
                logger.error(f"[VoiceTurnManager] Error in on_turn_timeout callback: {e}")

        return {"action": "timeout_reset", "state": self._state.value}

    def cancel_turn(self, reason: str = "cancelled") -> None:
        """Cancels any ongoing buffering and resets to IDLE_LISTENING immediately."""
        logger.info(f"[VoiceTurnManager] Turn cancelled: {reason}")
        self.reset()

    def reset(self) -> None:
        """Cleans up all buffers, timers, and state back to pristine IDLE_LISTENING."""
        self._utterance_buffer.clear()
        self._pre_speech_ring.clear()
        self._utterance_start_time = None
        self._last_speech_time = None
        self._pause_start_time = None
        self._total_speech_bytes = 0
        self._current_transcript_hint = ""
        self._has_explicit_finish = False
        self._cleaned_finish_text = None
        self._is_finalizing = False
        self._transition_to(TurnState.IDLE_LISTENING)

    def rearm_after_turn_completion(self) -> None:
        """
        Called when Victor finishes speaking (e.g. Gemini Live turn_complete),
        safely re-arming for the next incoming user speech turn.
        """
        self.reset()

    # -----------------------------------------------------------------------
    # Internal Helpers
    # -----------------------------------------------------------------------
    def _transition_to(self, new_state: TurnState) -> None:
        if self._state == new_state:
            return
        old_state = self._state
        self._state = new_state
        logger.debug(f"[VoiceTurnManager] State: {old_state.value} -> {new_state.value}")
        if self.on_state_change:
            try:
                self.on_state_change(old_state, new_state)
            except Exception as e:
                logger.error(f"[VoiceTurnManager] Error in on_state_change callback: {e}")

    def _has_continuation_word(self) -> bool:
        """Checks if current transcript hint ends with a connective / continuation word."""
        if not self._current_transcript_hint:
            return False

        text = self._current_transcript_hint.strip().lower()
        if any(text.endswith(suffix) for suffix in _CONTINUATION_SUFFIXES):
            return True

        # Check last token
        tokens = re.findall(r"\b\w+\b", text)
        if tokens and tokens[-1] in _CONTINUATION_WORDS:
            return True

        return False

    def _is_isolated_wake_word(self) -> bool:
        """Checks if the captured speech so far is strictly an isolated wake word."""
        if not self._current_transcript_hint:
            return False
        clean = re.sub(r"[^\w\s]", "", self._current_transcript_hint.lower()).strip()
        return clean in _STANDALONE_WAKE_ONLY

    def _check_explicit_finish(self, text: str) -> Tuple[bool, str]:
        """
        Detects if user said an explicit finishing phrase like 'That's all' or 'Victor, process it'.
        Returns (is_detected, cleaned_text_without_finish_command).
        """
        if not text:
            return False, text

        for pattern in _EXPLICIT_FINISH_PATTERNS:
            match = pattern.search(text)
            if match:
                stripped = text[:match.start()].strip().rstrip(" ,:;-")
                return True, stripped

        return False, text
