"""
Victor Phone Integration V1 module.
Provides secure Android companion device integration with strict PC command authority.
"""

from app.phone.crypto import PhoneCrypto
from app.phone.device_manager import PhoneDeviceManager
from app.phone.gateway import PhoneGateway
from app.phone.models import (
    CallStatus,
    CallType,
    ContactMatch,
    IncomingCallState,
    MessageType,
    PendingCallApproval,
    PhoneDevice,
    PhoneMessage,
    PhoneStatus,
)
from app.phone.server import PhoneServer, get_local_ip, phone_server
from app.phone.tools import (
    PhoneAnswerCallTool,
    PhoneGetStatusTool,
    PhoneInitiateCallTool,
    PhoneLaunchYouTubeTool,
    PhoneRejectCallTool,
    PhoneResolveContactTool,
    PhoneUnpairTool,
)

__all__ = [
    "PhoneCrypto",
    "PhoneDeviceManager",
    "PhoneGateway",
    "PhoneServer",
    "phone_server",
    "get_local_ip",
    "PhoneStatus",
    "PhoneDevice",
    "PhoneMessage",
    "MessageType",
    "ContactMatch",
    "PendingCallApproval",
    "IncomingCallState",
    "CallType",
    "CallStatus",
    "PhoneGetStatusTool",
    "PhoneResolveContactTool",
    "PhoneInitiateCallTool",
    "PhoneAnswerCallTool",
    "PhoneRejectCallTool",
    "PhoneLaunchYouTubeTool",
    "PhoneUnpairTool",
]
