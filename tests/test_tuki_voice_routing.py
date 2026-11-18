import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jarvis import assistants, config
from jarvis.brain import Brain


def load_voice(monkeypatch):
    monkeypatch.setitem(sys.modules, "winsound", MagicMock())
    spec = importlib.util.spec_from_file_location("voice_profiles", Path(__file__).parents[1] / "jarvis" / "voice.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VOICES = [SimpleNamespace(id="george", name="Microsoft George - English (United Kingdom)"),
          SimpleNamespace(id="zira", name="Microsoft Zira - English (United States)"),
          SimpleNamespace(id="david", name="Microsoft David - English (United States)")]


@pytest.mark.parametrize("text, expected", [
    ("Why does this raise a KeyError?", "tuki"),
    ("What is the probability of two sixes?", "tuki"),
    ("Write a regex for UK postcodes", "tuki"),
    ("How do I resolve a merge conflict in git?", "tuki"),
    ("Convert 5 miles to kilometres", "tuki"),
    ("/test budget.py", "tuki"),
    ("Proofread this: their going home", "jarvis"),
    ("What should I cook tonight?", "jarvis"),
    ("I want to commit to a study plan", "jarvis"),
    ("Tell me a joke", "jarvis"),
])
def test_technical_routing(text, expected):
    assert assistants.route(text)[0] == expected


def test_talk_mode_and_explicit_names_still_win():
    assert assistants.route("Why does this raise a KeyError?", mode="talk")[0] == "jarvis"
    assert assistants.route("Jarvis: what is a KeyError?")[0] == "jarvis"
    assert assistants.route("Tuki, what should I cook?")[0] == "tuki"


def test_tuki_has_a_distinct_voice_with_fallbacks(monkeypatch):
    voice = load_voice(monkeypatch)
    cfg = dict(config.DEFAULTS)
    jarvis = voice.voice_profile(cfg, "jarvis")
    tuki = voice.voice_profile(cfg, "tuki")
    assert voice.pick_voice(VOICES, jarvis["preferences"])[0].id == "george"
    assert voice.pick_voice(VOICES, tuki["preferences"], avoid="george")[0].id == "zira"
    assert tuki["rate"] != jarvis["rate"]
    cfg["tuki_sapi_voice_contains"] = "david"
    assert voice.pick_voice(VOICES, voice.voice_profile(cfg, "tuki")["preferences"], avoid="george")[0].id == "david"
    # Only one installed voice: TUKI falls back to it rather than going silent.
    only = VOICES[:1]
    picked, matched = voice.pick_voice(only, tuki["preferences"], avoid="george")
    assert picked.id == "george" and not matched
    # A configured TUKI Piper model is used only for TUKI.
    cfg.update(tuki_piper_model="C:/voices/en_US-amy.onnx", piper_model="")
    assert voice.voice_profile(cfg, "tuki")["piper_model"].endswith("amy.onnx")
    assert voice.voice_profile(cfg, "jarvis")["piper_model"] == ""
    cfg["tuki_voice_choice"] = "windows"
    assert voice.voice_profile(cfg, "tuki")["piper_model"] == ""


def test_speaker_applies_the_assistant_voice(monkeypatch):
    voice = load_voice(monkeypatch)
    monkeypatch.setattr(voice.threading, "Thread", MagicMock())
    speaker = voice.Speaker(dict(config.DEFAULTS))
    engine = MagicMock()
    engine.getProperty.return_value = VOICES
    speaker._apply_profile(engine, voice.voice_profile(speaker.cfg, "tuki"))
    engine.setProperty.assert_any_call("voice", "zira")
    speaker._apply_profile(engine, voice.voice_profile(speaker.cfg, "jarvis"))
    engine.setProperty.assert_any_call("voice", "george")
    speaker.say("Hello", "tuki")
    assert speaker._q.get_nowait()[2] == "tuki"
    speaker.say("Hello", "someone else")
    assert speaker._q.get_nowait()[2] == "jarvis"


def test_tuki_answers_report_confidence_and_what_was_checked(isolated_app):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)
    with patch.object(brain, "_chat", return_value={"content": "The derivative of x squared is 2x."}):
        reply = brain.ask("Tuki, what is the derivative of x squared?")
    assert "Confidence: not stated" in reply and "model's own knowledge" in reply
    assert assistants.label_uncertainty("Answer.\nConfidence: high, standard rule", ["calculate"]).endswith(
        "Checked with: calculate.")
    with patch.object(brain, "_chat", return_value={"content": "Sure, here is a pasta idea."}):
        assert "Confidence" not in brain.ask("Jarvis: what should I cook?")


def test_preview_uses_the_selected_assistant(isolated_app, monkeypatch):
    from jarvis.__main__ import App
    cfg, _, _, _ = isolated_app
    with patch.object(App, "_watchdog"):
        app = App(cfg, use_voice=False)
    app.speaker = MagicMock()
    app.speaker.describe.return_value = "Windows voice Microsoft Zira"
    result = app.preview_voice("tuki")
    assert result["voice"] == "Windows voice Microsoft Zira"
    assert app.speaker.say.call_args.args[1] == "tuki"
    app.preview_voice("anything")
    assert app.speaker.say.call_args.args[1] == "jarvis"
    with pytest.raises(ValueError, match="Piper"):
        app.set_preference("tuki_voice_choice", "piper")
