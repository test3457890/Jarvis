"""Small local read-only workflows. No model-generated step or shell execution."""
import hashlib
import json
import time
import uuid

from . import secure, skills
from .memory import redact

KINDS = {
    "documents": ("search_documents", "query", "Research selected documents"),
    "schedule": ("show_schedule", "when", "Read saved schedule"),
    "tasks": ("list_tasks", None, "Read open tasks"),
    "behind": ("whats_falling_behind", None, "Review deadlines"),
    "calculate": ("calculate", "expression", "Calculate expression"),
    "reminders": ("list_reminders", None, "Read upcoming reminders"),
    "notes": ("list_notes", None, "List saved notes"),
    "memory": ("recall", "query", "Search local memory"),
}


def init_db(memory):
    with memory._lock, memory.db:
        memory.db.executescript("""
            CREATE TABLE IF NOT EXISTS workflows (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, steps TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS workflow_runs (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, steps TEXT NOT NULL,
                cursor INTEGER NOT NULL DEFAULT 0, results TEXT NOT NULL DEFAULT '[]',
                state TEXT NOT NULL, error TEXT NOT NULL DEFAULT '', updated REAL NOT NULL);
        """)
        memory.db.execute("UPDATE workflow_runs SET state='interrupted', error='Jarvis restarted; review before resuming.' WHERE state='running'")


