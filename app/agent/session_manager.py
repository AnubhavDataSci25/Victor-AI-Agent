"""
VictorSessionManager — manages the lifecycle of a single browser
session from 2FA authentication (PIN + Windows Hello fingerprint)
through Gemini Live connection to lockdown.
"""

from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path
import time
from typing import Callable, Optional

from app.agent.state import VictorState
from app.auth.biometric import (
    BaseBiometricVerifier,
    BiometricAvailability,
    BiometricResult,
    WindowsHelloVerifier,
)
from app.auth.manager import AuthManager
from app.auth.store import SecretStore
from app.config import load_config
from app.live.session import LiveSessionManager
from app.logging import get_logger, log_event
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = get_logger("agent.session_manager")

_STATIC_DIR = Path(__file__).resolve().parent.parent / "ui" / "static"


def _get_dipper_audio(filename: str) -> Optional[str]:
    """Retrieve pre-generated Gemini Dipper voice PCM audio as base64 string."""
    audio_path = _STATIC_DIR / filename
    if audio_path.exists():
        try:
            return base64.b64encode(audio_path.read_bytes()).decode("utf-8")
        except Exception:
            return None
    return None



class VictorSessionManager:
    SESSION_TIMEOUT_SECONDS = 900  # 15 minutes

    def __init__(
        self,
        websocket_send_callback: Callable,
        biometric_verifier: Optional[BaseBiometricVerifier] = None,
    ) -> None:
        self.state = VictorState.LOCKED
        self.websocket_send_callback = websocket_send_callback
        self.live_session = LiveSessionManager(self)

        # Load config for auth settings
        self._config = load_config()
        self._secret_store = SecretStore(self._config.security.secrets_path)
        self._secret_store.ensure_configured()
        self._auth_manager = AuthManager(self._config.security, self._secret_store)

        timeout_sec = getattr(self._config.security, "biometric_timeout_seconds", 60.0)
        self.biometric_verifier = biometric_verifier or WindowsHelloVerifier(timeout_seconds=timeout_sec)
        self._is_verifying_biometric = False

        # Memory & Context Manager
        from app.memory.manager import MemoryManager

        self.memory = MemoryManager(
            db_path=self._config.memory.db_path,
            max_recall_results=self._config.memory.max_recall_results,
        )

        # Security: Inactivity tracking
        self.last_activity_time = time.time()
        self.watchdog_task: Optional[asyncio.Task] = None
        self._is_speaking = False
        self._pending_first_command: Optional[str] = None

    def is_authenticated(self) -> bool:
        """
        True ONLY if both PIN and Windows Hello biometric authentication
        have succeeded and the session is active.
        Enforces PIN_VERIFIED != AUTHENTICATED.
        """
        return self._auth_manager.is_unlocked() and self.state in (
            VictorState.AUTHENTICATED,
            VictorState.ACTIVE,
            VictorState.EXECUTING,
            VictorState.SPEAKING,
        )

    async def set_state(self, new_state: VictorState):
        self.state = new_state
        self.last_activity_time = time.time()  # Reset timer on state shifts
        await self.websocket_send_callback({
            "type": "session_state",
            "state": self.state.value,
        })

    async def _inactivity_watchdog(self):
        """Background coroutine that enforces session timeouts."""
        try:
            while self.state not in (VictorState.LOCKED, VictorState.CLOSED, VictorState.OFFLINE):
                await asyncio.sleep(10)
                elapsed = time.time() - self.last_activity_time
                if elapsed > self.SESSION_TIMEOUT_SECONDS:
                    logger.warning(f"Session timeout exceeded ({self.SESSION_TIMEOUT_SECONDS}s). Auto-locking.")
                    await self.lock()
                    break
        except asyncio.CancelledError:
            pass

    async def authenticate(self, credential: str) -> tuple[bool, str]:
        """
        Step 1 of 2FA: Verify the PIN.
        On success, transitions to BIOMETRIC_PENDING.
        Does NOT connect Gemini Live or allow tools until fingerprint is verified.
        """
        if self.state not in (VictorState.LOCKED, VictorState.CLOSED):
            return False, "Session is already active."

        await self.set_state(VictorState.AUTHENTICATING)

        auth_result = self._auth_manager.authenticate(credential)

        if auth_result.success:
            await self.set_state(VictorState.AUTH_SUCCESS)
            # Enforce PIN_VERIFIED != AUTHENTICATED: Hold in BIOMETRIC_PENDING
            await self.set_state(VictorState.BIOMETRIC_PENDING)
            log_event(logger, logging.INFO, "auth_pin_success_biometric_pending")
            # Pre-warm biometric availability check in background so first command doesn't incur latency
            asyncio.create_task(self._prewarm_biometric_check())
            return True, "PIN verified, Sir. Biometric authentication required."
        else:
            await self.set_state(VictorState.LOCKED)
            log_event(logger, logging.WARNING, "auth_pin_failed")
            return False, auth_result.message

    async def _prewarm_biometric_check(self) -> None:
        """Pre-warm biometric availability check in background."""
        try:
            await self.biometric_verifier.check_availability()
        except Exception as e:
            logger.debug(f"Pre-warming biometric availability check failed: {e}")

    @staticmethod
    def _calculate_pcm_rms(pcm_chunk: bytes) -> float:
        """Calculates Root Mean Square (RMS) audio energy of 16-bit mono PCM."""
        if not pcm_chunk or len(pcm_chunk) < 2:
            return 0.0
        import struct
        count = len(pcm_chunk) // 2
        try:
            shorts = struct.unpack(f"<{count}h", pcm_chunk[: count * 2])
            sum_squares = sum(s * s for s in shorts)
            return (sum_squares / count) ** 0.5
        except Exception:
            return 0.0

    async def trigger_biometric_verification(self, command_text: str = "") -> bool:
        """
        Step 2 of 2FA: Trigger the native Windows Hello fingerprint verification flow.
        Invoked when the user says 'Hello Victor' or attempts any command while in BIOMETRIC_PENDING.
        """
        if self.state != VictorState.BIOMETRIC_PENDING:
            return self.is_authenticated()

        if self._is_verifying_biometric:
            return False

        self._is_verifying_biometric = True
        if command_text:
            self._pending_first_command = command_text

        challenge_msg = (
            "Sir, before moving forward, I need you to verify as Anubhav Sir. "
            "Please complete fingerprint authentication, then we can move forward."
        )

        self._is_speaking = True

        # Notify UI and speak challenge
        await self.websocket_send_callback({
            "type": "transcript",
            "role": "assistant",
            "text": challenge_msg,
        })
        dipper_challenge = _get_dipper_audio("challenge_dipper.pcm")
        if dipper_challenge:
            await self.websocket_send_callback({
                "type": "audio_output",
                "data": dipper_challenge,
            })
        else:
            await self.websocket_send_callback({
                "type": "speak",
                "text": challenge_msg,
            })
        await self.websocket_send_callback({
            "type": "orb_state",
            "state": "THINKING",
        })

        # 1. Check availability
        availability = await self.biometric_verifier.check_availability()
        if availability != BiometricAvailability.AVAILABLE:
            self._is_speaking = False
            log_event(logger, logging.WARNING, "biometric_not_available", availability=availability.value)
            await self.websocket_send_callback({
                "type": "transcript",
                "role": "assistant",
                "text": f"Fingerprint verification unavailable ({availability.value}). Access denied.",
            })
            await self._handle_auth_failure(f"Fingerprint hardware unavailable ({availability.value}).")
            return False

        # Inform UI that sensor is ready and listening with timeout window
        timeout_display = int(getattr(self.biometric_verifier, "timeout_seconds", 60))
        await self.websocket_send_callback({
            "type": "transcript",
            "role": "assistant",
            "text": f"Fingerprint sensor active. Please scan your fingerprint now (timeout: {timeout_display}s).",
        })

        # 2. Invoke native Windows Hello
        result = await self.biometric_verifier.request_verification(
            "Please verify your fingerprint to authenticate as Anubhav Sir."
        )

        if result == BiometricResult.VERIFIED:
            self._auth_manager.verify_biometric(True)
            await self.set_state(VictorState.AUTHENTICATED)

            # Interrupt any ongoing challenge audio immediately so greeting starts clean
            await self.websocket_send_callback({
                "type": "audio_interrupted",
            })

            success_msg = "Hello Anubhav Sir. Verification successful. How can I help you?"
            await self.websocket_send_callback({
                "type": "transcript",
                "role": "assistant",
                "text": success_msg,
            })
            dipper_success = _get_dipper_audio("success_dipper.pcm")
            if dipper_success:
                await self.websocket_send_callback({
                    "type": "audio_output",
                    "data": dipper_success,
                })
            else:
                await self.websocket_send_callback({
                    "type": "speak",
                    "text": success_msg,
                })

            # Wait for greeting to finish speaking in browser so Gemini Live will never hear Victor's own voice
            self._is_speaking = True
            await asyncio.sleep(4.8 if dipper_success else 3.2)
            self._is_speaking = False

            await self.websocket_send_callback({
                "type": "greeting_complete",
            })

            # Connect to Gemini Live with clean microphone state
            await self.set_state(VictorState.CONNECTING)
            connected = await self.live_session.start()

            if connected:
                await self.set_state(VictorState.ACTIVE)
                self.watchdog_task = asyncio.create_task(self._inactivity_watchdog())
                self._is_verifying_biometric = False
                log_event(logger, logging.INFO, "biometric_auth_complete_session_active")
                if self._pending_first_command:
                    logger.info(f"Executing pending first command after authentication: '{self._pending_first_command}'")
                    await self.live_session.send_text(self._pending_first_command)
                return True
            else:
                await self.set_state(VictorState.ERROR)
                self._is_verifying_biometric = False
                return False
        else:
            self._is_speaking = False
            log_event(logger, logging.WARNING, "biometric_auth_failed", result=result.value)
            await self._handle_auth_failure(f"Fingerprint verification unsuccessful: {result.value}")
            return False

    async def _handle_auth_failure(self, reason: str):
        """
        Handle biometric verification failure, cancellation, timeout, or unconfigured hardware.
        Immediately blocks commands/tools, terminates session, closes browser, and resets.
        """
        self._is_verifying_biometric = False
        self._is_speaking = False
        self._auth_manager.verify_biometric(False)

        await self.websocket_send_callback({
            "type": "auth_result",
            "success": False,
            "message": reason,
        })
        await self.lock()

    async def handle_audio_input(self, pcm_chunk: bytes):
        """Handle incoming PCM audio from client mic."""
        # Acoustic echo suppression: ignore mic audio while Victor is speaking
        if self._is_speaking:
            return

        # Strictly stream only when session is ACTIVE; ignore during BIOMETRIC_PENDING or locks
        if self.state != VictorState.ACTIVE:
            return

        self.last_activity_time = time.time()  # Reset watchdog on speech
        self._auth_manager.touch_activity()
        await self.live_session.send_audio(pcm_chunk)

    async def handle_command(self, command_text: str) -> bool:
        """Handle incoming text or voice command from user."""
        command_text = (command_text or "").strip()
        if not command_text:
            return False

        if self.state == VictorState.BIOMETRIC_PENDING:
            await self.trigger_biometric_verification(command_text=command_text)
            return False

        if not self.is_authenticated():
            logger.warning("Command attempted while session is not authenticated.")
            await self.websocket_send_callback({
                "type": "transcript",
                "role": "assistant",
                "text": "Please complete PIN and fingerprint verification first, Sir.",
            })
            return False

        self.last_activity_time = time.time()
        self._auth_manager.touch_activity()

        # Echo user command to transcript in UI
        await self.websocket_send_callback({
            "type": "transcript",
            "role": "user",
            "text": command_text,
        })

        # Check for pending memory confirmation (User Consent Flow)
        if hasattr(self, "memory") and self.memory.get_pending_memory():
            cmd_lower = command_text.lower().strip().rstrip(".!")
            affirmative_words = ("yes", "sure", "remember it", "save it", "please do", "yes please", "go ahead", "affirmative", "correct")
            negative_words = ("no", "don't", "dont", "no need", "cancel", "never mind", "nevermind", "skip")

            if any(cmd_lower == w or cmd_lower.startswith(w + " ") for w in affirmative_words):
                pending_item = self.memory.get_pending_memory()
                ok, note = self.memory.confirm_pending_memory()
                if ok:
                    confirm_text = f"Understood, Sir. I have committed '{pending_item['key']}' to your persistent long-term memory."
                    await self.websocket_send_callback({
                        "type": "transcript",
                        "role": "assistant",
                        "text": confirm_text,
                    })
                    return True
            elif any(cmd_lower == w or cmd_lower.startswith(w + " ") for w in negative_words):
                self.memory.clear_pending_memory()
                await self.websocket_send_callback({
                    "type": "transcript",
                    "role": "assistant",
                    "text": "Understood, Sir. I will not save that in memory.",
                })
                return True

        # Check for natural response to a recently delivered proactive reminder
        try:
            from app.reminders.scheduler import get_global_reminder_scheduler
            reminder_sched = getattr(self, "reminder_scheduler", None) or get_global_reminder_scheduler()
            last_rem = reminder_sched.get_last_delivered_reminder()
            if last_rem:
                cmd_lower = command_text.lower().strip().rstrip(".!")
                completion_phrases = (
                    "completed", "done", "yes done", "yes it is done", "yes it's done",
                    "it is done", "it's done", "i completed it", "i finished it", "mark as completed",
                    "mark it completed", "mark completed", "task done", "finished"
                )
                pending_phrases = (
                    "no not yet", "not yet", "not done yet", "no not done yet",
                    "still pending", "haven't done it", "haven't finished", "in progress"
                )

                if any(cmd_lower == p or cmd_lower.startswith(p + " ") for p in completion_phrases):
                    reminder_sched.store.complete_reminder(last_rem.id)
                    reminder_sched.notify_store_updated()
                    reminder_sched.clear_last_delivered_context()
                    confirm_msg = f"Understood, Sir. Marked '{last_rem.work_task}' as completed and stopped future notifications."
                    await self.websocket_send_callback({
                        "type": "transcript",
                        "role": "assistant",
                        "text": confirm_msg,
                    })
                    await self.websocket_send_callback({
                        "type": "speak",
                        "text": confirm_msg,
                    })
                    return True
                elif any(cmd_lower == p or cmd_lower.startswith(p + " ") for p in pending_phrases):
                    reminder_sched.clear_last_delivered_context()
                    ack_msg = f"Understood, Sir. Keeping '{last_rem.work_task}' pending. I will remind you again according to schedule."
                    await self.websocket_send_callback({
                        "type": "transcript",
                        "role": "assistant",
                        "text": ack_msg,
                    })
                    await self.websocket_send_callback({
                        "type": "speak",
                        "text": ack_msg,
                    })
                    return True
        except Exception as rem_err:
            logger.debug(f"Reminder conversational check error: {rem_err}")

        # If live session is in 1011 cooldown, user typing a command cancels wait and reconnects immediately
        if hasattr(self.live_session, "is_in_cooldown") and self.live_session.is_in_cooldown:
            logger.info("User command received during 1011 cooldown; canceling standby and attempting immediate connection.")
            await self.live_session.cancel_cooldown()

        # Submit text turn to Gemini Live
        if self.live_session.is_connected:
            await self.live_session.send_text(command_text)
        else:
            logger.info("Live session not active; attempting connection for text command...")
            connected = await self.live_session.start()
            if connected:
                await self.live_session.send_text(command_text)
            else:
                await self.websocket_send_callback({
                    "type": "transcript",
                    "role": "assistant",
                    "text": "Gemini Live session is currently unavailable. Please try again in a moment, Sir.",
                })
        return True


    async def lock(self):
        """
        Terminates the active session, stops Victor's dedicated Playwright browser driver,
        clears memory, and transitions to CLOSED.
        """
        await self.set_state(VictorState.LOCKING)

        if self.watchdog_task:
            self.watchdog_task.cancel()

        if hasattr(self, "memory"):
            self.memory.session.clear()

        self._auth_manager.lock()
        await self.live_session.close()

        browser_driver = PlaywrightBrowserDriver()
        await browser_driver.stop()

        await self.set_state(VictorState.CLOSED)