"""Workspace choices share one backend and preserve existing modes and themes."""
import pytest

from jarvis import config
from jarvis.__main__ import App


def test_view_selection_is_persisted_independently(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, "_watchdog", lambda _: None)
    app = App(cfg, use_voice=False)
    original = {key:cfg[key] for key in ("mode","theme","assistant","speak_replies")}
    try:
        for view in config.WORKSPACE_VIEWS:
            result = app.set_preference("workspace_view", view)
            assert result["workspace_view"] == view
            assert config.load()["workspace_view"] == view
            assert all(cfg[key] == value for key, value in original.items())
        with pytest.raises(ValueError):
            app.set_preference("workspace_view", "unknown")
        assert app.state()["active_assistant"] == app.brain.assistant
    finally:
        app.memory.db.close()
