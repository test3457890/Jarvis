"""Persistent Background Task Engine with SQLite checkpoints, crash recovery,
cancellation, bounded parallel read-only execution, and wired outcome verification.

Security rules:
- Unattended background tasks may ONLY execute non-risky T0/T1 tools; T2/T3 risky tools
  are refused and audited so background execution can never bypass human confirmation.
- Every step executes through skills.run() and is verified by verify_step_outcome().
- On startup, any task left in 'running' state after a crash is marked 'recovered' with
  its last persisted checkpoint intact for explicit user resume or cancellation.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import secrets
import threading
import time

from . import secure, skills

ALLOWED_BG_TIERS = frozenset({"T0", "T1"})
_ACTIVE_CANCELS: dict[str, threading.Event] = {}
_LOCK = threading.Lock()


def init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS bg_tasks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'sequential',
                steps_json TEXT NOT NULL,
                current_step INTEGER NOT NULL DEFAULT 0,
                state TEXT NOT NULL DEFAULT 'queued',
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                results_json TEXT NOT NULL DEFAULT '[]',
                error TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def recover_interrupted(mem) -> list[str]:
    """Mark any tasks interrupted mid-run by a crash/restart as 'recovered'."""
    init_db(mem)
    now = time.time()
    with mem._lock:
        rows = mem.db.execute("SELECT id FROM bg_tasks WHERE state='running'").fetchall()
        ids = [r[0] for r in rows]
        if ids:
            mem.db.execute(
                "UPDATE bg_tasks SET state='recovered', error='Interrupted by restart; ready to resume.', updated_at=? WHERE state='running'",
                (now,),
            )
            mem.db.commit()
    if ids:
        secure.audit("bg_tasks_recovered", {"count": len(ids), "ids": ids[:20]})
    return ids


def verify_step_outcome(tool: str, result: str) -> dict:
    """Deterministic outcome verifier wired into every background step execution."""
    text = str(result or "").strip()
    lower = text.lower()
    if not text:
        return {"verified": False, "reason": "Empty tool output."}
    for prefix in (f"{tool.lower()} failed:", "unknown tool", "wrong arguments", "bad arguments",
                   "lockdown mode is active", "blocked for safety", "stopped by the user", "not done yet."):
        if lower.startswith(prefix):
            return {"verified": False, "reason": text[:160]}
    if "is disabled in settings" in lower or "offline mode" in lower:
        return {"verified": False, "reason": text[:160]}
    return {"verified": True, "reason": "Verified non-error tool output."}


def create_task(mem, title: str, steps: list[dict], *, kind: str = "sequential") -> dict:
    init_db(mem)
    clean_title = str(title or "").strip()[:120]
    if not clean_title:
        raise ValueError("Task title is required.")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 25:
        raise ValueError("Provide between 1 and 25 task steps.")
    if kind not in ("sequential", "parallel"):
        raise ValueError("Task kind must be 'sequential' or 'parallel'.")
    clean_steps = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str) or not step["tool"].strip():
            raise ValueError(f"Step {idx + 1} must specify a tool name.")
        tool = step["tool"].strip()
        if tool not in skills.SKILLS:
            raise ValueError(f"Unknown tool '{tool}' in step {idx + 1}.")
        tier = skills.risk_tier(tool)
        if tier not in ALLOWED_BG_TIERS:
            secure.audit("bg_task_rejected", {"tool": tool, "tier": tier})
            raise ValueError(f"Tool '{tool}' ({tier}) requires interactive approval and cannot run unattended in background tasks.")
        args = step.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"Step {idx + 1} args must be a JSON object.")
        clean_steps.append({"tool": tool, "args": args})

    task_id = f"bg-{secrets.token_hex(5)}"
    now = time.time()
    with mem._lock:
        mem.db.execute(
            """INSERT INTO bg_tasks (id, title, kind, steps_json, current_step, state, checkpoint_json, results_json, error, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, 'queued', '{}', '[]', '', ?, ?)""",
            (task_id, clean_title, kind, json.dumps(clean_steps), now, now),
        )
        mem.db.commit()
    secure.audit("bg_task_created", {"id": task_id, "kind": kind, "steps": len(clean_steps)})
    return get_task(mem, task_id)


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "title": row[1],
        "kind": row[2],
        "steps": json.loads(row[3]),
        "current_step": row[4],
        "state": row[5],
        "checkpoint": json.loads(row[6]),
        "results": json.loads(row[7]),
        "error": row[8],
        "created_at": row[9],
        "updated_at": row[10],
    }


def get_task(mem, task_id: str) -> dict | None:
    init_db(mem)
    with mem._lock:
        row = mem.db.execute(
            "SELECT id, title, kind, steps_json, current_step, state, checkpoint_json, results_json, error, created_at, updated_at FROM bg_tasks WHERE id=?",
            (task_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def list_tasks(mem, limit: int = 30) -> list[dict]:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, title, kind, steps_json, current_step, state, checkpoint_json, results_json, error, created_at, updated_at FROM bg_tasks ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def cancel_task(mem, task_id: str) -> dict:
    init_db(mem)
    with _LOCK:
        ev = _ACTIVE_CANCELS.get(task_id)
        if ev is not None:
            ev.set()
    with mem._lock:
        mem.db.execute(
            "UPDATE bg_tasks SET state='cancelled', updated_at=? WHERE id=? AND state IN ('queued', 'running', 'paused', 'recovered')",
            (time.time(), task_id),
        )
        mem.db.commit()
    secure.audit("bg_task_cancelled", {"id": task_id})
    task = get_task(mem, task_id)
    if not task:
        raise ValueError(f"Unknown background task '{task_id}'.")
    return task


def delete_task(mem, task_id: str) -> bool:
    init_db(mem)
    with mem._lock:
        cur = mem.db.execute("DELETE FROM bg_tasks WHERE id=?", (task_id,))
        mem.db.commit()
    return cur.rowcount > 0


def _save_progress(mem, task_id: str, *, state: str, current_step: int, checkpoint: dict, results: list, error: str = "") -> None:
    with mem._lock:
        mem.db.execute(
            "UPDATE bg_tasks SET state=?, current_step=?, checkpoint_json=?, results_json=?, error=?, updated_at=? WHERE id=?",
            (state, current_step, json.dumps(checkpoint), json.dumps(results), error[:500], time.time(), task_id),
        )
        mem.db.commit()


def run_parallel_steps(ctx: skills.Context, steps: list[dict], *, cancel_event: threading.Event | None = None, max_workers: int = 3) -> list[dict]:
    """Execute independent read-only T0 steps concurrently with policy enforcement and outcome verification."""
    def _exec(idx: int, step: dict) -> tuple[int, dict]:
        if cancel_event is not None and cancel_event.is_set():
            return idx, {"step": idx, "tool": step["tool"], "output": "Stopped by the user.", "verification": {"verified": False, "reason": "Cancelled"}}
        tool = step["tool"]
        tier = skills.risk_tier(tool)
        if tier != "T0":
            secure.audit("bg_parallel_blocked", {"tool": tool, "tier": tier})
            return idx, {"step": idx, "tool": tool, "output": f"Blocked: parallel execution only permits T0 tools (got {tier}).", "verification": {"verified": False, "reason": "Non-T0 blocked"}}
        step_ctx = skills.Context(ctx.cfg, ctx.memory)
        step_ctx.cancelled = cancel_event
        out = skills.run(step_ctx, tool, step.get("args") or {})
        ver = verify_step_outcome(tool, out)
        return idx, {"step": idx, "tool": tool, "output": secure.redact(out[:4000]), "verification": ver}

    ordered: dict[int, dict] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, 4))) as pool:
        futs = [pool.submit(_exec, i, s) for i, s in enumerate(steps)]
        for fut in as_completed(futs):
            idx, res = fut.result()
            ordered[idx] = res
    return [ordered[i] for i in range(len(steps))]


def execute_task(mem, ctx: skills.Context, task_id: str) -> dict:
    """Run or resume a background task from its persisted checkpoint."""
    task = get_task(mem, task_id)
    if not task:
        raise ValueError(f"Unknown background task '{task_id}'.")
    if task["state"] in ("completed", "cancelled"):
        return task
    if ctx.cfg.get("lockdown"):
        raise ValueError("Background tasks cannot start during Lockdown.")

    cancel_ev = threading.Event()
    with _LOCK:
        _ACTIVE_CANCELS[task_id] = cancel_ev

    steps = task["steps"]
    results = list(task["results"])
    start_idx = int(task["current_step"])
    _save_progress(mem, task_id, state="running", current_step=start_idx, checkpoint=task["checkpoint"], results=results)

    try:
        if task["kind"] == "parallel" and start_idx == 0:
            par_results = run_parallel_steps(ctx, steps, cancel_event=cancel_ev)
            if cancel_ev.is_set():
                _save_progress(mem, task_id, state="cancelled", current_step=0, checkpoint={"mode": "parallel"}, results=par_results)
            else:
                all_ok = all(r["verification"]["verified"] for r in par_results)
                _save_progress(
                    mem, task_id,
                    state="completed" if all_ok else "failed",
                    current_step=len(steps),
                    checkpoint={"completed_steps": len(steps), "mode": "parallel"},
                    results=par_results,
                    error="" if all_ok else "One or more parallel steps failed verification.",
                )
            return get_task(mem, task_id)

        for idx in range(start_idx, len(steps)):
            if cancel_ev.is_set() or (ctx.cancelled is not None and ctx.cancelled.is_set()):
                _save_progress(mem, task_id, state="cancelled", current_step=idx, checkpoint={"stopped_at": idx}, results=results)
                return get_task(mem, task_id)

            step = steps[idx]
            tool = step["tool"]
            tier = skills.risk_tier(tool)
            if tier not in ALLOWED_BG_TIERS:
                secure.audit("bg_task_blocked", {"id": task_id, "tool": tool, "tier": tier})
                _save_progress(mem, task_id, state="failed", current_step=idx, checkpoint={"blocked_step": idx}, results=results,
                               error=f"Blocked risky tool '{tool}' ({tier}).")
                return get_task(mem, task_id)

            step_ctx = skills.Context(ctx.cfg, ctx.memory)
            step_ctx.cancelled = cancel_ev
            output = skills.run(step_ctx, tool, step.get("args") or {})
            ver = verify_step_outcome(tool, output)
            results.append({
                "step": idx,
                "tool": tool,
                "tier": tier,
                "output": secure.redact(output[:4000]),
                "verification": ver,
                "ts": round(time.time(), 2),
            })
            ckpt = {"last_completed_step": idx, "last_tool": tool, "verified": ver["verified"]}
            if not ver["verified"]:
                _save_progress(mem, task_id, state="failed", current_step=idx + 1, checkpoint=ckpt, results=results, error=ver["reason"])
                return get_task(mem, task_id)
            _save_progress(mem, task_id, state="running", current_step=idx + 1, checkpoint=ckpt, results=results)

        _save_progress(mem, task_id, state="completed", current_step=len(steps), checkpoint={"completed_steps": len(steps)}, results=results)
        secure.audit("bg_task_completed", {"id": task_id, "steps": len(steps)})
        return get_task(mem, task_id)
    finally:
        with _LOCK:
            _ACTIVE_CANCELS.pop(task_id, None)
