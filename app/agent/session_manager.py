"""
VictorSessionManager — manages the lifecycle of a single browser
session from authentication through Gemini Live connection to lockdown.
"""

import asyncio
import time
import logging

from app.agent.state import VictorState
from app.auth.manager import AuthManager
from app.auth.store import SecretStore
from app.config import load_config
from app.live.session import LiveSessionManager
from app.tools.browser.playwright_driver import PlaywrightBrowserDriver

logger = logging.getLogger(__name__)


class VictorSessionManager:
    SESSION_TIMEOUT_SECONDS = 900  # 15 minutes

    def __init__(self, websocket_send_callback):
        self.state = VictorState.LOCKED
        self.websocket_send_callback = websocket_send_callback
        self.live_session = LiveSessionManager(self)

        # Load config for auth settings
        self._config = load_config()
        self._secret_store = SecretStore(self._config.security.secrets_path)
        self._secret_store.ensure_configured()
        self._auth_manager = AuthManager(self._config.security, self._secret_store)

        # Security: Inactivity tracking
        self.last_activity_time = time.time()
        self.watchdog_task = None

    async def set_state(self, new_state: VictorState):
        self.state = new_state
        self.last_activity_time = time.time()  # Reset timer on state shifts
        await self.websocket_send_callback({
            "type": "session_state",
            "state": self.state.value
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
        if self.state not in (VictorState.LOCKED, VictorState.CLOSED):
            return False, "Session is already active."

        await self.set_state(VictorState.AUTHENTICATING)

        auth_result = self._auth_manager.authenticate(credential)

        if auth_result.success:
            await self.set_state(VictorState.AUTH_SUCCESS)
            await self.set_state(VictorState.CONNECTING)
            connected = await self.live_session.start()

            if connected:
                await self.set_state(VictorState.ACTIVE)
                # Start the security watchdog
                self.watchdog_task = asyncio.create_task(self._inactivity_watchdog())
                return True, auth_result.message
            else:
                await self.set_state(VictorState.ERROR)
                return False, "Failed to connect to Gemini Live session."
        else:
            await self.set_state(VictorState.LOCKED)
            return False, auth_result.message

    async def handle_audio_input(self, pcm_chunk: bytes):
        if self.state == VictorState.ACTIVE:
            self.last_activity_time = time.time()  # Reset watchdog on speech
            self._auth_manager.touch_activity()
            await self.live_session.send_audio(pcm_chunk)

    async def lock(self):
        await self.set_state(VictorState.LOCKING)

        if self.watchdog_task:
            self.watchdog_task.cancel()

        self._auth_manager.lock()
        await self.live_session.close()

        browser_driver = PlaywrightBrowserDriver()
        await browser_driver.stop()

        await self.set_state(VictorState.CLOSED)