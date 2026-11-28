"""Phase 2 Next-Generation tests:
- Persistent Background Task Engine: checkpoints, crash recovery, cancellation, parallel T0 execution,
  T2/T3 unattended refusal, and wired outcome verification (bgtasks.py)
- Condition Monitoring Sentinels backed by real telemetry snapshots (monitors.py)
- Workflow/Macro recorder, editable macros, dry-run preview & policy-enforced replay (macros.py)
- Reviewable memory extraction (with secret redaction) & daily summary (memextract.py)
"""
import pytest

from jarvis import bgtasks, config, macros, memextract, memory, monitors, skills


def test_bgtasks_checkpoints_recovery_parallel_and_policy_enforcement(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    cfg = dict(config.DEFAULTS)
    mem = memory.Memory()
    ctx = skills.Context(cfg, mem)

    # Unattended T2/T3 risky tools MUST be rejected at creation
    with pytest.raises(ValueError, match="interactive approval"):
        bgtasks.create_task(mem, "Danger", [{"tool": "power", "args": {"action": "shutdown"}}])

    # Sequential T0 task executes, checkpoints, and verifies every step
    t = bgtasks.create_task(mem, "Check status", [
        {"tool": "get_time_date", "args": {}},
        {"tool": "calculate", "args": {"expression": "7 * 9"}},
    ])
    done = bgtasks.execute_task(mem, ctx, t["id"])
    assert done["state"] == "completed"
    assert done["current_step"] == 2
    assert all(r["verification"]["verified"] for r in done["results"])
    assert "63" in done["results"][1]["output"]

    # Parallel T0 task runs concurrently and verifies all outputs
    pt = bgtasks.create_task(mem, "Parallel checks", [
        {"tool": "calculate", "args": {"expression": "10 + 5"}},
        {"tool": "calculate", "args": {"expression": "20 + 5"}},
    ], kind="parallel")
    pdone = bgtasks.execute_task(mem, ctx, pt["id"])
    assert pdone["state"] == "completed"
    assert "15" in pdone["results"][0]["output"]
    assert "25" in pdone["results"][1]["output"]

    # Crash recovery: simulate a task left in 'running' state after a crash
    ct = bgtasks.create_task(mem, "Interrupted", [
        {"tool": "get_time_date", "args": {}},
        {"tool": "calculate", "args": {"expression": "3 * 3"}},
    ])
    with mem._lock:
        mem.db.execute("UPDATE bg_tasks SET state='running', current_step=1 WHERE id=?", (ct["id"],))
        mem.db.commit()
    recovered_ids = bgtasks.recover_interrupted(mem)
    assert ct["id"] in recovered_ids
    rec = bgtasks.get_task(mem, ct["id"])
    assert rec["state"] == "recovered"
    assert rec["current_step"] == 1

    # Resume from checkpoint completes step 2 without re-running step 1
    resumed = bgtasks.execute_task(mem, ctx, ct["id"])
    assert resumed["state"] == "completed"
    assert len(resumed["results"]) == 1
    assert "9" in resumed["results"][0]["output"]

    # Lockdown blocks background execution
    t_lock = bgtasks.create_task(mem, "Locked", [{"tool": "get_time_date", "args": {}}])
    cfg["lockdown"] = True
    with pytest.raises(ValueError, match="Lockdown"):
        bgtasks.execute_task(mem, ctx, t_lock["id"])
    cfg["lockdown"] = False
    cancelled = bgtasks.cancel_task(mem, t_lock["id"])
    assert cancelled["state"] == "cancelled"


def test_condition_monitors_evaluate_against_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    mem = memory.Memory()
    m1 = monitors.create_monitor(mem, name="High CPU", metric="cpu_percent", operator=">=", threshold=80.0)
    m2 = monitors.create_monitor(mem, name="Hot GPU", metric="gpu_temp_c", operator=">", threshold=75.0)
    snap = {"cpu": {"percent": 85.0}, "memory": {"percent": 40.0}, "disk": {"percent": 50.0}, "gpus": [{"temperature_c": 62.0}]}
    alerts = monitors.evaluate_all(mem, snap=snap)
    assert len(alerts) == 1
    assert alerts[0]["id"] == m1["id"]

    # Pausing disables evaluation
    monitors.set_enabled(mem, m1["id"], False)
    assert monitors.evaluate_all(mem, snap=snap) == []
    monitors.delete_monitor(mem, m2["id"])
    assert len(monitors.list_monitors(mem)) == 1


def test_macros_record_preview_and_policy_enforced_replay(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    cfg = dict(config.DEFAULTS)
    mem = memory.Memory()
    ctx = skills.Context(cfg, mem)

    macros.start_recording("Quick Math & Time")
    macros.record_step("get_time_date", {})
    macros.record_step("calculate", {"expression": "8 * 8"})
    res = macros.stop_recording(mem, save=True)
    assert res["saved"] is True
    mid = res["macro"]["id"]

    prev = macros.preview_macro(mem, ctx, mid)
    assert prev["all_allowed"] is True
    assert prev["needs_confirmation"] is False

    rep = macros.replay_macro(mem, ctx, mid)
    assert rep["steps_run"] == 2
    assert rep["halted_for_confirmation"] is False
    assert "64" in rep["outputs"][1]["output"]

    # Macro containing a risky step MUST halt for confirmation and NEVER bypass approval
    risky_m = macros.save_macro(mem, name="Risky Macro", steps=[
        {"tool": "get_time_date", "args": {}},
        {"tool": "power", "args": {"action": "shutdown"}},
    ])
    rep_risky = macros.replay_macro(mem, ctx, risky_m["id"])
    assert rep_risky["halted_for_confirmation"] is True
    assert rep_risky["pending"] is not None
    assert ctx.pending["name"] == "power"


def test_reviewable_memory_extraction_and_daily_summary(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    cfg = dict(config.DEFAULTS)
    mem = memory.Memory()

    text = "I prefer dark themes and concise answers. My project is Jarvis 2.0 with key sk-1234567890abcdef12345678."
    cands = memextract.extract_candidates(text)
    assert len(cands) >= 2
    assert all("sk-1234567890" not in c["text"] for c in cands)

    # Not saved until explicitly approved
    assert mem.all_facts() == []
    memextract.approve_candidate(mem, cands[0]["text"])
    assert len(mem.all_facts()) == 1

    summary = memextract.daily_summary(mem, cfg)
    assert "date" in summary and "background_tasks" in summary and "monitors" in summary
