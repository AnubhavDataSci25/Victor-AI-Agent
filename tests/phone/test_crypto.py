"""
Unit tests for Victor Phone Integration V1 cryptographic engine.
Tests AES-256-GCM payload encryption, HMAC-SHA256 signatures,
sliding-window nonce deduplication, and timestamp-based replay defense.
"""

import time
import pytest
from app.phone.crypto import PhoneCrypto, PhoneCryptoError
from app.phone.models import MessageType, PhoneMessage


def test_pairing_token_and_pin_generation():
    crypto = PhoneCrypto()
    token = crypto.generate_pairing_token()
    pin = crypto.generate_pairing_pin()

    assert isinstance(token, str) and len(token) == 32  # 16 bytes hex
    assert isinstance(pin, str) and len(pin) == 6
    assert pin.isdigit()


def test_replay_protection_timestamp_and_nonce():
    crypto = PhoneCrypto()
    now = time.time()
    nonce1 = "nonce_abc_123"

    # 1. Valid fresh message
    assert crypto.verify_replay_protection(nonce1, now, current_time=now) is True

    # 2. Replay attack: same nonce repeated within tolerance
    assert crypto.verify_replay_protection(nonce1, now + 1.0, current_time=now + 1.0) is False

    # 3. Expired timestamp: message from 45 seconds ago (tolerance is 30s)
    old_timestamp = now - 45.0
    assert crypto.verify_replay_protection("nonce_expired", old_timestamp, current_time=now) is False

    # 4. Future timestamp: message 40 seconds into the future
    future_timestamp = now + 40.0
    assert crypto.verify_replay_protection("nonce_future", future_timestamp, current_time=now) is False


def test_hmac_sha256_signing_and_verification():
    crypto = PhoneCrypto()
    secret = crypto.generate_shared_secret()

    msg = PhoneMessage(
        type=MessageType.COMMAND,
        action="resolve_contact",
        payload={"query": "Anubhav"},
    )

    # Sign message
    msg.signature = crypto.sign_message(msg, secret)
    assert len(msg.signature) == 64  # SHA256 hex is 64 chars

    # Verify signature passes
    assert crypto.verify_signature(msg, secret) is True

    # Tampering with payload must cause verification failure
    msg_tampered = msg.model_copy(deep=True)
    msg_tampered.payload = {"query": "Hacker"}
    assert crypto.verify_signature(msg_tampered, secret) is False

    # Wrong secret key must fail
    wrong_secret = crypto.generate_shared_secret()
    assert crypto.verify_signature(msg, wrong_secret) is False


def test_aes_256_gcm_payload_encryption_and_decryption():
    crypto = PhoneCrypto()
    secret = crypto.generate_shared_secret()

    original_payload = {
        "contact_name": "John Doe",
        "phone_number": "+1234567890",
        "nested": {"key": "value", "count": 42},
    }

    encrypted_b64 = crypto.encrypt_payload(original_payload, secret)
    assert isinstance(encrypted_b64, str)
    assert encrypted_b64 != str(original_payload)

    # Decrypt and compare
    decrypted = crypto.decrypt_payload(encrypted_b64, secret)
    assert decrypted == original_payload

    # Tampered ciphertext must raise PhoneCryptoError
    tampered_b64 = encrypted_b64[:-4] + "AAAA"
    with pytest.raises(PhoneCryptoError):
        crypto.decrypt_payload(tampered_b64, secret)

    # Decryption with wrong key must raise PhoneCryptoError
    wrong_secret = crypto.generate_shared_secret()
    with pytest.raises(PhoneCryptoError):
        crypto.decrypt_payload(encrypted_b64, wrong_secret)
