"""
Pydantic models for Victor Phone Integration V1.
Data structures for device pairing, protocol envelopes, contact resolution,
approval workflows, and incoming/outgoing call states.
"""

from __future__ import annotations

from enum import Enum
import time
from typing import Any, Optional
import uuid
from pydantic import BaseModel, Field


class PhoneStatus(str, Enum):
    UNPAIRED = "UNPAIRED"
    PAIRING = "PAIRING"
    OFFLINE = "OFFLINE"
    ONLINE = "ONLINE"


class CallType(str, Enum):
    PHONE = "phone"
    WHATSAPP = "whatsapp"


class CallStatus(str, Enum):
    IDLE = "IDLE"
    RINGING = "RINGING"
    ANSWERED = "ANSWERED"
    REJECTED = "REJECTED"


class MessageType(str, Enum):
    PAIR_REQUEST = "pair_request"
    PAIR_RESPONSE = "pair_response"
    HEARTBEAT = "heartbeat"
    COMMAND = "command"
    COMMAND_RESPONSE = "command_response"
    EVENT = "event"
    ERROR = "error"


class PhoneDevice(BaseModel):
    device_id: str
    device_name: str
    paired_at: float = Field(default_factory=time.time)
    shared_secret_hex: str
    last_seen: float = Field(default_factory=time.time)
    status: PhoneStatus = PhoneStatus.OFFLINE
    battery_level: Optional[int] = None
    is_charging: Optional[bool] = None


class PhoneMessage(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    nonce: str = Field(default_factory=lambda: uuid.uuid4().hex)
    type: MessageType
    action: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    signature: str = ""


class ContactMatch(BaseModel):
    name: str
    number: str
    type: str = "Mobile"


class PendingCallApproval(BaseModel):
    token: str = Field(default_factory=lambda: uuid.uuid4().hex)
    contact_name: str
    phone_number: str
    created_at: float = Field(default_factory=time.time)
    expires_at: float = Field(default_factory=lambda: time.time() + 60.0)

    def is_expired(self) -> bool:
        return time.time() > self.expires_at


class IncomingCallState(BaseModel):
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    caller_name: str = "Unknown Caller"
    caller_number: str = ""
    call_type: CallType = CallType.PHONE
    status: CallStatus = CallStatus.IDLE
    received_at: float = Field(default_factory=time.time)

    def is_active(self) -> bool:
        return self.status == CallStatus.RINGING and (time.time() - self.received_at < 45.0)
