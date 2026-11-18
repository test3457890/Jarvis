"""Long-term memory: conversation diary, remembered facts and reminders, all in a
local SQLite file. Sensitive data (card numbers, SSNs, passwords) is redacted
before anything is saved."""
import json
import math
import re
import sqlite3
import threading
import time
from typing import Callable, Optional

from .config import APP_DIR

DB_PATH = APP_DIR / "memory.db"

_REDACTIONS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[card number removed]"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN removed]"),
    (re.compile(r"(?i)\b(password|passcode|pin|api[_ ]?key|token|secret)\b(\s*(is|=|:)\s*)\S+"),
     r"\1\2[removed]"),
]


def redact(text: str) -> str:
    for pattern, repl in _REDACTIONS:
        text = pattern.sub(repl, text)
    return text


def _cosine(a, b) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


_WORD = re.compile(r"[a-z0-9']+")
_STOP = set("a an the is are was were i me my you your to of and or in on at for it this that "
            "what who when where how do does did be with about please jarvis".split())


def _words(text: str) -> set:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


class Memory:
    def __init__(self, embed: Optional[Callable[[str], Optional[list]]] = None):
        APP_DIR.mkdir(parents=True, exist_ok=True)
        self.embed = embed
        self._lock = threading.Lock()
        self.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, ts REAL, role TEXT, content TEXT);
            CREATE TABLE IF NOT EXISTS facts (
                id INTEGER PRIMARY KEY, ts REAL, text TEXT, embedding TEXT);
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY, due REAL, text TEXT, done INTEGER DEFAULT 0);
            """
        )
        self.db.commit()

    # ---------- diary ----------
    def log(self, role: str, content: str) -> None:
        with self._lock:
            self.db.execute("INSERT INTO messages(ts, role, content) VALUES (?,?,?)",
                            (time.time(), role, redact(content)))
            self.db.commit()

    def recent_messages(self, limit: int) -> list:
        with self._lock:
            rows = self.db.execute(
                "SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def search_diary(self, query: str, limit: int = 8) -> list:
        terms = _words(query)
        if not terms:
            return []
        with self._lock:
            rows = self.db.execute(
                "SELECT ts, role, content FROM messages ORDER BY id DESC LIMIT 3000"
            ).fetchall()
        scored = []
        for ts, role, content in rows:
            overlap = len(terms & _words(content))
            if overlap:
                scored.append((overlap, ts, role, content))
        scored.sort(key=lambda r: (-r[0], -r[1]))
        return [
            f"[{time.strftime('%b %d %H:%M', time.localtime(ts))}] {role}: {content[:300]}"
            for _, ts, role, content in scored[:limit]
        ]

    # ---------- facts ----------
    def remember(self, text: str) -> int:
        text = redact(text.strip())
        vec = self.embed(text) if self.embed else None
        with self._lock:
            cur = self.db.execute("INSERT INTO facts(ts, text, embedding) VALUES (?,?,?)",
                                  (time.time(), text, json.dumps(vec) if vec else None))
            self.db.commit()
            return cur.lastrowid

    def all_facts(self) -> list:
        with self._lock:
            return self.db.execute("SELECT id, text FROM facts ORDER BY id").fetchall()

    def edit_fact(self, fact_id: int, text: str) -> bool:
        if not isinstance(text, str) or not text.strip() or len(text) > 4000:
            raise ValueError("Enter a memory between 1 and 4000 characters.")
        with self._lock, self.db:
            result = self.db.execute("UPDATE facts SET text=?, embedding=NULL WHERE id=?",
                                     (redact(text.strip()), fact_id))
            return result.rowcount == 1

    def delete_fact(self, fact_id: int) -> bool:
        with self._lock, self.db:
            result = self.db.execute("DELETE FROM facts WHERE id=?", (fact_id,))
            return result.rowcount == 1

    def forget(self, query: str) -> list:
        matches = [(i, t) for i, t in self.all_facts() if query.lower() in t.lower()]
        with self._lock:
            for i, _ in matches:
                self.db.execute("DELETE FROM facts WHERE id=?", (i,))
            self.db.commit()
        return [t for _, t in matches]

    def recall(self, query: str, k: int = 5) -> list:
        with self._lock:
            rows = self.db.execute("SELECT text, embedding FROM facts").fetchall()
        if not rows:
            return []
        qvec = self.embed(query) if self.embed else None
        q_words = _words(query)
        scored = []
        for text, emb in rows:
            score = len(q_words & _words(text)) * 0.15
            if qvec and emb:
                score += _cosine(qvec, json.loads(emb))
            scored.append((score, text))
        scored.sort(reverse=True)
        threshold = 0.45 if qvec else 0.15
        return [t for s, t in scored[:k] if s >= threshold]

    # ---------- reminders ----------
    def add_reminder(self, due: float, text: str) -> int:
        with self._lock:
            cur = self.db.execute("INSERT INTO reminders(due, text) VALUES (?,?)", (due, text))
            self.db.commit()
            return cur.lastrowid

    def pending_reminders(self) -> list:
        with self._lock:
            return self.db.execute(
                "SELECT id, due, text FROM reminders WHERE done=0 ORDER BY due").fetchall()

    def pop_due_reminders(self) -> list:
        now = time.time()
        with self._lock:
            rows = self.db.execute(
                "SELECT id, text FROM reminders WHERE done=0 AND due<=?", (now,)).fetchall()
            for rid, _ in rows:
                self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (rid,))
            self.db.commit()
        return [t for _, t in rows]

    def cancel_reminder(self, query: str) -> list:
        hits = [(i, t) for i, _, t in self.pending_reminders() if query.lower() in t.lower()]
        with self._lock:
            for i, _ in hits:
                self.db.execute("UPDATE reminders SET done=1 WHERE id=?", (i,))
            self.db.commit()
        return [t for _, t in hits]