def validate_steps(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 10:
        raise ValueError("A workflow needs between 1 and 10 steps.")
    steps = []
    for step in value:
        if not isinstance(step, dict) or set(step) - {"kind", "value"}:
            raise ValueError("Each step needs a supported kind and optional value.")
        kind, argument = step.get("kind"), step.get("value", "")
        if not isinstance(kind, str) or kind not in KINDS or not isinstance(argument, str):
            raise ValueError("Choose a supported local workflow step.")
        argument = argument.strip()
        if len(argument) > 500 or (kind in ("documents", "calculate", "memory") and not argument):
            raise ValueError("Enter a step value of at most 500 characters.")
        if kind == "schedule" and argument not in ("today", "tomorrow", "week"):
            raise ValueError("Schedule steps accept today, tomorrow or week.")
        if KINDS[kind][1] is None and argument:
            raise ValueError("This step does not accept a value.")
        steps.append({"kind": kind, "value": argument})
    return steps


def revision(name, steps):
    return hashlib.sha256(json.dumps([name, steps], sort_keys=True).encode()).hexdigest()


def list_templates(memory):
    with memory._lock:
        rows = memory.db.execute("SELECT id, name, steps FROM workflows ORDER BY name, id").fetchall()
    return [{"id": key, "name": name, "steps": json.loads(steps),
             "revision": revision(name, json.loads(steps))} for key, name, steps in rows]


def save_template(memory, name, steps):
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80:
        raise ValueError("Choose a workflow name between 1 and 80 characters.")
    steps = validate_steps(steps)
    # Workflow inputs are user-authored. Never persist likely credentials in a template.
    if redact(name) != name or redact(json.dumps(steps)) != json.dumps(steps):
        raise ValueError("Remove credentials or sensitive numbers from workflow inputs.")
    with memory._lock, memory.db:
        if memory.db.execute("SELECT COUNT(*) FROM workflows").fetchone()[0] >= 20:
            raise ValueError("At most 20 workflows can be saved. Delete an old workflow first.")
        memory.db.execute("INSERT INTO workflows VALUES (?, ?, ?)",
                          (uuid.uuid4().hex, name.strip(), json.dumps(steps)))


def get_run(memory, key):
    with memory._lock:
        row = memory.db.execute("SELECT id, name, steps, cursor, results, state, error, updated FROM workflow_runs WHERE id=?", (key,)).fetchone()
    if not row:
        raise ValueError("Workflow run not found.")
    result = dict(zip(("id", "name", "steps", "cursor", "results", "state", "error", "updated"), row))
    result["steps"], result["results"] = json.loads(result["steps"]), json.loads(result["results"])
    result["revision"] = revision(result["name"], result["steps"])
    return result


def list_runs(memory):
    with memory._lock:
        rows = memory.db.execute("SELECT id FROM workflow_runs ORDER BY updated DESC LIMIT 50").fetchall()
    return [get_run(memory, row[0]) for row in rows]


def create_run(memory, key, expected):
    template = next((row for row in list_templates(memory) if row["id"] == key), None)
    if template is None:
        raise ValueError("Workflow not found. Refresh the preview.")
    if expected != template["revision"]:
        raise ValueError("Workflow changed. Review a fresh preview before running it.")
    run_id = uuid.uuid4().hex
    with memory._lock, memory.db:
        if memory.db.execute("SELECT COUNT(*) FROM workflow_runs").fetchone()[0] >= 50:
            raise ValueError("At most 50 workflow runs can be kept. Delete old results first.")
        memory.db.execute("INSERT INTO workflow_runs(id, name, steps, state, updated) VALUES (?, ?, ?, 'running', ?)",
                          (run_id, template["name"], json.dumps(template["steps"]), time.time()))
    return run_id


def update(memory, key, **values):
    assert set(values) <= {"cursor", "results", "state", "error"}
    if "results" in values:
        values["results"] = json.dumps(values["results"])
    values["updated"] = time.time()
    with memory._lock, memory.db:
        memory.db.execute("UPDATE workflow_runs SET " + ", ".join(f"{field}=?" for field in values) + " WHERE id=?",
                          (*values.values(), key))


def execute(memory, cfg, key, cancelled, changed):
    """Checkpoint after each local read. Resume never repeats completed steps."""
    run = get_run(memory, key)
    steps = validate_steps(run["steps"])
    results = run["results"]
    try:
        for index in range(run["cursor"], len(steps)):
            if cancelled.is_set():
                update(memory, key, state="cancelled", error="Stopped before the next step.")
                return
            if cfg.get("lockdown"):
                update(memory, key, state="blocked", error="Lockdown is active.")
                return
            step = steps[index]
            tool, arg, _ = KINDS[step["kind"]]
            # Ask permissions require a separate step approval; this initial runner stops
            # instead of treating approval of the overall workflow as tool approval.
            if skills.permission_level(cfg, tool) != "allowed":
                update(memory, key, state="blocked", error=f"{tool} is disabled or requires individual approval. Run that step directly.")
                return
            ctx = skills.Context(cfg, memory)
            ctx.cancelled = cancelled
            output = skills.run(ctx, tool, {arg: step["value"]} if arg else {})
            if cancelled.is_set():
                update(memory, key, state="cancelled", error="Stopped; the unfinished read can be retried.")
                return
            if cfg.get("lockdown") or ctx.injection_seen or ctx.pending:
                update(memory, key, state="blocked", error="Step blocked by Lockdown, unsafe source text or an approval requirement.")
                return
            if output.startswith((f"{tool} failed:", f"Bad arguments for {tool}:", f"{tool} isn't set up")):
                update(memory, key, state="failed", error=f"Step {index + 1} failed; check its inputs and local setup.")
                return
            results.append({"step": index + 1, "kind": step["kind"], "text": redact(output[:16000]), "time": time.time()})
            update(memory, key, cursor=index + 1, results=results, error="")
            changed()
        update(memory, key, state="completed", error="")
    except Exception:
        update(memory, key, state="failed", error="Local step failed. Check configuration and review before resuming.")
    finally:
        secure.audit("workflow_run", {"id": key, "completed_steps": len(results)})
        changed()


def delete(memory, table, key):
    if table not in ("workflows", "workflow_runs") or not isinstance(key, str):
        raise ValueError("Choose a saved workflow or run.")
    with memory._lock, memory.db:
        row = memory.db.execute(f"SELECT * FROM {table} WHERE id=?", (key,)).fetchone()
        if not row:
            raise ValueError("Workflow or run not found.")
        if table == "workflow_runs" and memory.db.execute("SELECT state FROM workflow_runs WHERE id=?", (key,)).fetchone()[0] == "running":
            raise ValueError("Stop the workflow before deleting its results.")
        memory.db.execute(f"DELETE FROM {table} WHERE id=?", (key,))
