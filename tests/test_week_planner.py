import datetime as dt
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from jarvis import planner
from jarvis.brain import Brain


@pytest.fixture
def morning(monkeypatch):
    day = dt.date.today()
    now = planner.at(day, dt.time(7))
    monkeypatch.setattr(planner.time, "time", lambda: now)
    return day


def blocks(db):
    return db.db.execute(
        "SELECT uid, start, end, task_id FROM events WHERE source='plan' ORDER BY start"
    ).fetchall()


def test_blocks_fit_around_class_and_replanning_counts_started_work(isolated_app, morning, monkeypatch):
    cfg, db, ctx, _ = isolated_app
    cfg.update(work_hours=[8, 12], max_planned_minutes_per_day=75)
    planner.add_event(ctx, "Class", morning.isoformat(), "8 am", 30)
    planner.add_task(ctx, "Worksheet", morning.isoformat(), minutes=60)
    planner.add_task(ctx, "Outline", morning.isoformat(), minutes=15)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports = list(pool.map(lambda _: planner.make_week_plan(db, cfg), range(2)))
    assert reports[0] == reports[1]
    before = blocks(db)
    assert [(dt.datetime.fromtimestamp(s).strftime("%H:%M"), (e-s)/60) for _, s, e, _ in before] == [
        ("08:35", 50), ("09:30", 10), ("09:45", 15)
    ]
    assert "min short" not in reports[0]

    monkeypatch.setattr(planner.time, "time", lambda: planner.at(morning, dt.time(8, 45)))
    assert "Planned 2 work blocks" in planner.make_week_plan(db, cfg)
    assert blocks(db) == before
    assert db.db.execute("SELECT COUNT(*) FROM tasks WHERE status='open'").fetchone() == (2,)


def test_deadline_buffer_and_partial_capacity_are_distinct(isolated_app, morning):
    cfg, db, ctx, _ = isolated_app
    cfg.update(work_hours=[8, 9], max_planned_minutes_per_day=30, study_lead_hours=24)
    planner.add_task(ctx, "Quiz prep", morning.isoformat(), "8:20 am", 40)
    tomorrow = morning + dt.timedelta(days=1)
    planner.add_task(ctx, "Reading", tomorrow.isoformat(), "9 am", 20)
    report = planner.make_week_plan(db, cfg)
    assert "20 min short" in report
    assert "Scheduled within 24h of the deadline: Reading" in report
    assert [(dt.datetime.fromtimestamp(s).date(), (e-s)/60) for _, s, e, _ in blocks(db)] == [
        (morning, 20), (morning, 10), (tomorrow, 10)
    ]
    assert blocks(db)[0][2] == planner.at(morning, dt.time(8, 20))
    cfg["study_lead_hours"] = 0
    assert "Scheduled within" not in planner.make_week_plan(db, cfg)


def test_seven_calendar_days_and_work_left_for_later(isolated_app, morning):
    cfg, db, ctx, _ = isolated_app
    cfg.update(work_hours=[8, 9], max_planned_minutes_per_day=30)
    planner.add_task(ctx, "Term project", (morning + dt.timedelta(days=14)).isoformat(), minutes=300)
    report = planner.make_week_plan(db, cfg)
    assert "Term project (90 min left)" in report
    assert "min short" not in report
    assert [dt.datetime.fromtimestamp(s).date() for _, s, _, _ in blocks(db)] == [
        morning + dt.timedelta(days=i) for i in range(7)
    ]


def test_failed_rebuild_keeps_previous_plan(isolated_app, morning):
    cfg, db, ctx, _ = isolated_app
    planner.add_task(ctx, "Worksheet", morning.isoformat(), minutes=65)
    planner.make_week_plan(db, cfg)
    before = blocks(db)
    db.db.execute(
        "CREATE TRIGGER fail_insert BEFORE INSERT ON events WHEN NEW.source='plan' "
        "BEGIN SELECT RAISE(ABORT, 'simulated write failure'); END"
    )
    with pytest.raises(sqlite3.IntegrityError, match="simulated write failure"):
        planner.make_week_plan(db, cfg)
    assert blocks(db) == before


