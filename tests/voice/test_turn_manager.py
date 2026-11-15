"""
Unit tests for Victor VoiceTurnManager and intelligent turn management.
"""

import math
import struct
import pytest
from app.voice.turn_manager import TurnManagerConfig, TurnState, VoiceTurnManager


def make_pcm_chunk(duration_sec: float = 0.128, amplitude: float = 0.5, freq: float = 440.0, sample_rate: int = 16000) -> bytes:
    """Generates synthetic sine-wave 16-bit PCM chunk at 16kHz."""
    num_samples = int(duration_sec * sample_rate)
    samples = []
    for i in range(num_samples):
        t = i / sample_rate
        val = int(amplitude * 32767.0 * math.sin(2.0 * math.pi * freq * t))
        samples.append(val)
    return struct.pack(f"<{num_samples}h", *samples)


def make_silence_chunk(duration_sec: float = 0.128, noise_amp: float = 0.001, sample_rate: int = 16000) -> bytes:
    """Generates synthetic near-silent 16-bit PCM chunk."""
    return make_pcm_chunk(duration_sec=duration_sec, amplitude=noise_amp, freq=100.0, sample_rate=sample_rate)


def test_turn_manager_initialization():
    cfg = TurnManagerConfig(short_pause_sec=1.0, potential_endpoint_sec=2.5)
    mgr = VoiceTurnManager(config=cfg)
    assert mgr.state == TurnState.IDLE_LISTENING
    assert mgr.buffered_duration_sec == 0.0
    assert mgr.speech_duration_sec == 0.0


def test_speech_onset_and_pre_speech_buffering():
    mgr = VoiceTurnManager()

    # Feed 2 ambient chunks
    c_silence = make_silence_chunk()
    mgr.process_audio(c_silence, now=10.0)
    mgr.process_audio(c_silence, now=10.128)
    assert mgr.state == TurnState.IDLE_LISTENING

    # Feed loud speech chunk (440Hz, amp=0.5)
    c_speech = make_pcm_chunk(amplitude=0.6)
    res = mgr.process_audio(c_speech, now=10.256)
    assert res["action"] == "speech_started"
    assert mgr.state == TurnState.SPEECH_ACTIVE
    # Utterance buffer should include the pre-speech chunks + the speech chunk
    assert len(mgr._utterance_buffer) >= len(c_speech) + len(c_silence)


def test_short_pause_continues_listening():
    """Test Case 1 & 2: Natural short pause (0.5 - 1.5s) does NOT stop listening or finalize."""
    mgr = VoiceTurnManager()
    t = 10.0

    # User starts speaking: "Victor, open my browser and..." (1.0s of speech)
    for _ in range(8):
        c_speech = make_pcm_chunk(amplitude=0.6)
        mgr.process_audio(c_speech, now=t)
        t += 0.128

    assert mgr.state == TurnState.SPEECH_ACTIVE
    initial_speech_dur = mgr.speech_duration_sec
    assert initial_speech_dur >= 0.9

    # User pauses for 1.0 second
    for _ in range(7):
        c_silence = make_silence_chunk()
        res = mgr.process_audio(c_silence, now=t)
        t += 0.128
        assert res["action"] in ("buffering_pause", "waiting_continuation")

    # Manager must still be buffering and NOT finalized
    assert mgr.state in (TurnState.SPEECH_ACTIVE, TurnState.WAITING_FOR_CONTINUATION)
    assert mgr.state != TurnState.FINALIZING
    assert mgr.buffered_duration_sec > 1.5


def test_continuation_word_extends_pause():
    """Test Case: Connective word ('and', 'because') extends continuation window."""
    cfg = TurnManagerConfig(potential_endpoint_sec=2.5, continuation_extension_sec=2.0)
    mgr = VoiceTurnManager(config=cfg)
    t = 100.0

    # User speaks: "Victor, open my browser and"
    for _ in range(8):
        c_speech = make_pcm_chunk(amplitude=0.6)
        mgr.process_audio(c_speech, now=t)
        t += 0.128

    mgr.feed_transcript_hint("Victor open my browser and")

    # User pauses for 3.0 seconds (normally >= 2.5s would endpoint, but 'and' extends by 2.0s to 4.5s)
    for _ in range(23):  # ~2.94s of silence
        c_silence = make_silence_chunk()
        res = mgr.process_audio(c_silence, now=t)
        t += 0.128
        assert res["action"] in ("buffering_pause", "waiting_continuation")

    assert mgr.state == TurnState.WAITING_FOR_CONTINUATION

    # User resumes speaking: "Search for the latest AI news."
    for _ in range(8):
        c_speech = make_pcm_chunk(amplitude=0.6)
        res = mgr.process_audio(c_speech, now=t)
        t += 0.128

    # Seamlessly reverted to SPEECH_ACTIVE without dropping prior audio!
    assert mgr.state == TurnState.SPEECH_ACTIVE


