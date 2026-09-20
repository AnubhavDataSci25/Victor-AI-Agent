"""
Unit tests for Victor 2.0 authentication and secret store.
"""

import tempfile
from pathlib import Path
import pytest

from app.auth.hashing import hash_phrase, verify_phrase
from app.auth.pin import normalize_pin
from app.auth.store import SecretStore
from app.auth.manager import AuthManager, AuthState
from app.config import SecurityConfig


def test_argon2id_hashing():
    phrase = "1234"
    h = hash_phrase(phrase)
    assert h.startswith("$argon2id$")
    assert verify_phrase("1234", h) is True
    assert verify_phrase("4321", h) is False
    assert verify_phrase("", h) is False


def test_pin_normalization():
    assert normalize_pin(" 1 2 3 4 ") == "1234"
    assert normalize_pin("12-34") == "1234"
    assert normalize_pin("  9876  ") == "9876"


def test_secret_store_temporary_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        secrets_path = Path(tmpdir) / "secrets.yaml"
        store = SecretStore(secrets_path)

        assert store.is_configured() is False
        assert store.get_phrase_hash() is None

        # Auto-provision default
        h = store.ensure_configured("9876")
        assert store.is_configured() is True
        assert verify_phrase("9876", h) is True

        # Idempotent call doesn't overwrite
        h2 = store.ensure_configured("0000")
        assert h2 == h
        assert verify_phrase("9876", store.get_phrase_hash()) is True


def test_auth_manager_lifecycle():
    with tempfile.TemporaryDirectory() as tmpdir:
        secrets_path = Path(tmpdir) / "secrets.yaml"
        store = SecretStore(secrets_path)
        store.set_phrase_hash(hash_phrase("1234"))

        sec_config = SecurityConfig(
            auth_mode="pin",
            max_failed_attempts=3,
            lockout_seconds=60,
            session_timeout_minutes=15,
            secrets_path=str(secrets_path),
        )

        simulated_time = 1000.0

        def fake_clock():
            return simulated_time

        manager = AuthManager(sec_config, store, clock=fake_clock)
        assert manager.state == AuthState.LOCKED

        # Failed attempt 1
        res1 = manager.authenticate("0000")
        assert res1.success is False
        assert res1.locked_out is False
        assert manager.state == AuthState.LOCKED

        # Failed attempt 2
        res2 = manager.authenticate("1111")
        assert res2.success is False
        assert res2.locked_out is False

        # Failed attempt 3 -> triggers lockout
        res3 = manager.authenticate("2222")
        assert res3.success is False
        assert res3.locked_out is True
        assert "Too many attempts" in res3.message
        assert manager.is_locked_out() is True
        assert manager.lockout_remaining_seconds() == 60

        # Attempt while locked out
        res_locked = manager.authenticate("1234")
        assert res_locked.success is False
        assert res_locked.locked_out is True
        assert "Please try again in" in res_locked.message

        # Fast-forward time past lockout
        simulated_time += 61.0
        assert manager.is_locked_out() is False

        # Step 1: Successful auth with spaces (PIN normalization) -> transitions to PIN_VERIFIED
        res_ok = manager.authenticate(" 1 2 3 4 ")
        assert res_ok.success is True
        assert manager.state == AuthState.PIN_VERIFIED
        # Enforce PIN_VERIFIED != AUTHENTICATED
        assert manager.is_unlocked() is False

        # Step 2: Biometric verification completes authentication
        bio_ok = manager.verify_biometric(True)
        assert bio_ok is True
        assert manager.is_unlocked() is True
        assert manager.state == AuthState.AUTHENTICATED

        # Manual lock
        manager.lock()
        assert manager.state == AuthState.LOCKED


@pytest.mark.asyncio
async def test_victor_session_manager_auth_integration():
    from unittest.mock import AsyncMock
    from app.agent.session_manager import VictorSessionManager
    from app.agent.state import VictorState
    from app.auth.biometric import BaseBiometricVerifier, BiometricAvailability, BiometricResult

    class MockVerifier(BaseBiometricVerifier):
        async def check_availability(self):
            return BiometricAvailability.AVAILABLE
        async def request_verification(self, prompt: str = ""):
            return BiometricResult.VERIFIED

    events = []

    async def mock_ws_send(data):
        events.append(data)

    sm = VictorSessionManager(websocket_send_callback=mock_ws_send, biometric_verifier=MockVerifier())
    # Mock out live_session.start so it does not connect to live Gemini over network in unit test
    sm.live_session.start = AsyncMock(return_value=True)

    # Wrong PIN
    success, msg = await sm.authenticate("9999")
    assert success is False
    assert sm.state == VictorState.LOCKED

    # Correct PIN -> Enters BIOMETRIC_PENDING without starting Gemini Live
    success, msg = await sm.authenticate("081225")
    assert success is True
    assert sm.state == VictorState.BIOMETRIC_PENDING
    sm.live_session.start.assert_not_called()

    # User initiates interaction -> triggers biometric verification -> ACTIVE
    bio_success = await sm.trigger_biometric_verification()
    assert bio_success is True
    assert sm.state == VictorState.ACTIVE
    sm.live_session.start.assert_awaited_once()

    # Clean up
    await sm.lock()
    assert sm.state == VictorState.CLOSED


def test_auth_manager_10_minute_lockout_config():
    """Verify default security config enforces 3 attempts and 600s (10 mins) lockout."""
    from app.config import load_config
    cfg = load_config()
    assert cfg.security.max_failed_attempts == 3
    assert cfg.security.lockout_seconds == 600
