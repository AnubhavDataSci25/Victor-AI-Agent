"""
Unit tests for PhoneDeviceManager: pairing handshake, persistence,
liveness tracking, and revocation.
"""

from pathlib import Path
import time
import pytest
from app.phone.device_manager import PhoneDeviceManager
from app.phone.models import PhoneStatus


def test_pairing_handshake_flow(tmp_path: Path):
    store_file = tmp_path / "paired_phone.json"
    mgr = PhoneDeviceManager(store_path=store_file)

    assert mgr.paired_device is None
    assert mgr.check_liveness() == PhoneStatus.UNPAIRED

    # 1. Initiate pairing
    token, pin, expires_at = mgr.initiate_pairing()
    assert len(pin) == 6
    assert mgr.pending_pairing is not None

    # 2. Attempt pairing with wrong PIN
    success, device, err = mgr.complete_pairing("000000", "dev_1", "Pixel 8")
    assert success is False
    assert device is None

    # 3. Successful pairing with PIN
    success, device, msg = mgr.complete_pairing(pin, "dev_1", "Pixel 8 Pro")
    assert success is True
    assert device is not None
    assert device.device_name == "Pixel 8 Pro"
    assert len(device.shared_secret_hex) == 64  # 32 bytes hex
    assert mgr.is_online() is True

    # 4. Config file must be written to disk
    assert store_file.exists()

    # 5. New manager instance loads the saved config
    mgr2 = PhoneDeviceManager(store_path=store_file)
    assert mgr2.paired_device is not None
    assert mgr2.paired_device.device_id == "dev_1"


def test_pairing_expiration(tmp_path: Path):
    store_file = tmp_path / "paired_phone.json"
    mgr = PhoneDeviceManager(store_path=store_file)

    token, pin, expires_at = mgr.initiate_pairing()
    # Force expiration
    mgr.pending_pairing["expires_at"] = time.time() - 10.0

    success, device, err = mgr.complete_pairing(pin, "dev_1", "Pixel 8")
    assert success is False
    assert "expired" in err.lower()


def test_heartbeat_and_liveness_timeout(tmp_path: Path):
    store_file = tmp_path / "paired_phone.json"
    mgr = PhoneDeviceManager(store_path=store_file)

    token, pin, _ = mgr.initiate_pairing()
    mgr.complete_pairing(pin, "dev_1", "Samsung S24")

    # Update heartbeat
    mgr.update_heartbeat(battery_level=85, is_charging=True)
    assert mgr.paired_device.battery_level == 85
    assert mgr.paired_device.is_charging is True
    assert mgr.check_liveness() == PhoneStatus.ONLINE

    # Simulate heartbeat timeout (>30s)
    mgr.paired_device.last_seen = time.time() - 40.0
    assert mgr.check_liveness() == PhoneStatus.OFFLINE
    assert mgr.is_online() is False


def test_device_revocation_unpair(tmp_path: Path):
    store_file = tmp_path / "paired_phone.json"
    mgr = PhoneDeviceManager(store_path=store_file)

    token, pin, _ = mgr.initiate_pairing()
    mgr.complete_pairing(pin, "dev_1", "OnePlus 12")
    assert store_file.exists()

    # Unpair
    res = mgr.unpair_device()
    assert res is True
    assert mgr.paired_device is None
    assert not store_file.exists()
    assert mgr.check_liveness() == PhoneStatus.UNPAIRED
