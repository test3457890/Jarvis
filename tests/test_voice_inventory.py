"""System voice selection checks installed names and preserves assistant choice."""
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from jarvis import voice
from jarvis.__main__ import App


def test_exact_installed_voice_name_wins_over_substring_fallback():
    voices = [SimpleNamespace(id='first', name='English George Extra'),
              SimpleNamespace(id='george', name='English George')]
    assert voice.pick_voice(voices, ('English George', 'george'))[0].id == 'george'
    assert voice.pick_voice(voices, ('English George',), avoid='george')[0].id == 'first'


def test_system_voice_selection_uses_installed_names(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    monkeypatch.setattr(voice, 'installed_voice_names', lambda: ['English George', 'English Zira'])
    try:
        app.set_preference('sapi_voice_contains', 'English George')
        app.set_preference('tuki_sapi_voice_contains', 'English Zira')
        assert app.state()['sapi_voice_contains'] == 'English George'
        assert voice.voice_profile(cfg, 'jarvis')['preferences'][0] == 'english george'
        assert voice.voice_profile(cfg, 'tuki')['preferences'][0] == 'english zira'
        with pytest.raises(ValueError, match='installed'):
            app.set_preference('sapi_voice_contains', 'imaginary voice')
        assert app.state()['sapi_voice_contains'] == 'English George'
        app.set_preference('sapi_voice_contains', '')
        assert app.state()['sapi_voice_contains'] == ''
    finally:
        app.memory.db.close()


def test_voice_inventory_handles_unavailable_engine():
    with patch.dict('sys.modules', {'pyttsx3': None}):
        assert voice.installed_voice_names() == []
