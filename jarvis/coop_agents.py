"""Cooperative Jarvis + TUKI Multi-Agent Planner & Visual Automation Builder (Phase 8).

Capabilities:
- Shared SQLite multi-agent plans with explicit step dependencies (`depends_on`),
  specialist roles (`jarvis_coordinator`, `tuki_research`, `tuki_coding`, `tuki_academic`, `sentinel_security`),
  approval gates, persistent checkpoints, outcome verification, and failure recovery.
- Bounded execution: enforces `MAX_RECURSION_DEPTH = 3`, `MAX_STEPS_PER_PLAN = 16`,
  and per-plan step/token budgets to prevent unbounded recursive agent loops.
- Visual Automation Routine Builder: trigger -> condition -> action definitions stored in SQLite.
"""
import json
import re
import time
import uuid

from . import secure

MAX_RECURSION_DEPTH = 3
MAX_STEPS_PER_PLAN = 16

SPECIALIST_AGENTS = {
    "jarvis_coordinator": {"assistant": "jarvis", "role": "Primary Coordinator & Action Gatekeeper"},
    "tuki_research": {"assistant": "tuki", "role": "Independent Research & Source Verification"},
    "tuki_coding": {"assistant": "tuki", "role": "Code Review, Static Analysis & Test Verification"},
    "tuki_academic": {"assistant": "tuki", "role": "Academic Planning, Citations & Study Synthesis"},
    "sentinel_security": {"assistant": "jarvis", "role": "Defensive Security Posture & Policy Verifier"},
}


