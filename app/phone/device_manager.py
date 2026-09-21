"""
Device manager for Victor Phone Integration V1.
Handles cryptographic pairing handshake, device persistence, heartbeat monitoring,
connection state tracking, and immediate device revocation / unpairing.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
import time
from typing import Any, Optional

from app.logging import get_logger
from app.phone.crypto import PhoneCrypto
from app.phone.models import PhoneDevice, PhoneStatus

logger = get_logger("phone.device_manager")

_DEFAULT_STORE = Path(__file__).resolve().parent.parent.parent / "config" / "paired_phone.json"


class PhoneDeviceManager:
    PAIRING_TTL_SECONDS = 300.0  # 5 minutes
    HEARTBEAT_TIMEOUT_SECONDS = 30.0

    def __init__(self, store_path: Optional[Path] = None, crypto: Optional[PhoneCrypto] = None) -> None:
        self.store_path = store_path or _DEFAULT_STORE
        self.crypto = crypto or PhoneCrypto()
        self.paired_device: Optional[PhoneDevice] = None
        self.pending_pairing: Optional[dict[str, Any]] = None
        self.load_paired_device()

    def load_paired_device(self) -> Optional[PhoneDevice]:
        """Loads paired device configuration from storage if it exists."""
        if not self.store_path.exists():
            self.paired_device = None
            return None

        try:
            raw = self.store_path.read_text(encoding="utf-8")
            data = json.loads(raw)
            device = PhoneDevice.model_validate(data)
            # Default to OFFLINE on initial process boot until WebSocket connects
            device.status = PhoneStatus.OFFLINE
            self.paired_device = device
            logger.info(f"Loaded paired phone device: '{device.device_name}' (ID: {device.device_id})")
            return self.paired_device
        except Exception as e:
            logger.error(f"Failed to load paired phone config: {e}")
            self.paired_device = None
            return None

    def save_paired_device(self) -> None:
        """Persists paired device configuration to storage securely."""
        if not self.paired_device:
            if self.store_path.exists():
                try:
                    self.store_path.unlink()
                except Exception as e:
                    logger.warning(f"Failed to delete {self.store_path}: {e}")
            return

        try:
            self.store_path.parent.mkdir(parents=True, exist_ok=True)
            data = self.paired_device.model_dump()
            self.store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
            logger.info(f"Saved paired phone device configuration to {self.store_path}")
        except Exception as e:
            logger.error(f"Failed to save paired phone config: {e}")

    def initiate_pairing(self) -> tuple[str, str, float]:
        """
        Initiates a new pairing session from the Victor PC UI.
        Generates a secure pairing token and a user-friendly 6-digit PIN.
        Returns (pairing_token, pairing_pin, expires_at).
        """
        token = self.crypto.generate_pairing_token()
        pin = self.crypto.generate_pairing_pin()
        expires_at = time.time() + self.PAIRING_TTL_SECONDS
        self.pending_pairing = {
            "token": token,
            "pin": pin,
            "expires_at": expires_at,
        }
        logger.info(f"Initiated phone pairing session (PIN: {pin}, expires in 5 min)")
        return token, pin, expires_at

    def complete_pairing(
        self,
        token_or_pin: str,
        device_id: str,
        device_name: str,
    ) -> tuple[bool, Optional[PhoneDevice], str]:
        """
        Completes pairing requested by Android Companion.
        Verifies token or PIN against active pairing session, derives shared secret,
        and saves device profile.
        """
        if not self.pending_pairing:
            return False, None, "No active pairing session on PC. Please initiate pairing from Victor UI."

        if time.time() > self.pending_pairing["expires_at"]:
            self.pending_pairing = None
            return False, None, "Pairing session expired. Please generate a new pairing code."

        valid_token = self.pending_pairing["token"]
        valid_pin = self.pending_pairing["pin"]

        token_clean = (token_or_pin or "").strip()
        if token_clean != valid_token and token_clean != valid_pin:
            return False, None, "Invalid pairing code or PIN."

        # Generate fresh 256-bit symmetric shared secret
        shared_secret = self.crypto.generate_shared_secret()

        device = PhoneDevice(
            device_id=device_id.strip(),
            device_name=device_name.strip() or "Android Device",
            paired_at=time.time(),
            shared_secret_hex=shared_secret,
            last_seen=time.time(),
            status=PhoneStatus.ONLINE,
        )

        self.paired_device = device
        self.pending_pairing = None
        self.save_paired_device()

        logger.info(f"Successfully paired device '{device.device_name}' (ID: {device.device_id})")
        return True, device, "Pairing successful."

    def unpair_device(self) -> bool:
        """
        Immediately revokes and unpairs the connected device.
        Wipes secret and storage, transitioning state to UNPAIRED.
        """
        if not self.paired_device:
            return False

        old_name = self.paired_device.device_name
        self.paired_device = None
        self.pending_pairing = None
        self.save_paired_device()

        logger.info(f"Revoked and unpaired phone device: '{old_name}'")
        return True

    def update_heartbeat(self, battery_level: Optional[int] = None, is_charging: Optional[bool] = None) -> None:
        """Updates last_seen and battery status for the paired device."""
        if self.paired_device:
            self.paired_device.last_seen = time.time()
            self.paired_device.status = PhoneStatus.ONLINE
            if battery_level is not None:
                self.paired_device.battery_level = battery_level
            if is_charging is not None:
                self.paired_device.is_charging = is_charging

    def check_liveness(self) -> PhoneStatus:
        """Checks if the device is currently active or has timed out."""
        if not self.paired_device:
            return PhoneStatus.UNPAIRED

        elapsed = time.time() - self.paired_device.last_seen
        if elapsed > self.HEARTBEAT_TIMEOUT_SECONDS:
            if self.paired_device.status != PhoneStatus.OFFLINE:
                self.paired_device.status = PhoneStatus.OFFLINE
                logger.info(f"Phone device '{self.paired_device.device_name}' is now OFFLINE (last seen {elapsed:.1f}s ago)")

        return self.paired_device.status

    def is_online(self) -> bool:
        """Returns True if a device is paired and currently online."""
        return self.check_liveness() == PhoneStatus.ONLINE

    def get_status_summary(self) -> dict[str, Any]:
        """Returns a non-sensitive summary of phone connection status."""
        status = self.check_liveness()
        if not self.paired_device:
            return {
                "paired": False,
                "status": PhoneStatus.UNPAIRED.value,
                "device_name": None,
                "battery_level": None,
                "is_charging": None,
            }

        return {
            "paired": True,
            "status": status.value,
            "device_name": self.paired_device.device_name,
            "device_id": self.paired_device.device_id,
            "battery_level": self.paired_device.battery_level,
            "is_charging": self.paired_device.is_charging,
            "last_seen_seconds_ago": round(time.time() - self.paired_device.last_seen, 1),
        }