def test_cached_all_day_events_block_dates_and_keep_assignment_due_time(isolated_app, mock_canvas_secret, morning):
    cfg, db, _, _ = isolated_app
    after_trip = morning + dt.timedelta(days=2)
    mock_canvas_secret("https://canvas.example.edu/feeds/calendars/test.ics")
    planner.CANVAS_CACHE.write_text(
        "BEGIN:VCALENDAR\nBEGIN:VEVENT\nUID:trip\nSUMMARY:Field trip\n"
        f"DTSTART;VALUE=DATE:{morning:%Y%m%d}\nDTEND;VALUE=DATE:{after_trip:%Y%m%d}\nEND:VEVENT\n"
        "BEGIN:VEVENT\nUID:event-assignment-1\nSUMMARY:Reflection\n"
        f"DTSTART;VALUE=DATE:{after_trip:%Y%m%d}\nEND:VEVENT\nEND:VCALENDAR", encoding="utf-8"
    )
    planner.kv_set(db, "canvas_last_sync", planner.time.time())
    with patch("jarvis.net.urlopen", side_effect=AssertionError("Unexpected network call")):
        planner.sync_canvas_now(db, cfg)
    assert db.db.execute("SELECT start, end FROM events WHERE uid='trip'").fetchone() == (
        planner.at(morning, dt.time.min), planner.at(after_trip, dt.time.min)
    )
    assert db.db.execute("SELECT due FROM tasks").fetchone() == (planner.at(after_trip, dt.time(23, 59)),)
    planner.make_week_plan(db, cfg)
    assert blocks(db)[0][1] == planner.at(after_trip, dt.time(8))


def test_ics_dates_durations_and_explicit_date_time():
    def event(properties):
        return planner.parse_ics("BEGIN:VEVENT\n" + properties + "\nEND:VEVENT")[0]

    assert event("DTSTART;VALUE=DATE:20261118")["end"] == dt.datetime(2026, 11, 19).timestamp()
    assert event("DTSTART:20261118\nDURATION:P2D")["end"] == dt.datetime(2026, 11, 20).timestamp()
    timed = event("DTSTART;VALUE=DATE-TIME:20261118T120000Z")
    assert not timed["all_day"]
    assert timed["start"] == dt.datetime(2026, 11, 18, 12, tzinfo=dt.timezone.utc).timestamp()


def test_planner_commands_work_without_a_model_and_keep_permissions(isolated_app, morning):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)
    with patch.object(brain, "_post", side_effect=AssertionError("Unexpected model request")), \
            patch("jarvis.net.urlopen", side_effect=AssertionError("Unexpected network request")):
        assert "Task added" in brain.ask(f"/task Lab | Part A | {morning.isoformat()} @ 5 pm | 60")
        assert "Lab | Part A" in brain.ask("/tasks")
        assert "Planned 2 work blocks" in brain.ask("/plan")
        assert "Work on: Lab | Part A" in brain.ask("/schedule week")
        assert "positive whole number" in brain.ask("/task Another task | today | -1")
        assert "OUTSIDE CONTENT" not in brain.ask("/schedule")
        cfg["skill_permissions"] = {"plan_week": "off", "add_task": "ask"}
        assert "disabled" in brain.ask("/plan")
        assert "confirm" in brain.ask("/task Second task").lower()
        assert db.db.execute("SELECT COUNT(*) FROM tasks").fetchone() == (1,)
        brain.confirm_pending(False)
        cfg["mode"] = "talk"
        assert "Talk mode" in brain.ask("/task Third task")
        assert db.db.execute("SELECT COUNT(*) FROM tasks").fetchone() == (1,)
