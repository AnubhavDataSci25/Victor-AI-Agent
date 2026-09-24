"""
Unit tests for PhoneGateway: authorization chokepoint, 2FA gating,
contact ambiguity resolution, outgoing call approval workflow,
and incoming call handling.
"""

from pathlib import Path
import time
import pytest
from app.phone.device_manager import PhoneDeviceManager
from app.phone.gateway import PhoneGateway
from app.phone.models import (
    CallStatus,
    CallType,
    IncomingCallState,
    PendingCallApproval,
    PhoneMessage,
    PhoneStatus,
)


class MockSessionManager:
    def __init__(self, authenticated: bool = True):
        self._authenticated = authenticated

    def is_authenticated(self) -> bool:
        return self._authenticated


@pytest.fixture
def setup_gateway(tmp_path: Path):
    store_file = tmp_path / "paired_phone.json"
    mgr = PhoneDeviceManager(store_path=store_file)
    _, pin, _ = mgr.initiate_pairing()
    mgr.complete_pairing(pin, "device_test_123", "Test Phone")

    session = MockSessionManager(authenticated=True)
    gateway = PhoneGateway(device_manager=mgr, session_manager=session)
    return gateway, mgr, session


@pytest.mark.asyncio
async def test_gateway_blocks_when_unauthenticated(setup_gateway):
    gateway, mgr, session = setup_gateway
    session._authenticated = False

    res = await gateway.resolve_contact("Dad")
    assert res["success"] is False
    assert "Access Denied" in res["message"]

    res_call = await gateway.initiate_call("Dad", "+919876543210")
    assert res_call["success"] is False
    assert "Access Denied" in res_call["message"]


@pytest.mark.asyncio
async def test_gateway_blocks_when_device_offline(setup_gateway):
    gateway, mgr, _ = setup_gateway
    mgr.paired_device.last_seen = time.time() - 60.0  # simulate offline

    res = await gateway.resolve_contact("Dad")
    assert res["success"] is False
    assert "offline" in res["message"].lower()


@pytest.mark.asyncio
async def test_contact_resolution_zero_matches(setup_gateway):
    gateway, _, _ = setup_gateway

    async def mock_dispatcher(msg: PhoneMessage):
        return {"success": True, "matches": []}

    gateway.set_command_dispatcher(mock_dispatcher)

    res = await gateway.resolve_contact("Unknown Person")
    assert res["success"] is False
    assert res["matches_count"] == 0
    assert "could not find any contact" in res["message"]


@pytest.mark.asyncio
async def test_contact_resolution_multiple_matches_ambiguity(setup_gateway):
    gateway, _, _ = setup_gateway

    async def mock_dispatcher(msg: PhoneMessage):
        return {
            "success": True,
            "matches": [
                {"name": "Rahul Sharma", "number": "+919876543210", "type": "Mobile"},
                {"name": "Rahul Office", "number": "+911122334455", "type": "Work"},
            ],
        }

    gateway.set_command_dispatcher(mock_dispatcher)

    res = await gateway.resolve_contact("Rahul")
    assert res["success"] is True
    assert res["ambiguous"] is True
    assert res["matches_count"] == 2
    assert "multiple contacts matching" in res["message"]
    # Approval must NOT be staged when ambiguous
    assert gateway.pending_call_approval is None


@pytest.mark.asyncio
async def test_contact_resolution_single_match_stages_approval(setup_gateway):
    gateway, _, _ = setup_gateway

    async def mock_dispatcher(msg: PhoneMessage):
        return {
            "success": True,
            "matches": [
                {"name": "Mom", "number": "+91 98765 43210", "type": "Mobile"}
            ],
        }

    gateway.set_command_dispatcher(mock_dispatcher)

    res = await gateway.resolve_contact("Mom")
    assert res["success"] is True
    assert res["ambiguous"] is False
    assert res["contact_name"] == "Mom"
    assert res["phone_number"] == "+919876543210"
    assert "Do you want me to call this number?" in res["message"]

    # Pending approval must be actively staged
    assert gateway.pending_call_approval is not None
    assert gateway.pending_call_approval.contact_name == "Mom"
    assert gateway.pending_call_approval.phone_number == "+919876543210"


@pytest.mark.asyncio
async def test_initiate_call_approval_enforcement(setup_gateway):
    gateway, _, _ = setup_gateway

    dispatched_calls = []

    async def mock_dispatcher(msg: PhoneMessage):
        dispatched_calls.append(msg.payload)
        return {"success": True}

    gateway.set_command_dispatcher(mock_dispatcher)

    # 1. Calling without approval is denied
    res_no_approval = await gateway.initiate_call("Dad", "+919876543210")
    assert res_no_approval["success"] is False
    assert "Authorization Denied" in res_no_approval["message"]
    assert len(dispatched_calls) == 0

    # 2. Stage approval for Mom (+919876543210)
    gateway.pending_call_approval = PendingCallApproval(
        contact_name="Mom",
        phone_number="+919876543210",
    )

    # 3. Calling a mismatched number is denied
    res_mismatch = await gateway.initiate_call("Mom", "+910000000000")
    assert res_mismatch["success"] is False
    assert "Mismatch" in res_mismatch["message"]
    assert len(dispatched_calls) == 0

    # 4. Calling matching approved number succeeds
    res_success = await gateway.initiate_call("Mom", "+919876543210")
    assert res_success["success"] is True
    assert "calling Mom at +919876543210" in res_success["message"]
    assert len(dispatched_calls) == 1
    assert dispatched_calls[0]["phone_number"] == "+919876543210"

    # 5. Approval is consumed immediately (preventing replay attack)
    assert gateway.pending_call_approval is None
    res_replay = await gateway.initiate_call("Mom", "+919876543210")
    assert res_replay["success"] is False


