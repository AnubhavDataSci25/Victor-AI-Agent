"""
WebSocket server endpoint for Victor Phone Integration V1.
Maintains persistent connection with Android companion, handles authentication and pairing,
dispatches commands, processes minimal notification events and incoming call states,
and relays updates to Victor's PC SessionManager and HUD UI.
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from typing import Any, Callable, Optional
from fastapi import WebSocket, WebSocketDisconnect

from app.logging import get_logger
from app.phone.crypto import PhoneCrypto
from app.phone.device_manager import PhoneDeviceManager
from app.phone.gateway import PhoneGateway
from app.phone.models import (
    CallStatus,
    MessageType,
    PhoneMessage,
    PhoneStatus,
)

logger = get_logger("phone.server")


def get_local_ip() -> str:
    """Detects local LAN IPv4 address for companion pairing."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


class PhoneServer:
    def __init__(
        self,
        device_manager: Optional[PhoneDeviceManager] = None,
        gateway: Optional[PhoneGateway] = None,
        crypto: Optional[PhoneCrypto] = None,
    ) -> None:
        self.device_manager = device_manager or PhoneDeviceManager()
        self.crypto = crypto or self.device_manager.crypto
        self.gateway = gateway or PhoneGateway(self.device_manager, self.crypto)
        self.gateway.set_command_dispatcher(self.dispatch_command)

        self.active_websocket: Optional[WebSocket] = None
        self._pending_responses: dict[str, asyncio.Future[dict[str, Any]]] = {}
        self._ui_notify_callback: Optional[Callable[[dict[str, Any]], Any]] = None

    def set_ui_notify_callback(self, callback: Callable[[dict[str, Any]], Any]) -> None:
        """Sets callback to push notifications and incoming calls down to Victor's PC UI."""
        self._ui_notify_callback = callback

    async def _notify_ui(self, data: dict[str, Any]) -> None:
        """Pushes event data to the Victor PC UI if callback is registered."""
        if self._ui_notify_callback:
            try:
                res = self._ui_notify_callback(data)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as e:
                logger.error(f"Error notifying UI: {e}")

    async def dispatch_command(self, message: PhoneMessage, timeout: float = 15.0) -> dict[str, Any]:
        """
        Sends a command message to the companion phone and awaits response future.
        """
        if not self.active_websocket:
            return {"success": False, "error": "No phone WebSocket connection active."}

        fut: asyncio.Future[dict[str, Any]] = asyncio.get_event_loop().create_future()
        self._pending_responses[message.id] = fut

        try:
            raw_text = message.model_dump_json()
            await self.active_websocket.send_text(raw_text)
            response = await asyncio.wait_for(fut, timeout=timeout)
            return response
        except asyncio.TimeoutError:
            logger.warning(f"Command '{message.action}' (ID: {message.id}) timed out after {timeout}s")
            return {"success": False, "error": f"Command '{message.action}' timed out on phone."}
        finally:
            self._pending_responses.pop(message.id, None)

    async def handle_websocket(self, websocket: WebSocket) -> None:
        """Main WebSocket loop for `/ws/phone` endpoint."""
        await websocket.accept()
        self.active_websocket = websocket
        logger.info("Android companion connected to /ws/phone")
        if self.device_manager.paired_device:
            self.device_manager.paired_device.status = PhoneStatus.ONLINE
            self.device_manager.paired_device.last_seen = time.time()
            await self._notify_ui({
                "type": "phone_status",
                "status": PhoneStatus.ONLINE.value,
                "device_name": self.device_manager.paired_device.device_name,
            })

        try:
            while True:
                data = await websocket.receive_text()
                try:
                    payload = json.loads(data)
                except Exception:
                    logger.warning("Received invalid JSON from phone")
                    continue

                msg_type = payload.get("type")

                # 1. Pairing Request Handshake
                if msg_type == MessageType.PAIR_REQUEST.value:
                    req_payload = payload.get("payload", {})
                    token_or_pin = req_payload.get("token", "")
                    device_id = req_payload.get("device_id", "")
                    device_name = req_payload.get("device_name", "Android Companion")

                    success, device, msg = self.device_manager.complete_pairing(
                        token_or_pin=token_or_pin,
                        device_id=device_id,
                        device_name=device_name,
                    )

                    if success and device:
                        resp = PhoneMessage(
                            type=MessageType.PAIR_RESPONSE,
                            action="pair_success",
                            payload={
                                "success": True,
                                "device_id": device.device_id,
                                "device_name": device.device_name,
                                "shared_secret_hex": device.shared_secret_hex,
                            },
                        )
                        # Sign pairing response
                        resp.signature = self.crypto.sign_message(resp, device.shared_secret_hex)
                        await websocket.send_text(resp.model_dump_json())
                        await self._notify_ui({
                            "type": "phone_status",
                            "status": PhoneStatus.ONLINE.value,
                            "device_name": device.device_name,
                        })
                    else:
                        resp = PhoneMessage(
                            type=MessageType.ERROR,
                            action="pair_failed",
                            payload={"success": False, "error": msg},
                        )
                        await websocket.send_text(resp.model_dump_json())
                    continue

                # 2. General Authenticated Messages (requires active paired device)
                device = self.device_manager.paired_device
                if not device:
                    err_msg = PhoneMessage(
                        type=MessageType.ERROR,
                        action="unauthorized",
                        payload={"error": "Device is not paired with Victor."},
                    )
                    await websocket.send_text(err_msg.model_dump_json())
                    continue

                try:
                    msg = PhoneMessage.model_validate(payload)
                except Exception as e:
                    logger.warning(f"Malformed PhoneMessage: {e}")
                    continue

                # Verify replay attack protection
                if not self.crypto.verify_replay_protection(msg.nonce, msg.timestamp):
                    logger.warning(f"Rejected stale/replayed message {msg.id}")
                    continue

                # Verify cryptographic signature
                if not self.crypto.verify_signature(msg, device.shared_secret_hex):
                    logger.warning(f"Signature mismatch on message {msg.id}")
                    continue

                # Any valid message from the device confirms it is actively online
                device.last_seen = time.time()
                device.status = PhoneStatus.ONLINE

                # 3. Message Routing
                if msg.type == MessageType.HEARTBEAT:
                    battery = msg.payload.get("battery_level")
                    charging = msg.payload.get("is_charging")
                    self.device_manager.update_heartbeat(battery, charging)
                    ack = PhoneMessage(
                        type=MessageType.HEARTBEAT,
                        action="heartbeat_ack",
                        payload={"timestamp": time.time()},
                    )
                    ack.signature = self.crypto.sign_message(ack, device.shared_secret_hex)
                    await websocket.send_text(ack.model_dump_json())
                    await self._notify_ui({
                        "type": "phone_status",
                        "status": PhoneStatus.ONLINE.value,
                        "device_name": device.device_name,
                        "battery_level": battery,
                        "is_charging": charging,
                    })

                elif msg.type == MessageType.COMMAND_RESPONSE:
                    # Resolve pending future for command
                    fut = self._pending_responses.get(msg.id)
                    if fut and not fut.done():
                        fut.set_result(msg.payload)

                elif msg.type == MessageType.EVENT:
                    await self._handle_incoming_event(msg.action, msg.payload)

        except WebSocketDisconnect:
            logger.info("Android companion disconnected.")
        except Exception as e:
            logger.error(f"Error in phone WebSocket connection: {e}")
        finally:
            self.active_websocket = None
            if self.device_manager.paired_device:
                self.device_manager.paired_device.status = PhoneStatus.OFFLINE
                await self._notify_ui({
                    "type": "phone_status",
                    "status": PhoneStatus.OFFLINE.value,
                    "device_name": self.device_manager.paired_device.device_name,
                })

    async def _handle_incoming_event(self, action: str, payload: dict[str, Any]) -> None:
        """Processes events originating from the phone companion."""
        # Event 1: Minimal Notification Alert (WhatsApp or SMS)
        if action == "notification":
            source = payload.get("source", "unknown").lower()
            if source == "whatsapp":
                announcement = "Sir, you received a WhatsApp message."
            elif source == "sms":
                announcement = "Sir, you received an SMS message."
            else:
                announcement = f"Sir, you received a notification from {source}."

            logger.info(f"Notification event received: {source} (no message body transferred)")

            # Notify UI
            await self._notify_ui({
                "type": "phone_alert",
                "source": source,
                "text": announcement,
            })
            await self._notify_ui({
                "type": "transcript",
                "role": "assistant",
                "text": announcement,
            })
            await self._notify_ui({
                "type": "speak",
                "text": announcement,
            })

        # Event 2: Incoming Call State Change
        elif action == "incoming_call":
            call_state = self.gateway.handle_incoming_call_event(payload)
            caller = call_state.caller_name
            call_type = call_state.call_type.value

            if call_state.status == CallStatus.RINGING:
                call_announcement = (
                    f"Sir, {caller} is calling on WhatsApp."
                    if call_state.call_type.value == "whatsapp"
                    else f"Sir, {caller} is calling."
                )
                logger.info(f"Incoming call announced: '{call_announcement}'")

                await self._notify_ui({
                    "type": "phone_incoming_call",
                    "caller_name": caller,
                    "caller_number": call_state.caller_number,
                    "call_type": call_type,
                    "status": "RINGING",
                    "call_id": call_state.call_id,
                })
                await self._notify_ui({
                    "type": "transcript",
                    "role": "assistant",
                    "text": call_announcement,
                })
                await self._notify_ui({
                    "type": "speak",
                    "text": call_announcement,
                })
            elif call_state.status in (CallStatus.IDLE, CallStatus.REJECTED, CallStatus.ANSWERED):
                await self._notify_ui({
                    "type": "phone_incoming_call",
                    "status": call_state.status.value,
                    "call_id": call_state.call_id,
                })


# Global singleton instance for Victor application
phone_server = PhoneServer()
