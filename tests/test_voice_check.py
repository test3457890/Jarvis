"""The optional voice check records in memory and exercises the configured paths."""
import sys
from types import SimpleNamespace

import numpy as np

from jarvis import voice
from jarvis.__main__ import voice_check


def test_voice_check_transcribes_and_requests_playback(monkeypatch, capsys):
    events = []
    audio = np.zeros((4 * voice.RATE, 1), dtype=np.float32)
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        rec=lambda *args, **kwargs: (events.append("record"), audio)[1],
        wait=lambda: events.append("wait")))

    class Model:
        def transcribe(self, samples, **kwargs):
            assert samples.shape == (4 * voice.RATE,)
            assert kwargs["language"] == "en"
            events.append("transcribe")
            return [SimpleNamespace(text=" Hello Jarvis", no_speech_prob=0.1)], None

    class Speaker:
        def __init__(self, cfg):
            events.append("speaker")

        def say(self, message):
            assert message == "Jarvis voice check complete."
            events.append("say")

        def wait(self):
            events.append("playback-wait")

    monkeypatch.setattr(voice, "load_whisper", lambda cfg: Model())
    monkeypatch.setattr(voice, "Speaker", Speaker)
    assert voice_check({}) == 0
    assert events == ["record", "wait", "transcribe", "speaker", "say", "playback-wait"]
    assert "Recognized: Hello Jarvis" in capsys.readouterr().out


def test_voice_check_silence_does_not_play(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        rec=lambda *args, **kwargs: np.zeros((4 * voice.RATE, 1), dtype=np.float32),
        wait=lambda: None))
    monkeypatch.setattr(voice, "load_whisper", lambda cfg: SimpleNamespace(
        transcribe=lambda *args, **kwargs: ([], None)))
    assert voice_check({}) == 1
    assert "No speech recognized" in capsys.readouterr().out
