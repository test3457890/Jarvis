"""Reviewable Memory Extraction & Daily Summary generator.

Extracts candidate lasting facts from recent conversation text without auto-saving them.
Secrets are redacted before presentation; candidates are saved ONLY upon explicit user approval.
"""
import datetime as dt
import re
import secrets

from . import bgtasks, monitors, secure

_PATTERNS = [
    ("preference", re.compile(r"\b(?:i prefer|i like|my favorite|my favourite|please always|call me)\s+([^.!?\n]{4,140})", re.I)),
    ("project", re.compile(r"\b(?:i am working on|i'm working on|our project is|my project is)\s+([^.!?\n]{4,140})", re.I)),
    ("schedule", re.compile(r"\b(?:my (?:meeting|class|standup|deadline) is|every (?:monday|tuesday|wednesday|thursday|friday|saturday|sunday))\s+([^.!?\n]{4,140})", re.I)),
]


def extract_candidates(text: str, *, existing_facts: list[str] | None = None) -> list[dict]:
    """Return deduplicated, redacted candidate memories for human review."""
    clean = secure.redact(str(text or ""))
    existing_lower = {str(f).strip().lower() for f in (existing_facts or [])}
    seen = set()
    candidates = []
    for category, pattern in _PATTERNS:
        for match in pattern.finditer(clean):
            phrase = match.group(0).strip().rstrip(".,;:")
            norm = phrase.lower()
            if norm in seen or any(norm in ex or ex in norm for ex in existing_lower):
                continue
            seen.add(norm)
            candidates.append({
                "id": f"cand-{secrets.token_hex(4)}",
                "category": category,
                "text": phrase[:240],
                "approved": False,
            })
            if len(candidates) >= 10:
                return candidates
    return candidates


def approve_candidate(mem, text: str, *, project: str = "") -> str:
    """Explicitly save a user-approved candidate fact into long-term memory."""
    clean = secure.redact(str(text or "").strip())
    if not clean or len(clean) < 4:
        raise ValueError("Candidate fact is too short.")
    mem.remember(clean, origin="reviewed_extraction", project=project)
    secure.audit("memory_candidate_approved", {"chars": len(clean), "project": project})
    return clean


def daily_summary(mem, cfg: dict) -> dict:
    """Build an authentic daily summary from local SQLite memory, tasks, monitors, and background runs."""
    today = dt.date.today().isoformat()
    reminders = mem.pending_reminders()
    tasks = bgtasks.list_tasks(mem, limit=10)
    mons = monitors.list_monitors(mem)
    triggered = [m for m in mons if m.get("trigger_count", 0) > 0]
    recent_msgs = mem.recent_messages(limit=20)
    return {
        "date": today,
        "reminders_pending": len(reminders),
        "background_tasks": {
            "total": len(tasks),
            "completed": sum(1 for t in tasks if t["state"] == "completed"),
            "recovered": sum(1 for t in tasks if t["state"] == "recovered"),
            "failed": sum(1 for t in tasks if t["state"] == "failed"),
        },
        "monitors": {
            "total": len(mons),
            "enabled": sum(1 for m in mons if m["enabled"]),
            "triggered_ever": len(triggered),
        },
        "recent_messages_count": len(recent_msgs),
        "privacy_mode": cfg.get("privacy_mode", "hybrid"),
    }
