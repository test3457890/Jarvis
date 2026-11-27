"""Local model inventory and explicit role selection."""
import pytest

from jarvis import setupwizard
from jarvis.__main__ import App


def test_model_inventory_and_role_selection(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    monkeypatch.setattr(setupwizard, 'installed_ollama',
                        lambda cfg: {'qwen3:4b': 2_500_000_000, 'coder:7b': 4_000_000_000})
    app = App(cfg, use_voice=False)
    try:
        report = app.models_operation()
        assert report['reachable'] and report['models'][0]['disk_bytes'] == 4_000_000_000
        updated = app.models_operation({'role':'coder_model', 'name':'coder:7b'})
        assert updated['selected']['coder_model'] == 'coder:7b'
        with pytest.raises(ValueError, match='installed'):
            app.models_operation({'role':'model', 'name':'not-installed'})
        with pytest.raises(ValueError, match='role'):
            app.models_operation({'role':'embed_model', 'name':'coder:7b'})
        cfg['lockdown'] = True
        with pytest.raises(ValueError, match='Lockdown'):
            app.models_operation({'role':'model', 'name':'qwen3:4b'})
    finally:
        app.memory.db.close()


def test_model_inventory_handles_unavailable_ollama(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    monkeypatch.setattr(setupwizard, 'installed_ollama', lambda cfg: None)
    app = App(cfg, use_voice=False)
    try:
        assert app.models_operation()['models'] == []
        with pytest.raises(ValueError, match='unavailable'):
            app.models_operation({'role':'model', 'name':'qwen3:8b'})
    finally:
        app.memory.db.close()