@pytest.mark.asyncio
async def test_incoming_call_answer_and_reject(setup_gateway):
    gateway, _, _ = setup_gateway

    dispatched = []

    async def mock_dispatcher(msg: PhoneMessage):
        dispatched.append(msg.action)
        return {"success": True}

    gateway.set_command_dispatcher(mock_dispatcher)

    # 1. Answering when no call is active fails
    assert (await gateway.answer_call())["success"] is False
    assert (await gateway.reject_call())["success"] is False

    # 2. Incoming WhatsApp call detection
    gateway.handle_incoming_call_event({
        "call_id": "c1",
        "caller_name": "Boss",
        "call_type": "whatsapp",
        "status": "RINGING",
    })

    # WhatsApp calls must decline programmatic answer per user requirements (no accessibility hacks)
    res_wa = await gateway.answer_call()
    assert res_wa["success"] is False
    assert "WhatsApp incoming calls cannot be answered programmatically" in res_wa["message"]

    # 3. Incoming cellular phone call
    gateway.handle_incoming_call_event({
        "call_id": "c2",
        "caller_name": "Friend",
        "call_type": "phone",
        "status": "RINGING",
    })

    # Answering cellular phone call succeeds
    res_phone = await gateway.answer_call()
    assert res_phone["success"] is True
    assert "answered the call from Friend" in res_phone["message"]
    assert "answer_call" in dispatched


@pytest.mark.asyncio
async def test_launch_youtube(setup_gateway):
    gateway, _, _ = setup_gateway

    dispatched = []

    async def mock_dispatcher(msg: PhoneMessage):
        dispatched.append(msg.payload)
        return {"success": True}

    gateway.set_command_dispatcher(mock_dispatcher)

    res = await gateway.launch_youtube("Python tutorials")
    assert res["success"] is True
    assert "Python tutorials" in res["message"]
    assert dispatched[0]["query"] == "Python tutorials"


@pytest.mark.asyncio
async def test_phone_number_matching_with_country_code_and_formatting(setup_gateway):
    """Test that numbers with +91, local 0, spaces, and 10 digits match seamlessly."""
    gateway, _, _ = setup_gateway
    dispatched = []

    async def mock_dispatcher(msg: PhoneMessage):
        dispatched.append(msg.payload)
        return {"success": True}

    gateway.set_command_dispatcher(mock_dispatcher)

    # 1. Staged with local 10 digits, called with +91 country code
    gateway.pending_call_approval = PendingCallApproval(
        contact_name="Govinda",
        phone_number="9876543210",
    )
    res1 = await gateway.initiate_call("Govinda", "+91 98765 43210")
    assert res1["success"] is True
    assert len(dispatched) == 1
    assert dispatched[-1]["phone_number"] == "+919876543210"

    # 2. Staged with +91, called with trunk 0
    gateway.pending_call_approval = PendingCallApproval(
        contact_name="Govinda",
        phone_number="+919876543210",
    )
    res2 = await gateway.initiate_call("Govinda", "09876543210")
    assert res2["success"] is True
    assert len(dispatched) == 2


@pytest.mark.asyncio
async def test_multi_match_candidates_allow_approval_on_initiate_call(setup_gateway):
    """Test that contacts resolved from multi-match queries can be initiated directly."""
    gateway, _, _ = setup_gateway
    dispatched = []

    async def mock_dispatcher(msg: PhoneMessage):
        if msg.action == "resolve_contact":
            return {
                "success": True,
                "matches": [
                    {"name": "Govinda MCA DS", "number": "+919876543210", "type": "Mobile"},
                    {"name": "Govinda Office", "number": "+911122334455", "type": "Work"},
                ],
            }
        elif msg.action in ("initiate_call", "make_call"):
            dispatched.append(msg.payload)
            return {"success": True}
        return {"success": False}

    gateway.set_command_dispatcher(mock_dispatcher)

    # Resolve contacts (returns 2 matches, sets candidate_matches)
    res_res = await gateway.resolve_contact("Govinda")
    assert res_res["success"] is True
    assert res_res["ambiguous"] is True
    assert len(gateway.candidate_matches) == 2

    # Now initiate call directly with the chosen candidate contact name & number
    res_call = await gateway.initiate_call("Govinda MCA DS", "9876543210")
    assert res_call["success"] is True
    assert len(dispatched) == 1
    assert dispatched[0]["phone_number"] == "9876543210"
    # Candidates and pending approval are cleaned up upon successful dispatch
    assert len(gateway.candidate_matches) == 0
    assert gateway.pending_call_approval is None

