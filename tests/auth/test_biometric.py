"""
Comprehensive unit tests for Victor 2.0 Windows Hello fingerprint 2FA authentication.

Test suite covers:
1. Successful 2FA authentication (PIN -> BIOMETRIC_PENDING -> Fingerprint VERIFIED -> ACTIVE)
2. Failed fingerprint (locks session, terminates browser driver, requires fresh PIN+fingerprint)
3. Cancelled fingerprint
4. Unavailable / unconfigured fingerprint hardware (never falls back to PIN-only)
5. Incorrect PIN (never reaches biometric)
6. Commands attempted before biometric verification (blocked, triggers challenge)
7. Gemini tool calls attempted before verification (blocked below conversational model)
8. Browser shutdown after biometric failure
9. Preservation of existing high-risk PermissionEngine confirmations after successful authentication
10. Strict enforcement of PIN_VERIFIED != AUTHENTICATED
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.agent.session_manager import VictorSessionManager
from app.agent.state import VictorState
from app.auth.biometric import (
    BaseBiometricVerifier,
    BiometricAvailability,
    BiometricResult,
)
from app.auth.manager import AuthManager, AuthState
from app.config import SecurityConfig
from app.live.tool_calls import LiveToolDispatcher
from app.tools.permissions import PermissionDecision, PermissionEngine, PermissionLevel


class MockVerifier(BaseBiometricVerifier):
    def __init__(
        self,
        availability: BiometricAvailability = BiometricAvailability.AVAILABLE,
        result: BiometricResult = BiometricResult.VERIFIED,
    ):
        self._availability = availability
        self._result = result
        self.check_availability_calls = 0
        self.request_verification_calls = 0

    async def check_availability(self) -> BiometricAvailability:
        self.check_availability_calls += 1
        return self._availability

    async def request_verification(self, prompt: str = "") -> BiometricResult:
        self.request_verification_calls += 1
        return self._result


@pytest.fixture
def session_setup():
    events = []

    async def mock_ws_send(data):
        events.append(data)

    verifier = MockVerifier()
    sm = VictorSessionManager(websocket_send_callback=mock_ws_send, biometric_verifier=verifier)
    sm.live_session.start = AsyncMock(return_value=True)
    sm.live_session.close = AsyncMock()
    return sm, verifier, events


# 1. Successful Authentication Flow
@pytest.mark.asyncio
async def test_successful_2fa_authentication(session_setup):
    sm, verifier, events = session_setup

    # Step 1: Valid PIN entered
    success, msg = await sm.authenticate("081225")
    assert success is True
    assert sm.state == VictorState.BIOMETRIC_PENDING
    assert sm.is_authenticated() is False
    sm.live_session.start.assert_not_called()

    # Step 2: User says "Hello Victor" or triggers interaction
    res = await sm.trigger_biometric_verification()
    assert res is True
    assert sm.state == VictorState.ACTIVE
    assert sm.is_authenticated() is True
    sm.live_session.start.assert_awaited_once()

    # Verify challenge speech and transcript
    transcripts = [e["text"] for e in events if e.get("type") == "transcript"]
    assert any("verify as Anubhav Sir" in t for t in transcripts)
    assert any("Hello Anubhav Sir. Verification successful." in t for t in transcripts)


# 2. Failed Fingerprint Authentication
@pytest.mark.asyncio
async def test_failed_fingerprint_authentication(session_setup):
    sm, verifier, events = session_setup
    verifier._result = BiometricResult.RETRIES_EXHAUSTED

    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING

    with patch("app.agent.session_manager.PlaywrightBrowserDriver") as mock_browser_cls:
        mock_driver = MagicMock()
        mock_driver.stop = AsyncMock()
        mock_browser_cls.return_value = mock_driver

        res = await sm.trigger_biometric_verification()
        assert res is False
        assert sm.state == VictorState.CLOSED
        assert sm.is_authenticated() is False
        # Browser driver must be stopped
        mock_driver.stop.assert_awaited_once()


# 3. Cancelled Fingerprint Verification
@pytest.mark.asyncio
async def test_cancelled_fingerprint_authentication(session_setup):
    sm, verifier, events = session_setup
    verifier._result = BiometricResult.CANCELED

    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING

    res = await sm.trigger_biometric_verification()
    assert res is False
    assert sm.state == VictorState.CLOSED
    assert sm.is_authenticated() is False


# 4. Unavailable or Unconfigured Fingerprint Device (No Fallback to PIN-only)
@pytest.mark.asyncio
async def test_unavailable_fingerprint_hardware(session_setup):
    sm, verifier, events = session_setup
    verifier._availability = BiometricAvailability.DEVICE_NOT_PRESENT

    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING

    res = await sm.trigger_biometric_verification()
    assert res is False
    assert sm.state == VictorState.CLOSED
    assert sm.is_authenticated() is False
    # Never falls back to PIN-only access
    assert verifier.request_verification_calls == 0


# 5. Incorrect PIN Never Reaches Biometric Verification
@pytest.mark.asyncio
async def test_incorrect_pin_never_reaches_biometric(session_setup):
    sm, verifier, events = session_setup

    success, msg = await sm.authenticate("000000")
    assert success is False
    assert sm.state == VictorState.LOCKED
    assert sm.is_authenticated() is False
    assert verifier.check_availability_calls == 0
    assert verifier.request_verification_calls == 0


# 6. Commands Attempted Before Biometric Verification are Blocked
@pytest.mark.asyncio
async def test_commands_blocked_before_biometric_verification(session_setup):
    sm, verifier, events = session_setup

    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING

    # Attempt normal command before completing fingerprint verification
    cmd_result = await sm.handle_command("open calculator")
    assert cmd_result is False
    # Verifies the challenge was triggered
    assert verifier.request_verification_calls == 1


# 7. Gemini Tool Calls Blocked Below the Conversational Model
@pytest.mark.asyncio
async def test_gemini_tool_calls_blocked_below_llm(session_setup):
    sm, verifier, events = session_setup
    dispatcher = LiveToolDispatcher(sm)

    # In LOCKED state
    fc = MagicMock()
    fc.name = "read_file"
    fc.args = {"path": "test.txt"}
    fc.id = "call_123"

    resp = await dispatcher.handle_function_call(fc)
    assert resp.response["status"] == "failed"
    assert "Access Denied" in resp.response["error"]

    # In BIOMETRIC_PENDING state (PIN verified, but no fingerprint)
    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING
    assert sm.is_authenticated() is False

    resp2 = await dispatcher.handle_function_call(fc)
    assert resp2.response["status"] == "failed"
    assert "Access Denied" in resp2.response["error"]


# 8. Browser Shutdown After Biometric Failure
@pytest.mark.asyncio
async def test_browser_shutdown_after_biometric_failure(session_setup):
    sm, verifier, events = session_setup
    verifier._result = BiometricResult.ERROR

    await sm.authenticate("081225")
    with patch("app.agent.session_manager.PlaywrightBrowserDriver") as mock_browser_cls:
        mock_driver = MagicMock()
        mock_driver.stop = AsyncMock()
        mock_browser_cls.return_value = mock_driver

        await sm.trigger_biometric_verification()
        mock_driver.stop.assert_awaited_once()
        assert sm.state == VictorState.CLOSED


# 9. Preservation of High-Risk PermissionEngine Confirmations After Successful Auth
@pytest.mark.asyncio
async def test_preservation_of_permission_engine_after_auth(session_setup):
    sm, verifier, events = session_setup

    # Complete 2FA
    await sm.authenticate("081225")
    await sm.trigger_biometric_verification()
    assert sm.is_authenticated() is True

    # PermissionEngine must still enforce SAFE, LOW, MEDIUM, HIGH, BLOCKED rules
    engine = PermissionEngine()
    assert engine.decide(PermissionLevel.SAFE) == PermissionDecision.ALLOWED
    assert engine.decide(PermissionLevel.LOW) == PermissionDecision.ALLOWED

    # High-risk actions require user confirmation even when authenticated
    assert engine.decide(PermissionLevel.MEDIUM) == PermissionDecision.REQUIRES_CONFIRMATION
    assert engine.decide(PermissionLevel.HIGH) == PermissionDecision.REQUIRES_CONFIRMATION
    assert engine.decide(PermissionLevel.BLOCKED) == PermissionDecision.DENIED

    # With explicit confirmation
    assert engine.decide(PermissionLevel.HIGH, confirmed=True) == PermissionDecision.ALLOWED


# 10. Strict Enforcement of PIN_VERIFIED != AUTHENTICATED
def test_pin_verified_not_equal_authenticated():
    store = MagicMock()
    store.is_configured.return_value = True
    # "1234" hash
    from app.auth.hashing import hash_phrase
    store.get_phrase_hash.return_value = hash_phrase("1234")

    cfg = SecurityConfig(auth_mode="pin")
    manager = AuthManager(cfg, store)

    # Initially LOCKED
    assert manager.state == AuthState.LOCKED
    assert manager.is_unlocked() is False
    assert manager.is_pin_verified() is False

    # Enter PIN
    res = manager.authenticate("1234")
    assert res.success is True
    # PIN_VERIFIED != AUTHENTICATED
    assert manager.state == AuthState.PIN_VERIFIED
    assert manager.is_unlocked() is False
    assert manager.is_pin_verified() is True

    # Biometric verification succeeds
    assert manager.verify_biometric(True) is True
    assert manager.state == AuthState.AUTHENTICATED
    assert manager.is_unlocked() is True


# 11. Raw Audio In BIOMETRIC_PENDING Does Not Trigger Verification
@pytest.mark.asyncio
async def test_audio_input_in_biometric_pending_ignored(session_setup):
    sm, verifier, events = session_setup
    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING

    # Send raw audio (including loud background noise / music)
    loud_pcm = b"\xff\x7f" * 1024  # max amplitude 16-bit PCM
    await sm.handle_audio_input(loud_pcm)

    # Must NOT have triggered verification or touched verifier
    assert verifier.request_verification_calls == 0
    assert sm.state == VictorState.BIOMETRIC_PENDING


# 12. User Command In BIOMETRIC_PENDING Triggers Biometric Verification Flow
@pytest.mark.asyncio
async def test_first_command_triggers_biometric_verification(session_setup):
    sm, verifier, events = session_setup
    await sm.authenticate("081225")
    assert sm.state == VictorState.BIOMETRIC_PENDING

    # User speaks first command: "Hello Victor"
    result = await sm.handle_command("Hello Victor")
    assert result is False  # Blocked until biometric succeeds
    assert verifier.request_verification_calls == 1
    assert sm.state == VictorState.ACTIVE
    assert sm.is_authenticated() is True
    assert sm._pending_first_command == "Hello Victor"


# 13. Continuous Audio Streaming In ACTIVE & Speech Suppression
@pytest.mark.asyncio
async def test_continuous_audio_streaming_and_speech_suppression(session_setup):
    sm, verifier, events = session_setup
    sm.live_session.send_audio = AsyncMock()

    # Authenticate fully
    await sm.authenticate("081225")
    await sm.handle_command("Hello Victor")
    assert sm.state == VictorState.ACTIVE

    # Normal audio packet in ACTIVE streams seamlessly
    test_pcm = b"\x00\x20" * 512
    await sm.handle_audio_input(test_pcm)
    sm.live_session.send_audio.assert_called_once_with(test_pcm)

    # When Victor is speaking, microphone audio is strictly suppressed
    sm.live_session.send_audio.reset_mock()
    sm._is_speaking = True
    await sm.handle_audio_input(test_pcm)
    sm.live_session.send_audio.assert_not_called()


