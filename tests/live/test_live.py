"""
Unit tests for LiveSessionManager and Gemini Live calls.
"""

from unittest.mock import AsyncMock, MagicMock
import pytest
from google.genai import types

from app.live.session import LiveSessionManager
from app.live.tool_calls import LiveToolDispatcher
from app.agent.state import VictorState


@pytest.mark.asyncio
async def test_live_session_send_audio():
    mock_session_manager = MagicMock()
    mock_session_manager.websocket_send_callback = AsyncMock()

    manager = LiveSessionManager(mock_session_manager)
    manager.is_connected = True
    manager.session = MagicMock()
    manager.session.send_realtime_input = AsyncMock()

    test_pcm = b"\x00\x01\x02\x03" * 100
    await manager.send_audio(test_pcm)

    manager.session.send_realtime_input.assert_awaited_once()
    call_kwargs = manager.session.send_realtime_input.await_args.kwargs
    assert "audio" in call_kwargs
    assert isinstance(call_kwargs["audio"], types.Blob)
    assert call_kwargs["audio"].data == test_pcm
    assert call_kwargs["audio"].mime_type == "audio/pcm;rate=16000"


@pytest.mark.asyncio
async def test_live_session_receive_tool_call_and_send_response():
    mock_session_manager = MagicMock()
    mock_session_manager.state = VictorState.ACTIVE
    mock_session_manager.set_state = AsyncMock()
    mock_session_manager.websocket_send_callback = AsyncMock()

    manager = LiveSessionManager(mock_session_manager)
    manager.is_connected = True
    manager.session = MagicMock()
    manager.session.send_tool_response = AsyncMock()

    # Create a simulated Tool Call response from Gemini
    fc = MagicMock()
    fc.name = "system_get_time"
    fc.args = {}
    fc.id = "call-123"

    tool_call = MagicMock()
    tool_call.function_calls = [fc]

    mock_resp = MagicMock()
    mock_resp.server_content = None
    mock_resp.tool_call = tool_call

    # Mock the receive generator yielding one tool call response then finishing
    async def mock_receive_gen():
        yield mock_resp
        manager.is_connected = False

    manager.session.receive = mock_receive_gen

    # Run receive loop for that one item
    await manager._receive_loop()

    # Verify send_tool_response was called with keyword argument 'function_responses'
    manager.session.send_tool_response.assert_awaited_once()
    kwargs = manager.session.send_tool_response.await_args.kwargs
    assert "function_responses" in kwargs
    f_resps = kwargs["function_responses"]
    assert len(f_resps) == 1
    assert f_resps[0].name == "system_get_time"
    assert f_resps[0].id == "call-123"
    assert f_resps[0].response["status"] == "success"


@pytest.mark.asyncio
async def test_live_session_interruption():
    mock_session_manager = MagicMock()
    mock_session_manager.state = VictorState.ACTIVE
    mock_session_manager.set_state = AsyncMock()
    mock_session_manager.websocket_send_callback = AsyncMock()

    manager = LiveSessionManager(mock_session_manager)
    manager.is_connected = True
    manager.session = MagicMock()

    # Simulate an interrupted server content event
    server_content = MagicMock()
    server_content.interrupted = True
    server_content.model_turn = None
    server_content.turn_complete = False

    mock_resp = MagicMock()
    mock_resp.server_content = server_content
    mock_resp.tool_call = None

    async def mock_receive_gen():
        yield mock_resp
        manager.is_connected = False

    manager.session.receive = mock_receive_gen
    await manager._receive_loop()

    # Verify interruption was dispatched to browser WebSocket
    calls = [call.args[0] for call in mock_session_manager.websocket_send_callback.await_args_list]
    types_sent = [c.get("type") for c in calls]
    assert "audio_interrupted" in types_sent


@pytest.mark.asyncio
async def test_live_session_multi_turn_continuity():
    """Verify that multiple turns complete without prematurely disconnecting the session."""
    import asyncio

    mock_session_manager = MagicMock()
    mock_session_manager.state = VictorState.ACTIVE
    mock_session_manager.set_state = AsyncMock()
    mock_session_manager.websocket_send_callback = AsyncMock()

    manager = LiveSessionManager(mock_session_manager)
    manager.is_connected = True
    manager.session = MagicMock()

    # Turn 1: model speaks then turn_complete
    part1 = MagicMock()
    part1.inline_data.data = b"\x01\x02\x03\x04"
    turn1_speak = MagicMock()
    turn1_speak.server_content.interrupted = False
    turn1_speak.server_content.model_turn.parts = [part1]
    turn1_speak.server_content.turn_complete = False
    turn1_speak.tool_call = None

    turn1_end = MagicMock()
    turn1_end.server_content.interrupted = False
    turn1_end.server_content.model_turn = None
    turn1_end.server_content.turn_complete = True
    turn1_end.tool_call = None

    # Turn 2: model speaks then turn_complete
    turn2_speak = MagicMock()
    turn2_speak.server_content.interrupted = False
    turn2_speak.server_content.model_turn.parts = [part1]
    turn2_speak.server_content.turn_complete = False
    turn2_speak.tool_call = None

    turn2_end = MagicMock()
    turn2_end.server_content.interrupted = False
    turn2_end.server_content.model_turn = None
    turn2_end.server_content.turn_complete = True
    turn2_end.tool_call = None

    turns = [
        [turn1_speak, turn1_end],
        [turn2_speak, turn2_end],
    ]
    turn_idx = 0

    async def mock_receive_gen():
        nonlocal turn_idx
        if turn_idx < len(turns):
            curr_turn = turns[turn_idx]
            turn_idx += 1
            for msg in curr_turn:
                yield msg
        else:
            # Done with test turns, signal disconnect
            manager.is_connected = False
            await asyncio.sleep(0.01)

    manager.session.receive = mock_receive_gen

    # Run the receive loop
    await manager._receive_loop()

    # Verify both turns were processed
    assert turn_idx == 2
    # Verify websocket callbacks: 2 LISTENING states (one after each turn_complete)
    calls = [call.args[0] for call in mock_session_manager.websocket_send_callback.await_args_list]
    orb_states = [c.get("state") for c in calls if c.get("type") == "orb_state"]
    assert orb_states.count("LISTENING") == 2

