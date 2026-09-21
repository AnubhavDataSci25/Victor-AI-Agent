"""
Phone Tool Gateway & Authorization Layer for Victor Phone Integration V1.
Deterministic safety chokepoint:
- Enforces 2FA session authentication (PIN + Biometric).
- Enforces strict capability allowlist.
- Enforces outgoing call contact ambiguity resolution and explicit user approval state machine.
- Enforces incoming call verification and legitimate Android Telecom handling (blocking unsafe WhatsApp workarounds).
- Dispatches signed, encrypted, replay-protected commands to the phone companion.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Callable, Optional

from app.logging import get_logger
from app.phone.crypto import PhoneCrypto
from app.phone.device_manager import PhoneDeviceManager
from app.phone.models import (
    CallStatus,
    CallType,
    ContactMatch,
    IncomingCallState,
    MessageType,
    PendingCallApproval,
    PhoneMessage,
    PhoneStatus,
)

logger = get_logger("phone.gateway")

ALLOWED_ACTIONS = {
    "resolve_contact",
    "initiate_call",
    "answer_call",
    "reject_call",
    "launch_youtube",
    "get_status",
}


def _sanitize_phone_number(number: str) -> str:
    """Removes non-digit characters except leading plus."""
    if not number:
        return ""
    number = number.strip()
    has_plus = number.startswith("+")
    digits = re.sub(r"\D", "", number)
    return f"+{digits}" if has_plus else digits


class PhoneGateway:
    def __init__(
        self,
        device_manager: Optional[PhoneDeviceManager] = None,
        crypto: Optional[PhoneCrypto] = None,
        session_manager: Optional[Any] = None,
    ) -> None:
        self.device_manager = device_manager or PhoneDeviceManager()
        self.crypto = crypto or self.device_manager.crypto
        self.session_manager = session_manager
        self.pending_call_approval: Optional[PendingCallApproval] = None
        self.current_incoming_call: Optional[IncomingCallState] = None
        self._command_dispatcher: Optional[Callable[[PhoneMessage], Any]] = None

    def set_command_dispatcher(self, dispatcher: Callable[[PhoneMessage], Any]) -> None:
        """Sets the low-level async dispatch function provided by PhoneServer."""
        self._command_dispatcher = dispatcher

    def set_session_manager(self, session_manager: Any) -> None:
        self.session_manager = session_manager

    def _verify_session_auth(self) -> tuple[bool, str]:
        """Verifies that Victor PC session is fully authenticated with 2FA."""
        if not self.session_manager:
            return False, "Access Denied: Session manager not initialized."

        if hasattr(self.session_manager, "is_authenticated") and not self.session_manager.is_authenticated():
            return False, "Access Denied: Victor session is not authenticated with PIN and biometric verification."

        return True, ""

    def _verify_device_ready(self) -> tuple[bool, str]:
        """Verifies that phone device is paired and online."""
        status = self.device_manager.check_liveness()
        if status == PhoneStatus.UNPAIRED:
            return False, "No phone is paired with Victor. Please pair your Android phone through Victor UI."
        if status == PhoneStatus.OFFLINE:
            device_name = self.device_manager.paired_device.device_name if self.device_manager.paired_device else "Phone"
            return False, f"Paired phone '{device_name}' is currently offline. Please ensure the Victor Companion app is running."
        return True, ""

    async def _send_phone_command(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Encapsulates, signs, and sends an allowed command to the companion phone."""
        if action not in ALLOWED_ACTIONS:
            return {"success": False, "error": f"Action '{action}' is not in the phone capability allowlist."}

        device = self.device_manager.paired_device
        if not device:
            return {"success": False, "error": "No paired device."}

        msg = PhoneMessage(
            type=MessageType.COMMAND,
            action=action,
            payload=payload,
        )
        msg.signature = self.crypto.sign_message(msg, device.shared_secret_hex)

        if not self._command_dispatcher:
            return {"success": False, "error": "Phone communication channel is not connected."}

        try:
            res = await self._command_dispatcher(msg)
            return res
        except Exception as e:
            logger.error(f"Error dispatching phone command '{action}': {e}")
            return {"success": False, "error": f"Failed to communicate with phone: {e}"}

    # =========================================================================
    # Capability 1: Outgoing Calls (Contact Resolution & Explicit Approval)
    # =========================================================================

    async def resolve_contact(self, contact_name: str) -> dict[str, Any]:
        """
        Resolves a contact name from the phone.
        Handles zero, single, or multiple contact matches.
        """
        auth_ok, auth_err = self._verify_session_auth()
        if not auth_ok:
            return {"success": False, "message": auth_err}

        dev_ok, dev_err = self._verify_device_ready()
        if not dev_ok:
            return {"success": False, "message": dev_err}

        name_query = (contact_name or "").strip()
        if not name_query:
            return {"success": False, "message": "Please specify a contact name to call."}

        # Clear any stale pending call approval
        self.pending_call_approval = None

        logger.info(f"Querying phone contacts for query: '{name_query}'")
        res = await self._send_phone_command("resolve_contact", {"query": name_query})

        if not res.get("success"):
            return {"success": False, "message": res.get("error", "Failed to resolve contact from phone.")}

        raw_matches = res.get("matches", [])
        if not raw_matches:
            return {
                "success": False,
                "matches_count": 0,
                "message": f"Sir, I could not find any contact named '{name_query}' on your phone.",
            }

        matches = [ContactMatch.model_validate(m) for m in raw_matches]

        if len(matches) > 1:
            summary = "\n".join([f"- {m.name} ({m.type}): {m.number}" for m in matches])
            return {
                "success": True,
                "ambiguous": True,
                "matches_count": len(matches),
                "matches": [m.model_dump() for m in matches],
                "message": (
                    f"Sir, I found multiple contacts matching '{name_query}':\n{summary}\n"
                    "Which number would you like me to call?"
                ),
            }

        # Exactly 1 match found -> stage pending call approval
        match = matches[0]
        sanitized = _sanitize_phone_number(match.number)
        self.pending_call_approval = PendingCallApproval(
            contact_name=match.name,
            phone_number=sanitized,
        )

        return {
            "success": True,
            "ambiguous": False,
            "contact_name": match.name,
            "phone_number": sanitized,
            "approval_token": self.pending_call_approval.token,
            "message": (
                f"Sir, I found {match.name} at {sanitized}. Do you want me to call this number? "
                "(Please confirm with 'yes', 'call', or 'proceed')."
            ),
        }

    async def initiate_call(self, contact_name: str, phone_number: str) -> dict[str, Any]:
        """
        Initiates an outgoing call to the specified contact.
        STRICT REQUIREMENT: Requires an active, matching PendingCallApproval.
        Calls without explicit prior user approval are deterministically rejected.
        """
        auth_ok, auth_err = self._verify_session_auth()
        if not auth_ok:
            return {"success": False, "message": auth_err}

        dev_ok, dev_err = self._verify_device_ready()
        if not dev_ok:
            return {"success": False, "message": dev_err}

        if not self.pending_call_approval:
            return {
                "success": False,
                "message": (
                    "Authorization Denied: No approved call request found. "
                    "Victor must first resolve the contact and obtain your explicit confirmation before calling."
                ),
            }

        if self.pending_call_approval.is_expired():
            self.pending_call_approval = None
            return {
                "success": False,
                "message": "Authorization Expired: The call approval has timed out. Please request the call again.",
            }

        sanitized_req = _sanitize_phone_number(phone_number)
        sanitized_approved = _sanitize_phone_number(self.pending_call_approval.phone_number)

        # Numbers must match (ignoring formatting/spaces)
        if sanitized_req and sanitized_approved and sanitized_req != sanitized_approved:
            return {
                "success": False,
                "message": f"Authorization Mismatch: Approved number was {sanitized_approved}, but requested {sanitized_req}.",
            }

        target_number = sanitized_approved
        target_name = self.pending_call_approval.contact_name

        # Consume the approval immediately to prevent replay
        self.pending_call_approval = None

        logger.info(f"Initiating approved phone call to {target_name} at {target_number}")
        res = await self._send_phone_command("initiate_call", {"phone_number": target_number})

        if res.get("success"):
            return {
                "success": True,
                "contact_name": target_name,
                "phone_number": target_number,
                "message": f"Sir, calling {target_name} at {target_number}. Please speak directly through your phone.",
            }
        else:
            return {
                "success": False,
                "message": res.get("error", "Phone failed to initiate the call."),
            }

    # =========================================================================
    # Capability 2: Incoming Call Detection, Answering & Rejection
    # =========================================================================

    def handle_incoming_call_event(self, event_data: dict[str, Any]) -> IncomingCallState:
        """Called by PhoneServer when phone reports an incoming call state change."""
        state = IncomingCallState(
            call_id=event_data.get("call_id", ""),
            caller_name=event_data.get("caller_name", "Unknown Caller"),
            caller_number=event_data.get("caller_number", ""),
            call_type=CallType(event_data.get("call_type", "phone")),
            status=CallStatus(event_data.get("status", "RINGING")),
            received_at=time.time(),
        )
        self.current_incoming_call = state
        logger.info(f"Incoming call state updated: {state.caller_name} ({state.call_type.value}, status: {state.status.value})")
        return state

    async def answer_call(self) -> dict[str, Any]:
        """Answers an actively ringing incoming call after user command."""
        auth_ok, auth_err = self._verify_session_auth()
        if not auth_ok:
            return {"success": False, "message": auth_err}

        dev_ok, dev_err = self._verify_device_ready()
        if not dev_ok:
            return {"success": False, "message": dev_err}

        if not self.current_incoming_call or not self.current_incoming_call.is_active():
            return {"success": False, "message": "Sir, there is no active incoming call to answer."}

        # WhatsApp call safeguard: refuse programmatic answer if unsupported without hacks
        if self.current_incoming_call.call_type == CallType.WHATSAPP:
            return {
                "success": False,
                "message": (
                    "Sir, WhatsApp incoming calls cannot be answered programmatically via standard Android Telecom APIs "
                    "without accessibility workarounds. Please accept the call directly on your phone."
                ),
            }

        caller = self.current_incoming_call.caller_name
        call_id = self.current_incoming_call.call_id

        res = await self._send_phone_command("answer_call", {"call_id": call_id})
        if res.get("success"):
            self.current_incoming_call.status = CallStatus.ANSWERED
            return {"success": True, "message": f"Sir, answered the call from {caller}."}
        else:
            return {"success": False, "message": res.get("error", "Failed to answer call on phone.")}

    async def reject_call(self) -> dict[str, Any]:
        """Rejects or dismisses an active incoming call after user command."""
        auth_ok, auth_err = self._verify_session_auth()
        if not auth_ok:
            return {"success": False, "message": auth_err}

        dev_ok, dev_err = self._verify_device_ready()
        if not dev_ok:
            return {"success": False, "message": dev_err}

        if not self.current_incoming_call or not self.current_incoming_call.is_active():
            return {"success": False, "message": "Sir, there is no active incoming call to reject."}

        caller = self.current_incoming_call.caller_name
        call_id = self.current_incoming_call.call_id

        res = await self._send_phone_command("reject_call", {"call_id": call_id})
        if res.get("success"):
            self.current_incoming_call.status = CallStatus.REJECTED
            return {"success": True, "message": f"Sir, rejected the incoming call from {caller}."}
        else:
            return {"success": False, "message": res.get("error", "Failed to reject call on phone.")}

    # =========================================================================
    # Capability 3: YouTube Search & Launch
    # =========================================================================

    async def launch_youtube(self, query: str = "") -> dict[str, Any]:
        """Opens YouTube on the companion phone, optionally searching for a query."""
        auth_ok, auth_err = self._verify_session_auth()
        if not auth_ok:
            return {"success": False, "message": auth_err}

        dev_ok, dev_err = self._verify_device_ready()
        if not dev_ok:
            return {"success": False, "message": dev_err}

        clean_query = (query or "").strip()
        res = await self._send_phone_command("launch_youtube", {"query": clean_query})

        if res.get("success"):
            if clean_query:
                return {"success": True, "message": f"Sir, opened YouTube and searched for '{clean_query}' on your phone."}
            else:
                return {"success": True, "message": "Sir, opened YouTube on your phone."}
        else:
            return {"success": False, "message": res.get("error", "Failed to launch YouTube on phone.")}

    # =========================================================================
    # Device Management Commands
    # =========================================================================

    def get_status(self) -> dict[str, Any]:
        """Returns non-sensitive status summary of the paired phone."""
        return self.device_manager.get_status_summary()

    def unpair(self) -> dict[str, Any]:
        """Unpairs and revokes the companion phone immediately."""
        unpaired = self.device_manager.unpair_device()
        self.pending_call_approval = None
        self.current_incoming_call = None
        if unpaired:
            return {"success": True, "message": "Phone has been successfully unpaired and revoked, Sir."}
        else:
            return {"success": False, "message": "No phone was paired with Victor."}