def test_endpoint_silence_finalization():
    """Test Case 3: Complete sentence followed by endpoint silence finalizes cleanly."""
    finalized_events = []

    def on_finalized(pcm, hint):
        finalized_events.append((pcm, hint))

    cfg = TurnManagerConfig(normal_pause_sec=1.5, potential_endpoint_sec=2.5)
    mgr = VoiceTurnManager(config=cfg, on_turn_finalized=on_finalized)
    t = 200.0

    # User speaks: "What is the battery level?" (1.2s of speech)
    for _ in range(10):
        c_speech = make_pcm_chunk(amplitude=0.6)
        mgr.process_audio(c_speech, now=t)
        t += 0.128

    mgr.feed_transcript_hint("What is the battery level")

    # Silence for 2.6 seconds (exceeds potential_endpoint_sec=2.5s)
    res = None
    for _ in range(22):
        c_silence = make_silence_chunk()
        res = mgr.process_audio(c_silence, now=t)
        t += 0.128
        if res.get("action") == "turn_finalized":
            break

    assert res is not None
    assert res["action"] == "turn_finalized"
    assert mgr.state == TurnState.DISPATCHED
    assert len(finalized_events) == 1
    assert len(finalized_events[0][0]) > 0
    assert finalized_events[0][1] == "What is the battery level"


def test_explicit_finish_voice_command():
    """Test Case 6: Explicit voice command ('That's all', 'I'm done', 'Victor, process it')."""
    finalized_events = []

    def on_finalized(pcm, hint):
        finalized_events.append((pcm, hint))

    mgr = VoiceTurnManager(on_turn_finalized=on_finalized)
    t = 300.0

    # User speaks: "Book a meeting with Rahul tomorrow at 3pm"
    for _ in range(10):
        c_speech = make_pcm_chunk(amplitude=0.6)
        mgr.process_audio(c_speech, now=t)
        t += 0.128

    # User says finish phrase
    res = mgr.feed_transcript_hint("Book a meeting with Rahul tomorrow at 3pm that's all")
    assert res is not None
    assert res["action"] == "turn_finalized"
    assert res["reason"] == "explicit_voice_command"
    assert res["transcript_hint"] == "Book a meeting with Rahul tomorrow at 3pm"  # finish phrase stripped!
    assert len(finalized_events) == 1
    assert finalized_events[0][1] == "Book a meeting with Rahul tomorrow at 3pm"


def test_discard_short_noise_click():
    """Test Case 5: Background transient noise (< 0.35s) discarded rather than executed."""
    mgr = VoiceTurnManager()
    t = 400.0

    # Single click of 0.128s
    c_click = make_pcm_chunk(amplitude=0.7)
    mgr.process_audio(c_click, now=t)
    t += 0.128
    assert mgr.state == TurnState.SPEECH_ACTIVE

    # Silence follows immediately for 3 seconds
    res = None
    for _ in range(25):
        c_silence = make_silence_chunk()
        res = mgr.process_audio(c_silence, now=t)
        t += 0.128
        if res.get("action") == "discard_noise":
            break

    assert res is not None
    assert res["action"] == "discard_noise"
    # Reset back to IDLE_LISTENING without firing finalized turn!
    assert mgr.state == TurnState.IDLE_LISTENING
    assert len(mgr._utterance_buffer) == 0


def test_timeout_on_isolated_wake_word():
    """Test Case 7: User says 'Victor...' and walks away / never continues."""
    timed_out = []

    def on_timeout(reason):
        timed_out.append(reason)

    cfg = TurnManagerConfig(max_waiting_duration_sec=5.0)
    mgr = VoiceTurnManager(config=cfg, on_turn_timeout=on_timeout)
    t = 500.0

    # User says "Victor"
    for _ in range(4):
        c_speech = make_pcm_chunk(amplitude=0.6)
        mgr.process_audio(c_speech, now=t)
        t += 0.128

    mgr.feed_transcript_hint("Victor")

    # User remains silent for 6 seconds
    res = None
    for _ in range(48):
        c_silence = make_silence_chunk()
        res = mgr.process_audio(c_silence, now=t)
        t += 0.128
        if res.get("action") == "timeout_reset":
            break

    assert res is not None
    assert res["action"] == "timeout_reset"
    assert mgr.state == TurnState.IDLE_LISTENING
    assert len(timed_out) == 1
    assert len(mgr._utterance_buffer) == 0  # Cleaned up without execution!


