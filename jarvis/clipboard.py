"""Clipboard History Manager with pinning, search, and automatic secret redaction.

All stored clipboard entries are redacted via secure.redact() before persistence and
fenced as untrusted content when returned to the LLM.
"""
import secrets
import time

from . import secure
from .skills import skill

MAX_ENTRIES = 100
MAX_ENTRY_CHARS = 8000


def init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS clipboard_history (
                id TEXT PRIMARY KEY,
                text TEXT NOT NULL,
                pinned INTEGER NOT NULL DEFAULT 0,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def capture(mem, text: str, *, source: str = "manual") -> dict:
    init_db(mem)
    clean = secure.redact(str(text or "").strip())[:MAX_ENTRY_CHARS]
    if not clean:
        raise ValueError("Clipboard text is empty.")
    cid = f"clip-{secrets.token_hex(4)}"
    now = time.time()
    with mem._lock:
        mem.db.execute(
            "INSERT INTO clipboard_history (id, text, pinned, source, created_at) VALUES (?, ?, 0, ?, ?)",
            (cid, clean, str(source or "manual")[:40], now),
        )
        # Keep bounded size by trimming oldest unpinned entries beyond MAX_ENTRIES
        mem.db.execute(
            """DELETE FROM clipboard_history WHERE pinned=0 AND id NOT IN (
                   SELECT id FROM clipboard_history ORDER BY pinned DESC, created_at DESC LIMIT ?
               )""",
            (MAX_ENTRIES,),
        )
        mem.db.commit()
    return {"id": cid, "text": clean, "pinned": False, "source": source, "created_at": now}


def list_entries(mem, *, limit: int = 30, pinned_only: bool = False) -> list[dict]:
    init_db(mem)
    q = "SELECT id, text, pinned, source, created_at FROM clipboard_history"
    if pinned_only:
        q += " WHERE pinned=1"
    q += " ORDER BY pinned DESC, created_at DESC LIMIT ?"
    with mem._lock:
        rows = mem.db.execute(q, (max(1, min(limit, MAX_ENTRIES)),)).fetchall()
    return [{"id": r[0], "text": r[1], "pinned": bool(r[2]), "source": r[3], "created_at": r[4]} for r in rows]


def search_entries(mem, query: str, *, limit: int = 20) -> list[dict]:
    init_db(mem)
    needle = str(query or "").strip().lower()
    if not needle:
        return list_entries(mem, limit=limit)
    rows = list_entries(mem, limit=MAX_ENTRIES)
    return [r for r in rows if needle in r["text"].lower()][:max(1, min(limit, 50))]


def set_pinned(mem, clip_id: str, pinned: bool) -> list[dict]:
    init_db(mem)
    with mem._lock:
        mem.db.execute("UPDATE clipboard_history SET pinned=? WHERE id=?", (1 if pinned else 0, clip_id))
        mem.db.commit()
    return list_entries(mem)


def delete_entry(mem, clip_id: str) -> list[dict]:
    init_db(mem)
    with mem._lock:
        mem.db.execute("DELETE FROM clipboard_history WHERE id=?", (clip_id,))
        mem.db.commit()
    return list_entries(mem)


@skill("List recent saved clipboard history entries (redacted).", untrusted=True)
def clipboard_history_list(ctx):
    rows = list_entries(ctx.memory, limit=15)
    if not rows:
        return "Clipboard history is empty."
    return "\n".join(f"[{r['id']}{'*' if r['pinned'] else ''}] {r['text'][:120]}" for r in rows)


@skill("Search saved clipboard history.", params={"query": ("string", "Words to search", True)}, untrusted=True)
def clipboard_history_search(ctx, query):
    rows = search_entries(ctx.memory, query, limit=10)
    if not rows:
        return "No matching clipboard entries."
    return "\n".join(f"[{r['id']}] {r['text'][:120]}" for r in rows)
