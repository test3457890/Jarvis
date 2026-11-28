"""Unified Undo Journal and Stale-Target File Fingerprint Guard.

Provides:
1. Stale-target protection: captures file stat() metadata when preparing a risky file
   operation and verifies the target has not changed before executing after user approval.
2. Unified Undo Journal: bounded, redacted record of reversible actions (code patches,
   file jobs, memory edits, settings changes) with explicit undo hints and state tracking.
"""
from collections import deque
import secrets
import threading
import time
from pathlib import Path

from . import secure


def file_fingerprint(path: str | Path) -> dict:
    """Capture a lightweight stat() fingerprint for stale-target detection."""
    p = Path(path)
    try:
        st = p.lstat()
        return {
            "path": str(p),
            "exists": True,
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
            "is_symlink": p.is_symlink(),
        }
    except OSError:
        return {
            "path": str(p),
            "exists": False,
            "size": None,
            "mtime_ns": None,
            "is_symlink": False,
        }


def verify_fingerprint(path: str | Path, expected: dict) -> tuple[bool, str]:
    """Verify a target file has not changed since approval preview was generated."""
    current = file_fingerprint(path)
    if current["is_symlink"] != expected.get("is_symlink"):
        return False, "Target changed to or from a symbolic link while awaiting approval."
    if current["exists"] != expected.get("exists"):
        return False, "Target was created or deleted while awaiting approval."
    if current["exists"]:
        if current["size"] != expected.get("size") or current["mtime_ns"] != expected.get("mtime_ns"):
            return False, "Target file was modified while awaiting approval. Re-preview before applying."
    return True, "ok"


class UndoJournal:
    """Thread-safe bounded journal of reversible Jarvis operations."""

    def __init__(self, maxlen: int = 100):
        self._lock = threading.Lock()
        self._entries: deque[dict] = deque(maxlen=maxlen)

    def record(
        self,
        *,
        category: str,
        tool: str,
        summary: str,
        target: str = "",
        undo_hint: str = "",
        reversible: bool = True,
    ) -> dict:
        entry = {
            "id": secrets.token_hex(6),
            "ts": round(time.time(), 2),
            "category": str(category or "general")[:40],
            "tool": str(tool or "")[:80],
            "summary": secure.redact(str(summary or "")[:240]),
            "target": secure.redact(str(target or "")[:240]),
            "undo_hint": secure.redact(str(undo_hint or "")[:160]),
            "reversible": bool(reversible),
            "undone": False,
        }
        with self._lock:
            self._entries.appendleft(entry)
        secure.audit("undo_journal_record", {"id": entry["id"], "category": entry["category"], "tool": entry["tool"]})
        return dict(entry)

    def mark_undone(self, entry_id: str) -> dict | None:
        with self._lock:
            for item in self._entries:
                if item["id"] == entry_id:
                    item["undone"] = True
                    secure.audit("undo_journal_undone", {"id": entry_id, "tool": item["tool"]})
                    return dict(item)
        return None

    def list_entries(self, limit: int = 30) -> list[dict]:
        with self._lock:
            return [dict(e) for e in list(self._entries)[:max(1, min(limit, 100))]]

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


JOURNAL = UndoJournal()
