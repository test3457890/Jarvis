"""Manual capture uses real sample buffers and a fake local transcription model."""
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from jarvis import config, voice
from jarvis.__main__ import App


@pytest.fixture
def capture(monkeypatch):
    monkeypatch.setattr(voice, "load_whisper", lambda cfg: SimpleNamespace(
        transcribe=lambda *a, **kw: ([SimpleNamespace(text="delete a file", no_speech_prob=0)], None)))
    events, commands = [], []
    listener = voice.Listener(dict(config.DEFAULTS), None, lambda *a: commands.append(a),
                              lambda kind, data: events.append((kind, data)))
    yield listener, events, commands
    listener.cancel_manual()


def wait_preview(events):
    # Use the real worker and a bounded wait, without any microphone or model downloads.
    import time
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        if events and events[-1][1].get("state") == "preview":
            return events[-1][1]
        time.sleep(.005)
    raise AssertionError("No transcript preview arrived")


def test_manual_capture_only_previews_and_never_calls_command(capture):
    listener, events, commands = capture
    listener.cfg["voice_input_mode"] = "manual"
    listener._receive(np.ones((16000, 1), dtype="float32"))
    assert listener._audio.empty()
    recording = listener.begin_manual()
    listener._receive(np.ones((16000, 1), dtype="float32"))
    listener.finish_manual(recording["id"])
    assert wait_preview(events)["text"] == "delete a file"
    assert not commands and not listener.room and listener._audio.empty()


def test_capture_bounds_and_pause_release_all_buffers(capture):
    listener, events, _ = capture
    listener.begin_manual()
    with pytest.raises(ValueError, match="already active"):
        listener.begin_manual()
    listener._receive(np.ones((voice.RATE * 30, 1), dtype="float32"))
    active = listener._manual
    assert active["samples"] == voice.RATE * 25
    listener.pause()
    assert listener._manual is None and not active["blocks"]
    assert events[-1][1]["state"] == "cancelled"
    listener._receive(np.ones((16000, 1)))
    assert listener._audio.empty()
    with pytest.raises(ValueError, match="Resume Mic"):
        listener.begin_manual()


def test_cancel_during_transcription_prevents_late_preview(capture):
    listener, events, commands = capture
    started, release, finished = threading.Event(), threading.Event(), threading.Event()

    def transcribe(*args, **kwargs):
        started.set()
        assert release.wait(3)
        return [SimpleNamespace(text="late private text", no_speech_prob=0)], None

    listener.model.transcribe = transcribe
    original = listener._preview_manual
    def preview(*args):
        try:
            original(*args)
        finally:
            finished.set()
    listener._preview_manual = preview
    recording = listener.begin_manual()
    listener._receive(np.ones((16000, 1)))
    listener.finish_manual(recording["id"])
    assert started.wait(3)
    listener.pause()
    listener.resume()
    release.set()
    assert finished.wait(3)
    assert not any(event[1].get("text") for event in events)
    assert not commands


@pytest.mark.parametrize("text", ["", "Thanks for watching!", "[BLANK_AUDIO]"])
def test_silence_hallucinations_have_no_usable_transcript(capture, text):
    listener, events, commands = capture
    listener.model.transcribe = lambda *a, **kw: ([SimpleNamespace(text=text, no_speech_prob=0)], None)
    recording = listener.begin_manual()
    listener._receive(np.ones((16000, 1)))
    listener.finish_manual(recording["id"])
    result = wait_preview(events)
    assert not result["text"] and result["error"] and not commands


def test_expiry_and_stale_recording_ids(capture):
    listener, events, _ = capture
    old = listener.begin_manual()["id"]
    listener.cancel_manual()
    current = listener.begin_manual()["id"]
    listener._expire_manual(old)
    assert listener._manual["id"] == current
    with pytest.raises(ValueError, match="no longer active"):
        listener.finish_manual(old)
    listener._expire_manual(current)
    assert wait_preview(events)["error"].startswith("Recording too short")


def test_manual_setting_and_stop_discard_capture(isolated_app, capture, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, "_watchdog", lambda _: None)
    app = App(cfg, use_voice=False)
    listener, events, _ = capture
    app.listener = listener
    try:
        app.set_preference("voice_input_mode", "manual")
        assert app.state()["voice_input_mode"] == "manual"
        with pytest.raises(ValueError):
            app.set_preference("voice_input_mode", "unsupported")
        app.dictation_operation({"action": "start"})
        app.stop()
        assert listener._manual is None
        app.listener = None
        with pytest.raises(ValueError, match="unavailable"):
            app.dictation_operation({"action": "start"})
    finally:
        app.memory.db.close()
