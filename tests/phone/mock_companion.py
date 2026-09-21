"""
Interactive Mock Android Companion for Victor Phone Integration V1.
Allows immediate end-to-end testing of Victor's Phone Integration module directly from PC.
Simulates:
- Cryptographic pairing handshake via 6-digit PIN
- Heartbeat and battery telemetry
- Privacy-safe WhatsApp and SMS notification alerts
- Incoming call alerts (Cellular & WhatsApp) with answer/reject tracking
- Contact resolution (single match & ambiguous matches)
- Outgoing call execution after explicit approval
- YouTube search intent execution
"""

import asyncio
import json
import sys
import time
import uuid
from typing import Optional
import websockets

from app.phone.crypto import PhoneCrypto
from app.phone.models import MessageType, PhoneMessage


class MockCompanion:
    def __init__(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        self.host = host
        self.port = port
        self.ws_url = f"ws://{host}:{port}/ws/phone"
        self.crypto = PhoneCrypto()
        self.device_id = f"mock_phone_{uuid.uuid4().hex[:8]}"
        self.device_name = "Google Pixel 8 Pro (Mock)"
        self.shared_secret: Optional[str] = None
        self.ws = None
        self.is_running = False

        # Mock Contacts Database
        self.contacts = [
            {"name": "Dad", "number": "+919876543210", "type": "Mobile"},
            {"name": "Mom", "number": "+919123456789", "type": "Mobile"},
            {"name": "Rahul Sharma", "number": "+919876500001", "type": "Mobile"},
            {"name": "Rahul Office", "number": "+911122334455", "type": "Work"},
            {"name": "Doctor Clinic", "number": "+911144556677", "type": "Work"},
        ]

    async def connect_and_pair(self, pin: str) -> bool:
        print(f"\n[Mock Companion] Connecting to Victor at {self.ws_url}...")
        try:
            self.ws = await websockets.connect(self.ws_url)
            print("[Mock Companion] WebSocket connected.")
        except Exception as e:
            print(f"[Mock Companion] Connection failed: {e}")
            return False

        # Send pair_request
        pair_req = {
            "type": MessageType.PAIR_REQUEST.value,
            "action": "pair",
            "payload": {
                "token": pin.strip(),
                "device_id": self.device_id,
                "device_name": self.device_name,
            },
        }
        await self.ws.send(json.dumps(pair_req))
        print(f"[Mock Companion] Sent pairing request with PIN '{pin}'...")

        # Await pair_response
        resp_raw = await self.ws.recv()
        resp_json = json.loads(resp_raw)

        if resp_json.get("type") == MessageType.PAIR_RESPONSE.value:
            payload = resp_json.get("payload", {})
            self.shared_secret = payload.get("shared_secret_hex")
            print(f"[Mock Companion] PAIRING SUCCESSFUL! Device paired with Victor.")
            print(f"[Mock Companion] Shared secret established ({len(self.shared_secret)} hex chars).\n")
            return True
        else:
            err = resp_json.get("payload", {}).get("error", "Unknown error")
            print(f"[Mock Companion] Pairing failed: {err}")
            await self.ws.close()
            return False

    async def send_event(self, action: str, payload: dict) -> None:
        if not self.ws or not self.shared_secret:
            print("[Mock Companion] Not connected/paired.")
            return

        msg = PhoneMessage(
            type=MessageType.EVENT,
            action=action,
            payload=payload,
        )
        msg.signature = self.crypto.sign_message(msg, self.shared_secret)
        await self.ws.send(msg.model_dump_json())
        print(f"[Mock Companion] Dispatched event '{action}' -> {payload}")

    async def _heartbeat_loop(self) -> None:
        try:
            while self.is_running and self.ws:
                await asyncio.sleep(10)
                if not self.shared_secret:
                    continue
                hb = PhoneMessage(
                    type=MessageType.HEARTBEAT,
                    action="ping",
                    payload={"battery_level": 88, "is_charging": True},
                )
                hb.signature = self.crypto.sign_message(hb, self.shared_secret)
                await self.ws.send(hb.model_dump_json())
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def _receive_loop(self) -> None:
        try:
            while self.is_running and self.ws:
                raw = await self.ws.recv()
                msg_json = json.loads(raw)
                msg = PhoneMessage.model_validate(msg_json)

                if msg.type == MessageType.HEARTBEAT and msg.action == "heartbeat_ack":
                    continue

                if msg.type == MessageType.COMMAND:
                    await self._handle_command(msg)

        except asyncio.CancelledError:
            pass
        except websockets.exceptions.ConnectionClosed:
            print("\n[Mock Companion] Connection closed by Victor PC.")
        except Exception as e:
            print(f"\n[Mock Companion] Error in receive loop: {e}")

    async def _handle_command(self, msg: PhoneMessage) -> None:
        action = msg.action
        payload = msg.payload
        print(f"\n>>> [Mock Companion Received Command] '{action}' with args: {payload}")

        resp_payload = {"success": True}

        if action == "resolve_contact":
            query = payload.get("query", "").lower()
            matches = [c for c in self.contacts if query in c["name"].lower()]
            resp_payload["matches"] = matches
            print(f"[Mock Companion] Contact lookup found {len(matches)} match(es)")

        elif action == "initiate_call":
            number = payload.get("phone_number")
            print(f"[Mock Companion] >>> DIALING CALL ON PHONE TO: {number} <<<")
            resp_payload["success"] = True

        elif action == "answer_call":
            print("[Mock Companion] >>> ACCEPTED / ANSWERED INCOMING CALL ON PHONE <<<")
            resp_payload["success"] = True

        elif action == "reject_call":
            print("[Mock Companion] >>> DECLINED / REJECTED INCOMING CALL ON PHONE <<<")
            resp_payload["success"] = True

        elif action == "launch_youtube":
            query = payload.get("query", "")
            print(f"[Mock Companion] >>> LAUNCHED YOUTUBE SEARCH FOR: '{query}' <<<")
            resp_payload["success"] = True

        elif action == "get_status":
            resp_payload = {"success": True, "battery_level": 88, "is_charging": True}

        # Send response back to Victor PC
        resp = PhoneMessage(
            id=msg.id,
            type=MessageType.COMMAND_RESPONSE,
            action=action,
            payload=resp_payload,
        )
        resp.signature = self.crypto.sign_message(resp, self.shared_secret)
        await self.ws.send(resp.model_dump_json())
        print(f"[Mock Companion] Sent command response to Victor PC.")

    async def run(self, pin: str) -> None:
        paired = await self.connect_and_pair(pin)
        if not paired:
            return

        self.is_running = True
        recv_task = asyncio.create_task(self._receive_loop())
        hb_task = asyncio.create_task(self._heartbeat_loop())

        print("=" * 60)
        print("MOCK ANDROID COMPANION IS ONLINE & ACTIVE")
        print("Available test triggers:")
        print("  [w] Trigger WhatsApp message notification")
        print("  [s] Trigger SMS message notification")
        print("  [c] Trigger incoming phone call (from 'Dad')")
        print("  [q] Disconnect & Quit")
        print("=" * 60)

        loop = asyncio.get_event_loop()
        try:
            while self.is_running:
                # Read keyboard input non-blockingly
                cmd = await loop.run_in_executor(None, input, "Enter action [w/s/c/q]: ")
                cmd = cmd.strip().lower()

                if cmd == "w":
                    await self.send_event("notification", {"source": "whatsapp"})
                elif cmd == "s":
                    await self.send_event("notification", {"source": "sms"})
                elif cmd == "c":
                    await self.send_event("incoming_call", {
                        "call_id": str(uuid.uuid4()),
                        "caller_name": "Dad",
                        "caller_number": "+919876543210",
                        "call_type": "phone",
                        "status": "RINGING",
                    })
                elif cmd == "q":
                    break
        finally:
            self.is_running = False
            recv_task.cancel()
            hb_task.cancel()
            if self.ws:
                await self.ws.close()
            print("[Mock Companion] Exited.")


if __name__ == "__main__":
    pin_arg = sys.argv[1] if len(sys.argv) > 1 else ""
    if not pin_arg:
        pin_arg = input("Enter the 6-digit Pairing PIN shown on Victor HUD UI: ").strip()

    companion = MockCompanion()
    asyncio.run(companion.run(pin_arg))
