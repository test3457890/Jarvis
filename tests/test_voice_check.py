"""The optional voice check exercises the configured paths without real hardware."""
import sys
from types import SimpleNamespace

from jarvis.__main__ import voice_check


class Audio:
    def __getitem__(self, key):
        assert key == (slice(None), 0)
        return self


def test_voice_check_transcribes_and_requests_playback(monkeypatch, capsys):
    events = []
    audio = Audio()
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        rec=lambda *args, **kwargs: (events.append("record"), audio)[1],
        wait=lambda: events.append("wait")))

    class Model:
        def transcribe(self, samples, **kwargs):
            assert samples is audio
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

    monkeypatch.setitem(sys.modules, "jarvis.voice", SimpleNamespace(
        RATE=16000, load_whisper=lambda cfg: Model(), Speaker=Speaker))
    assert voice_check({}) == 0
    assert events == ["record", "wait", "transcribe", "speaker", "say", "playback-wait"]
    assert "Recognized: Hello Jarvis" in capsys.readouterr().out


def test_voice_check_silence_does_not_play(monkeypatch, capsys):
    monkeypatch.setattr("builtins.input", lambda _: "")
    monkeypatch.setitem(sys.modules, "sounddevice", SimpleNamespace(
        rec=lambda *args, **kwargs: Audio(), wait=lambda: None))
    monkeypatch.setitem(sys.modules, "jarvis.voice", SimpleNamespace(
        RATE=16000, Speaker=lambda cfg: None, load_whisper=lambda cfg: SimpleNamespace(
            transcribe=lambda *args, **kwargs: ([], None))))
    assert voice_check({}) == 1
    assert "No speech recognized" in capsys.readouterr().out