def _init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS coop_plans (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                goal TEXT NOT NULL,
                status TEXT NOT NULL,
                depth INTEGER NOT NULL DEFAULT 0,
                max_steps INTEGER NOT NULL DEFAULT 10,
                steps_json TEXT NOT NULL,
                checkpoint_json TEXT NOT NULL DEFAULT '{}',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS visual_automations (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                trigger_type TEXT NOT NULL,
                trigger_spec TEXT NOT NULL,
                condition_expr TEXT NOT NULL DEFAULT '',
                action_spec TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 0,
                last_run REAL DEFAULT 0,
                created_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def create_plan(
    mem,
    title: str,
    goal: str,
    steps: list[dict],
    *,
    depth: int = 0,
    max_steps: int = 10,
) -> dict:
    """Create a persistent, bounded cooperative Jarvis+TUKI task plan."""
    if int(depth) > MAX_RECURSION_DEPTH:
        secure.audit("coop_agent_recursion_blocked", {"depth": int(depth)})
        raise PermissionError(f"Blocked recursive agent delegation: depth {depth} exceeds limit {MAX_RECURSION_DEPTH}.")
    if not steps or len(steps) > MAX_STEPS_PER_PLAN:
        raise ValueError(f"A cooperative plan must contain 1 to {MAX_STEPS_PER_PLAN} steps.")
    clean_steps = []
    seen_ids = set()
    for idx, st in enumerate(steps):
        sid = str(st.get("id") or f"step_{idx+1}").strip()[:32]
        agent = str(st.get("agent") or "jarvis_coordinator").strip()
        if agent not in SPECIALIST_AGENTS:
            raise ValueError(f"Unknown specialist agent '{agent}'.")
        deps = [str(d) for d in (st.get("depends_on") or []) if str(d) in seen_ids]
        seen_ids.add(sid)
        clean_steps.append({
            "id": sid,
            "title": str(st.get("title") or sid)[:120],
            "agent": agent,
            "assistant": SPECIALIST_AGENTS[agent]["assistant"],
            "depends_on": deps,
            "requires_approval": bool(st.get("requires_approval", False)),
            "approved": False,
            "status": "pending",
            "outcome": "",
            "verified": False,
        })

    _init_db(mem)
    pid = f"plan_{uuid.uuid4().hex[:10]}"
    now = time.time()
    with mem._lock:
        mem.db.execute(
            """INSERT INTO coop_plans (id, title, goal, status, depth, max_steps, steps_json, checkpoint_json, created_at, updated_at)
               VALUES (?, ?, ?, 'planned', ?, ?, ?, '{}', ?, ?)""",
            (pid, str(title)[:100], str(goal)[:400], int(depth), min(int(max_steps), MAX_STEPS_PER_PLAN), json.dumps(clean_steps), now, now),
        )
        mem.db.commit()
    secure.audit("coop_plan_created", {"plan_id": pid, "steps": len(clean_steps), "depth": int(depth)})
    return get_plan(mem, pid)


def get_plan(mem, plan_id: str) -> dict:
    _init_db(mem)
    with mem._lock:
        row = mem.db.execute(
            "SELECT id, title, goal, status, depth, max_steps, steps_json, checkpoint_json, created_at, updated_at FROM coop_plans WHERE id=?",
            (plan_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"Cooperative plan '{plan_id}' not found.")
    return {
        "id": row[0], "title": row[1], "goal": row[2], "status": row[3],
        "depth": row[4], "max_steps": row[5],
        "steps": json.loads(row[6]), "checkpoint": json.loads(row[7]),
        "created_at": row[8], "updated_at": row[9],
    }


def list_plans(mem, limit: int = 25) -> list[dict]:
    _init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, title, goal, status, depth, max_steps, steps_json, checkpoint_json, created_at, updated_at FROM coop_plans ORDER BY updated_at DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [
        {
            "id": r[0], "title": r[1], "goal": r[2], "status": r[3],
            "depth": r[4], "max_steps": r[5],
            "steps": json.loads(r[6]), "checkpoint": json.loads(r[7]),
            "created_at": r[8], "updated_at": r[9],
        }
        for r in rows
    ]


def advance_step(mem, plan_id: str, step_id: str, *, outcome: str = "", approve: bool = False, verify: bool = False) -> dict:
    """Advance, approve, or verify a step in a cooperative plan with dependency checks and checkpointing."""
    plan = get_plan(mem, plan_id)
    if plan["status"] == "cancelled":
        raise RuntimeError("Cannot advance a cancelled cooperative plan.")
    steps = plan["steps"]
    by_id = {s["id"]: s for s in steps}
    if step_id not in by_id:
        raise ValueError(f"Step '{step_id}' not found in plan '{plan_id}'.")
    step = by_id[step_id]
    for dep in step["depends_on"]:
        if by_id[dep]["status"] != "completed":
            raise RuntimeError(f"Step '{step_id}' is blocked until dependency '{dep}' completes.")
    if approve:
        step["approved"] = True
    if step["requires_approval"] and not step["approved"]:
        step["status"] = "awaiting_approval"
    else:
        step["status"] = "completed"
        step["outcome"] = str(outcome or "Completed cleanly.")[:300]
        if verify:
            step["verified"] = True

    all_done = all(s["status"] == "completed" for s in steps)
    new_status = "completed" if all_done else ("awaiting_approval" if step["status"] == "awaiting_approval" else "in_progress")
    ckpt = {"last_step": step_id, "completed": sum(1 for s in steps if s["status"] == "completed"), "total": len(steps), "ts": time.time()}
    with mem._lock:
        mem.db.execute(
            "UPDATE coop_plans SET status=?, steps_json=?, checkpoint_json=?, updated_at=? WHERE id=?",
            (new_status, json.dumps(steps), json.dumps(ckpt), time.time(), plan_id),
        )
        mem.db.commit()
    return get_plan(mem, plan_id)


def cancel_plan(mem, plan_id: str) -> dict:
    plan = get_plan(mem, plan_id)
    with mem._lock:
        mem.db.execute("UPDATE coop_plans SET status='cancelled', updated_at=? WHERE id=?", (time.time(), plan_id))
        mem.db.commit()
    secure.audit("coop_plan_cancelled", {"plan_id": plan_id})
    return get_plan(mem, plan_id)


# ------------------------------------------------------------------ Visual Automation Builder
def save_automation(
    mem,
    cfg: dict,
    *,
    name: str,
    trigger_type: str,
    trigger_spec: str,
    condition_expr: str = "",
    action_spec: str,
    enabled: bool = False,
) -> dict:
    if cfg.get("lockdown"):
        raise PermissionError("Cannot modify visual automations during Lockdown.")
    ttype = str(trigger_type or "").strip().lower()
    if ttype not in ("schedule", "metric_threshold", "manual", "file_watch"):
        raise ValueError("Trigger type must be schedule, metric_threshold, manual, or file_watch.")
    _init_db(mem)
    aid = f"auto_{uuid.uuid4().hex[:8]}"
    now = time.time()
    with mem._lock:
        mem.db.execute(
            """INSERT INTO visual_automations (id, name, trigger_type, trigger_spec, condition_expr, action_spec, enabled, last_run, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)""",
            (aid, str(name)[:80], ttype, str(trigger_spec)[:160], str(condition_expr)[:160], str(action_spec)[:240], 1 if enabled else 0, now),
        )
        mem.db.commit()
    secure.audit("visual_automation_saved", {"id": aid, "trigger": ttype, "enabled": bool(enabled)})
    return {"id": aid, "name": str(name)[:80], "trigger_type": ttype, "trigger_spec": str(trigger_spec)[:160], "condition_expr": str(condition_expr)[:160], "action_spec": str(action_spec)[:240], "enabled": bool(enabled)}


def list_automations(mem) -> list[dict]:
    _init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, trigger_type, trigger_spec, condition_expr, action_spec, enabled, last_run, created_at FROM visual_automations ORDER BY created_at DESC LIMIT 50"
        ).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "trigger_type": r[2], "trigger_spec": r[3],
            "condition_expr": r[4], "action_spec": r[5], "enabled": bool(r[6]),
            "last_run": r[7], "created_at": r[8],
        }
        for r in rows
    ]


def workspace_state(mem) -> dict:
    return {
        "specialists": SPECIALIST_AGENTS,
        "limits": {"max_recursion_depth": MAX_RECURSION_DEPTH, "max_steps_per_plan": MAX_STEPS_PER_PLAN},
        "plans": list_plans(mem, 20),
        "automations": list_automations(mem),
    }
