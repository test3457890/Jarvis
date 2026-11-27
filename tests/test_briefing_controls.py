"""Daily briefing time, mute and replay controls."""
import datetime
from types import SimpleNamespace

import pytest

from jarvis import planner, skills
from jarvis import __main__ as main
from jarvis.__main__ import App


def test_daily_briefing_time_mute_and_once(isolated_app, monkeypatch):
    cfg, db, ctx, _ = isolated_app
    cfg.update({'briefing_time':'09:00', 'briefing_enabled':True, 'briefing_speak':False})
    class Clock:
        value = datetime.datetime(2026, 11, 26, 8, 59)
        @classmethod
        def now(cls):
            return cls.value
    monkeypatch.setattr(main, 'dt', SimpleNamespace(datetime=Clock, time=datetime.time))
    monkeypatch.setattr(skills, 'briefing', lambda ctx: 'Today: one task.')
    notices = []
    app = App.__new__(App)
    app.cfg, app.memory, app.brain = cfg, db, SimpleNamespace(ctx=ctx)
    app.notify = lambda text, speak=True: notices.append((text, speak))
    app._daily_briefing()
    assert notices == []
    Clock.value = datetime.datetime(2026, 11, 26, 9, 1)
    app._daily_briefing()
    app._daily_briefing()
    assert notices == [('Today: one task.', False)]
    assert planner.kv_get(db, 'last_briefing') == '2026-11-26'
    cfg['briefing_enabled'] = False
    Clock.value = datetime.datetime(2026, 11, 27, 9, 1)
    app._daily_briefing()
    assert len(notices) == 1
    cfg.update({'briefing_enabled':True, 'briefing_speak':True})
    app._daily_briefing()
    assert notices[-1] == ('Today: one task.', True)


def test_briefing_setup_rejects_bad_values(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    try:
        with pytest.raises(ValueError, match='HH:MM'):
            app.settings_operation({'briefing_time':'25:12'})
        with pytest.raises(ValueError, match='spoken'):
            app.settings_operation({'briefing_speak':'false'})
        result = app.settings_operation({'briefing_time':'10:15', 'briefing_enabled':False, 'briefing_speak':False})
        assert result['briefing_time'] == '10:15' and not result['briefing_enabled'] and not result['briefing_speak']
    finally:
        app.memory.db.close()