def test_multiple_consecutive_requests():
    """Test Case 8: Multiple consecutive requests are processed independently without mixing."""
    finalized_requests = []

    def on_finalized(pcm, hint):
        finalized_requests.append(len(pcm))

    cfg = TurnManagerConfig(potential_endpoint_sec=2.0)
    mgr = VoiceTurnManager(config=cfg, on_turn_finalized=on_finalized)
    t = 600.0

    # Turn 1
    for _ in range(6):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128
    for _ in range(18):
        mgr.process_audio(make_silence_chunk(), now=t)
        t += 0.128

    assert len(finalized_requests) == 1

    # Assistant finished turn, rearm turn manager
    mgr.rearm_after_turn_completion()
    assert mgr.state == TurnState.IDLE_LISTENING
    assert len(mgr._utterance_buffer) == 0

    # Turn 2
    for _ in range(8):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128
    for _ in range(18):
        mgr.process_audio(make_silence_chunk(), now=t)
        t += 0.128

    assert len(finalized_requests) == 2


def test_continuous_speech_without_pauses():
    """Test Case 4: A user speaking continuously without pauses."""
    mgr = VoiceTurnManager()
    t = 700.0

    # User speaks continuously for 5 seconds without pausing
    for _ in range(40):
        res = mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128
        assert res["action"] in ("speech_started", "speech_accumulated")
        assert mgr.state == TurnState.SPEECH_ACTIVE

    assert mgr.speech_duration_sec >= 4.8
    # User finishes, followed by 3 seconds of silence -> endpoints
    res = None
    for _ in range(25):
        c_silence = make_silence_chunk()
        res = mgr.process_audio(c_silence, now=t)
        t += 0.128
        if res.get("action") == "turn_finalized":
            break

    assert res is not None
    assert res["action"] == "turn_finalized"
    assert mgr.state == TurnState.DISPATCHED


def test_pause_for_5_to_8_seconds_with_continuation_window():
    """Test Case 6: User pauses for 6 seconds with continuation window and resumes."""
    cfg = TurnManagerConfig(
        potential_endpoint_sec=2.5,
        continuation_extension_sec=4.0,  # e.g. continuation phrase extension up to 6.5s
        max_waiting_duration_sec=10.0,
    )
    mgr = VoiceTurnManager(config=cfg)
    t = 800.0

    # User speaks: "Check tomorrow's calendar and"
    for _ in range(10):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128

    mgr.feed_transcript_hint("Check tomorrow's calendar and")

    # User pauses for 5.5 seconds (within 2.5 + 4.0 = 6.5s window)
    for _ in range(40):
        res = mgr.process_audio(make_silence_chunk(), now=t)
        t += 0.128
        assert res["action"] in ("buffering_pause", "waiting_continuation")

    assert mgr.state == TurnState.WAITING_FOR_CONTINUATION

    # User continues: "summarize the key meetings for me"
    for _ in range(12):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128

    # Reverts to SPEECH_ACTIVE with both clauses preserved in one buffer!
    assert mgr.state == TurnState.SPEECH_ACTIVE
    assert mgr.buffered_duration_sec >= 7.0


def test_long_request_multiple_sentences():
    """Test Case 9: Long request containing multiple sentences preserved in full."""
    finalized = []
    mgr = VoiceTurnManager(on_turn_finalized=lambda pcm, hint: finalized.append(pcm))
    t = 900.0

    # Sentence 1: "I am planning my trip to Mumbai next week." (1.5s)
    for _ in range(12):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128
    # Short pause (1.0s)
    for _ in range(7):
        mgr.process_audio(make_silence_chunk(), now=t)
        t += 0.128

    # Sentence 2: "Look up flights on Friday afternoon." (1.5s)
    for _ in range(12):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128
    # Short pause (1.2s)
    for _ in range(9):
        mgr.process_audio(make_silence_chunk(), now=t)
        t += 0.128

    # Sentence 3: "Also check hotels near Nariman Point." (1.5s)
    for _ in range(12):
        mgr.process_audio(make_pcm_chunk(amplitude=0.6), now=t)
        t += 0.128

    # Silence (3.0s) -> Endpoint
    for _ in range(25):
        res = mgr.process_audio(make_silence_chunk(), now=t)
        t += 0.128
        if res.get("action") == "turn_finalized":
            break

    assert len(finalized) == 1
    # Total duration of all 3 sentences + pauses is in the single buffer
    assert len(finalized[0]) >= int(16000 * 2 * 6.0)

