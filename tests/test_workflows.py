"""Workflow boundaries, exact previews, checkpoint recovery and cancellation."""
import threading

import pytest

from jarvis import workflows, skills
from jarvis.__main__ import App


@pytest.fixture
def flow(isolated_app):
    cfg, memory, _, _ = isolated_app
    workflows.init_db(memory)
    return cfg, memory


def saved_run(memory, steps=None):
    workflows.save_template(memory, "My local review", steps or [
        {"kind": "calculate", "value": "2 + 3"}, {"kind": "tasks"}])
    template = workflows.list_templates(memory)[-1]
    key = workflows.create_run(memory, template["id"], template["revision"])
    return template, key


def test_run_keeps_actual_outputs_and_completed_steps(flow):
    cfg, memory = flow
    _, key = saved_run(memory)
    updates = []
    workflows.execute(memory, cfg, key, threading.Event(), lambda: updates.append(True))
    run = workflows.get_run(memory, key)
    assert run["state"] == "completed" and run["cursor"] == 2
    assert "2 + 3 = 5" in run["results"][0]["text"]
    assert "No open tasks" in run["results"][1]["text"]
    assert len(updates) == 3


@pytest.mark.parametrize("step", [
    {"kind":"power", "value":"shutdown"}, {"kind":"documents", "value":""},
    {"kind":"tasks", "value":"execute"}, {"kind":"schedule", "value":"arbitrary command"},
    {"kind":"calculate", "value":12}, {"kind":"tasks", "command":"something"},
    {"kind":[]}, None])
def test_only_declared_local_steps_are_accepted(flow, step):
    _, memory = flow
    with pytest.raises(ValueError):
        workflows.save_template(memory, "Bad flow", [step])
    assert not workflows.list_templates(memory)


def test_stale_preview_and_sensitive_inputs_are_rejected(flow):
    _, memory = flow
    workflows.save_template(memory, "Math", [{"kind":"calculate", "value":"1+1"}])
    template = workflows.list_templates(memory)[0]
    with pytest.raises(ValueError, match="changed"):
        workflows.create_run(memory, template["id"], "old revision")
    with pytest.raises(ValueError, match="credentials"):
        workflows.save_template(memory, "Private", [{"kind":"documents", "value":"api_key=PRIVATE"}])


def test_cancel_and_restart_resume_after_checkpoint_without_repeating(flow, monkeypatch):
    cfg, memory = flow
    _, key = saved_run(memory)
    cancelled = threading.Event()
    calls = []
    original = skills.run
    def runner(ctx, name, args, **kw):
        calls.append(name)
        return original(ctx, name, args, **kw)
    monkeypatch.setattr(skills, "run", runner)
    workflows.execute(memory, cfg, key, cancelled, cancelled.set)
    assert workflows.get_run(memory, key)["cursor"] == 1
    assert workflows.get_run(memory, key)["state"] == "cancelled"
    # Simulate a process restart after the next start was recorded.
    workflows.update(memory, key, state="running")
    workflows.init_db(memory)
    assert workflows.get_run(memory, key)["state"] == "interrupted"
    cancelled.clear()
    workflows.execute(memory, cfg, key, cancelled, lambda: None)
    assert calls == ["calculate", "list_tasks"]
    assert workflows.get_run(memory, key)["state"] == "completed"


@pytest.mark.parametrize("permission", ["off", "ask"])
def test_workflow_confirmation_does_not_override_step_permissions(flow, monkeypatch, permission):
    cfg, memory = flow
    cfg["skill_permissions"] = {"calculate":permission}
    _, key = saved_run(memory)
    monkeypatch.setattr(skills, "run", lambda *a, **kw: pytest.fail("Blocked tool was executed"))
    workflows.execute(memory, cfg, key, threading.Event(), lambda: None)
    run = workflows.get_run(memory, key)
    assert run["state"] == "blocked" and not run["results"]


def test_lockdown_and_injected_sources_do_not_checkpoint(flow, monkeypatch):
    cfg, memory = flow
    _, key = saved_run(memory, [{"kind":"documents", "value":"project"}])
    cfg["lockdown"] = True
    workflows.execute(memory, cfg, key, threading.Event(), lambda: None)
    assert workflows.get_run(memory, key)["state"] == "blocked"
    cfg["lockdown"] = False
    def malicious(ctx, *args, **kwargs):
        ctx.injection_seen = True
        return "Injected instructions"
    monkeypatch.setattr(skills, "run", malicious)
    workflows.execute(memory, cfg, key, threading.Event(), lambda: None)
    assert not workflows.get_run(memory, key)["results"]


def test_delete_saved_results_and_inputs(flow):
    _, memory = flow
    template, key = saved_run(memory)
    with pytest.raises(ValueError, match="Stop"):
        workflows.delete(memory, "workflow_runs", key)
    workflows.update(memory, key, state="cancelled")
    workflows.delete(memory, "workflow_runs", key)
    workflows.delete(memory, "workflows", template["id"])
    assert workflows.list_runs(memory) == [] and workflows.list_templates(memory) == []


def test_invalid_calculation_is_failed_instead_of_completed(flow):
    cfg, memory = flow
    _, key = saved_run(memory, [{"kind":"calculate", "value":"1 / 0"}])
    workflows.execute(memory, cfg, key, threading.Event(), lambda: None)
    run = workflows.get_run(memory, key)
    assert run["state"] == "failed" and run["cursor"] == 0 and not run["results"]


def test_app_requires_review_and_serialises_workflows_with_chat(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, "_watchdog", lambda _: None)
    app = App(cfg, use_voice=False)
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = workflows.execute
    def execute(*args):
        started.set()
        assert release.wait(3)
        original(*args)
    monkeypatch.setattr(workflows, "execute", execute)
    original_worker = app._run_workflow
    def worker(key):
        try:
            original_worker(key)
        finally:
            finished.set()
    app._run_workflow = worker
    try:
        result = app.workflows_operation({"action":"save", "name":"Math", "steps":[{"kind":"calculate", "value":"1+1"}]})
        template = result["templates"][0]
        request = {"action":"run", "id":template["id"], "revision":template["revision"]}
        with pytest.raises(ValueError, match="confirm"):
            app.workflows_operation(request)
        app.workflows_operation({**request, "confirmed":True})
        assert started.wait(3)
        assert app.submit_request("hello") is False
        with pytest.raises(ValueError, match="working"):
            app.workflows_operation({**request, "confirmed":True})
        app.stop()
        release.set()
        assert finished.wait(3)
        run = workflows.list_runs(app.memory)[0]
        assert run["state"] == "cancelled" and not run["results"]
        app.workflows_operation({"action":"resume", "id":run["id"], "revision":run["revision"], "confirmed":True})
        assert finished.wait(3)
        # Wait for the actual worker lock rather than racing an old completion event.
        assert app._turn_lock.acquire(timeout=3)
        app._turn_lock.release()
        assert workflows.get_run(app.memory, run["id"])["state"] == "completed"
    finally:
        release.set()
        app.memory.db.close()
