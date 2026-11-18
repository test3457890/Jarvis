"""Core regression tests: DPAPI secrets, planner/Canvas sync, and Brain confirmation."""
import datetime as dt
import os
from unittest.mock import patch

import pytest

from jarvis import brain as brain_mod, planner, secure


@pytest.mark.skipif(os.name != "nt", reason="Windows DPAPI integration test")
def test_dpapi_secrets_roundtrip(isolated_app):
    secure.set_secret("canvas_token", "secret-token-123")
    assert secure.has_secret("canvas_token") is True
    assert secure.get_secret("canvas_token") == "secret-token-123"
    secure.set_secret("canvas_token", "")
    assert secure.has_secret("canvas_token") is False


def test_canvas_sync_no_duplicates_and_plan_week(isolated_app, mock_canvas_secret):
    cfg, db, ctx, app_dir = isolated_app
    due = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=3)
    mock_canvas_secret("https://canvas.example.edu/feeds/calendars/test.ics")
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        "BEGIN:VEVENT\r\n"
        "UID:event-assignment-101\r\n"
        f"DTSTART:{due:%Y%m%dT%H%M%SZ}\r\n"
        "SUMMARY:Lab Report [CYBER-101]\r\n"
        "URL:https://canvas.example.edu/courses/1/assignments/101\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )

    class _FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): pass
        def read(self, n=-1): return ics.encode()

    with patch("jarvis.net.urlopen", return_value=_FakeResp()):
        r1 = planner.sync_canvas_now(db, cfg, force=True)
        r2 = planner.sync_canvas_now(db, cfg, force=True)

    assert "1 new assignments" in r1
    assert "0 new assignments" in r2  # no duplicates
    with patch("jarvis.planner.Path.home", return_value=app_dir):
        ics_out = planner.export_calendar(ctx)
    assert "Exported 1 items" in ics_out
    exported = (app_dir / "Documents" / "Jarvis Calendar.ics").read_bytes()
    assert b"SUMMARY:DUE: Lab Report" in exported
    assert b"\r\r\n" not in exported and exported.endswith(b"END:VCALENDAR\r\n")


def test_brain_yes_no_handled_in_code(isolated_app):
    cfg, db, _, _ = isolated_app
    b = brain_mod.Brain(cfg, db)
    b.ctx.pending = {"name": "tell_joke", "args": {}, "preview": "tell a joke"}
    with patch.object(b, "_chat", side_effect=AssertionError("Model must not be called for yes/no")):
        assert b.ask("no") == "Cancelled. Nothing was done."
        b.ctx.pending = {"name": "tell_joke", "args": {}, "preview": "tell a joke"}
        res = b.ask("yes")
        assert res and "Cancelled" not in res
