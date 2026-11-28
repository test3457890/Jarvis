"""Workflow Recording, Editable Macros & Policy-Enforced Playback.

Security rules:
- Every macro step is validated against registered skills.
- Dry-run preview inspects every step's risk tier (T0-T3) and permission status before replay.
- Replay executes strictly through skills.run(). If Lockdown is active or any step requires
  user confirmation, playback halts cleanly and surfaces the confirmation preview rather than
  bypassing approvals.
"""
import json
import secrets
import threading
import time

from . import secure, skills

_REC_LOCK = threading.Lock()
_RECORDING: dict | None = None


def init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS macros (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                steps_json TEXT NOT NULL,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                run_count INTEGER NOT NULL DEFAULT 0,
                last_run REAL
            )"""
        )
        mem.db.commit()


def _validate_steps(steps: list[dict]) -> list[dict]:
    if not isinstance(steps, list) or not 1 <= len(steps) <= 30:
        raise ValueError("A macro must contain between 1 and 30 steps.")
    clean = []
    for idx, step in enumerate(steps):
        if not isinstance(step, dict) or not isinstance(step.get("tool"), str) or not step["tool"].strip():
            raise ValueError(f"Step {idx + 1} must specify a tool name.")
        tool = step["tool"].strip()
        if tool not in skills.SKILLS:
            raise ValueError(f"Unknown tool '{tool}' in step {idx + 1}.")
        args = step.get("args") or {}
        if not isinstance(args, dict):
            raise ValueError(f"Step {idx + 1} args must be a JSON object.")
        clean.append({"tool": tool, "args": args})
    return clean


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "description": row[2],
        "steps": json.loads(row[3]),
        "created_at": row[4],
        "updated_at": row[5],
        "run_count": row[6],
        "last_run": row[7],
    }


def list_macros(mem) -> list[dict]:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, description, steps_json, created_at, updated_at, run_count, last_run FROM macros ORDER BY updated_at DESC"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def get_macro(mem, macro_id: str) -> dict | None:
    init_db(mem)
    with mem._lock:
        row = mem.db.execute(
            "SELECT id, name, description, steps_json, created_at, updated_at, run_count, last_run FROM macros WHERE id=?",
            (macro_id,),
        ).fetchone()
    return _row_to_dict(row) if row else None


def save_macro(mem, *, name: str, steps: list[dict], description: str = "", macro_id: str | None = None) -> dict:
    init_db(mem)
    clean_name = str(name or "").strip()[:80]
    if not clean_name:
        raise ValueError("Macro name is required.")
    clean_steps = _validate_steps(steps)
    now = time.time()
    mid = macro_id or f"mac-{secrets.token_hex(4)}"
    with mem._lock:
        existing = mem.db.execute("SELECT id FROM macros WHERE id=?", (mid,)).fetchone()
        if existing:
            mem.db.execute(
                "UPDATE macros SET name=?, description=?, steps_json=?, updated_at=? WHERE id=?",
                (clean_name, str(description or "")[:240], json.dumps(clean_steps), now, mid),
            )
        else:
            mem.db.execute(
                "INSERT INTO macros (id, name, description, steps_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
                (mid, clean_name, str(description or "")[:240], json.dumps(clean_steps), now, now),
            )
        mem.db.commit()
    secure.audit("macro_saved", {"id": mid, "steps": len(clean_steps)})
    return get_macro(mem, mid)


def delete_macro(mem, macro_id: str) -> bool:
    init_db(mem)
    with mem._lock:
        cur = mem.db.execute("DELETE FROM macros WHERE id=?", (macro_id,))
        mem.db.commit()
    return cur.rowcount > 0


# ---- Interactive Recording
def start_recording(name: str, description: str = "") -> dict:
    global _RECORDING
    clean_name = str(name or "").strip()[:80]
    if not clean_name:
        raise ValueError("Provide a name for the recorded macro.")
    with _REC_LOCK:
        _RECORDING = {"name": clean_name, "description": str(description or "")[:240], "steps": [], "started_at": time.time()}
        return dict(_RECORDING)


def record_step(tool: str, args: dict | None = None) -> dict:
    with _REC_LOCK:
        if _RECORDING is None:
            raise ValueError("No macro recording is currently active.")
        if tool not in skills.SKILLS:
            raise ValueError(f"Unknown tool '{tool}'.")
        _RECORDING["steps"].append({"tool": tool, "args": dict(args or {})})
        return {"name": _RECORDING["name"], "steps_recorded": len(_RECORDING["steps"])}


def recording_status() -> dict:
    with _REC_LOCK:
        if _RECORDING is None:
            return {"active": False, "steps_recorded": 0}
        return {"active": True, "name": _RECORDING["name"], "steps_recorded": len(_RECORDING["steps"])}


def stop_recording(mem, *, save: bool = True) -> dict:
    global _RECORDING
    with _REC_LOCK:
        rec = _RECORDING
        _RECORDING = None
    if rec is None:
        raise ValueError("No macro recording is active.")
    if not save or not rec["steps"]:
        return {"saved": False, "steps_recorded": len(rec["steps"])}
    macro = save_macro(mem, name=rec["name"], description=rec["description"], steps=rec["steps"])
    return {"saved": True, "macro": macro}


# ---- Preview & Replay
def preview_macro(mem, ctx: skills.Context, macro_id: str) -> dict:
    macro = get_macro(mem, macro_id)
    if not macro:
        raise ValueError(f"Unknown macro '{macro_id}'.")
    step_previews = [skills.dry_run(ctx, s["tool"], s.get("args") or {}) for s in macro["steps"]]
    return {
        "id": macro["id"],
        "name": macro["name"],
        "steps": step_previews,
        "all_allowed": all(p["ok"] for p in step_previews),
        "needs_confirmation": any(p.get("requires_confirmation") for p in step_previews),
    }


def replay_macro(mem, ctx: skills.Context, macro_id: str) -> dict:
    """Replay a macro strictly through skills.run(), halting if any step needs confirmation or is blocked."""
    macro = get_macro(mem, macro_id)
    if not macro:
        raise ValueError(f"Unknown macro '{macro_id}'.")
    if ctx.cfg.get("lockdown"):
        raise ValueError("Macros cannot run while Lockdown is active.")
    outputs = []
    halted_for_confirmation = False
    for idx, step in enumerate(macro["steps"]):
        out = skills.run(ctx, step["tool"], step.get("args") or {})
        outputs.append({"step": idx, "tool": step["tool"], "tier": skills.risk_tier(step["tool"]), "output": secure.redact(out[:2000])})
        if ctx.pending is not None:
            halted_for_confirmation = True
            break
    with mem._lock:
        mem.db.execute(
            "UPDATE macros SET run_count=run_count+1, last_run=? WHERE id=?",
            (time.time(), macro_id),
        )
        mem.db.commit()
    secure.audit("macro_replayed", {"id": macro_id, "steps_run": len(outputs), "halted_for_confirmation": halted_for_confirmation})
    return {
        "id": macro["id"],
        "name": macro["name"],
        "steps_run": len(outputs),
        "halted_for_confirmation": halted_for_confirmation,
        "pending": {"text": ctx.pending["preview"], "id": ctx.pending["id"]} if ctx.pending else None,
        "outputs": outputs,
    }
