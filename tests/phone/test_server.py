"""
Unit tests for PhoneServer: notification event handling, incoming call alerts,
and WebSocket dispatching.
"""

import pytest
from app.phone.models import CallStatus
from app.phone.server import PhoneServer


@pytest.mark.asyncio
async def test_notification_alert_zero_leakage_forwarding():
    server = PhoneServer()
    ui_messages = []

    server.set_ui_notify_callback(lambda data: ui_messages.append(data))

    # WhatsApp notification event (without message body)
    await server._handle_incoming_event("notification", {"source": "whatsapp"})

    assert len(ui_messages) == 3
    alert_msg = ui_messages[0]
    assert alert_msg["type"] == "phone_alert"
    assert alert_msg["source"] == "whatsapp"
    assert "Sir, you received a WhatsApp message" in alert_msg["text"]

    # SMS notification event (without message body)
    ui_messages.clear()
    await server._handle_incoming_event("notification", {"source": "sms"})

    assert len(ui_messages) == 3
    assert ui_messages[0]["source"] == "sms"
    assert "Sir, you received an SMS message" in ui_messages[0]["text"]


@pytest.mark.asyncio
async def test_incoming_call_event_forwarding():
    server = PhoneServer()
    ui_messages = []

    server.set_ui_notify_callback(lambda data: ui_messages.append(data))

    await server._handle_incoming_event("incoming_call", {
        "call_id": "call_99",
        "caller_name": "Dr. Sharma",
        "caller_number": "+919876543210",
        "call_type": "phone",
        "status": "RINGING",
    })

    assert len(ui_messages) == 3
    call_msg = ui_messages[0]
    assert call_msg["type"] == "phone_incoming_call"
    assert call_msg["caller_name"] == "Dr. Sharma"
    assert call_msg["status"] == "RINGING"

    speech_msg = ui_messages[2]
    assert "Sir, Dr. Sharma is calling." in speech_msg["text"]
