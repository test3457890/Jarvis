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
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, project TEXT NOT NULL DEFAULT '',
                created REAL NOT NULL, updated REAL NOT NULL, summary TEXT NOT NULL DEFAULT '');
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, description TEXT NOT NULL DEFAULT '',
                code_dir TEXT NOT NULL DEFAULT '', document_folders TEXT NOT NULL DEFAULT '[]',
                created REAL NOT NULL);
            """
        )
        fact_columns = {row[1] for row in self.db.execute('PRAGMA table_info(facts)')}
        if 'expires' not in fact_columns:
            self.db.execute('ALTER TABLE facts ADD COLUMN expires REAL')
        if 'origin' not in fact_columns:
            self.db.execute("ALTER TABLE facts ADD COLUMN origin TEXT DEFAULT 'Saved before source tracking'")
        if 'project' not in fact_columns:
            self.db.execute("ALTER TABLE facts ADD COLUMN project TEXT NOT NULL DEFAULT ''")
        msg_columns = {row[1] for row in self.db.execute('PRAGMA table_info(messages)')}
        if 'conversation_id' not in msg_columns:
            self.db.execute("ALTER TABLE messages ADD COLUMN conversation_id TEXT NOT NULL DEFAULT 'default'")
        self.db.commit()

    # ---------- diary & conversations ----------
    def log(self, role: str, content: str, conversation_id: str = "default") -> None:
        now = time.time()
        cid = (conversation_id or "default")[:64]
        with self._lock:
            self.db.execute(
                "INSERT INTO messages(ts, role, content, conversation_id) VALUES (?,?,?,?)",
                (now, role, redact(content), cid),
            )
            self.db.execute(
                "INSERT OR IGNORE INTO conversations(id, title, project, created, updated, summary) VALUES (?,?,?,?,?,?)",
                (cid, "Main conversation" if cid == "default" else f"Conversation {cid[:8]}", "", now, now, ""),
            )
            self.db.execute("UPDATE conversations SET updated=? WHERE id=?", (now, cid))
            self.db.commit()

    def recent_messages(self, limit: int, conversation_id: str = "default") -> list:
        cid = (conversation_id or "default")[:64]
        with self._lock:
            rows = self.db.execute(
                "SELECT role, content FROM messages WHERE conversation_id=? ORDER BY id DESC LIMIT ?", (cid, limit)
            ).fetchall()
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def create_conversation(self, title: str, project: str = "") -> dict:
        import uuid
        title = redact(str(title or "").strip())[:100]
        if not title:
            raise ValueError("Enter a conversation title between 1 and 100 characters.")
        project = str(project or "").strip()[:60]
        cid = uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock, self.db:
            self.db.execute(
                "INSERT INTO conversations(id, title, project, created, updated, summary) VALUES (?,?,?,?,?,?)",
                (cid, title, project, now, now, ""),
            )
        return {"id": cid, "title": title, "project": project, "created": now, "updated": now, "summary": ""}

    def list_conversations(self, project: str = "") -> list:
        with self._lock:
            if project:
                rows = self.db.execute(
                    "SELECT id, title, project, created, updated, summary FROM conversations WHERE project=? ORDER BY updated DESC LIMIT 100",
                    (project,),
                ).fetchall()
            else:
                rows = self.db.execute(
                    "SELECT id, title, project, created, updated, summary FROM conversations ORDER BY updated DESC LIMIT 100"
                ).fetchall()
        return [dict(zip(("id", "title", "project", "created", "updated", "summary"), row)) for row in rows]

    def rename_conversation(self, cid: str, title: str) -> bool:
        title = redact(str(title or "").strip())[:100]
        if not title:
            raise ValueError("Enter a conversation title between 1 and 100 characters.")
        with self._lock, self.db:
            res = self.db.execute("UPDATE conversations SET title=?, updated=? WHERE id=?", (title, time.time(), cid))
            return res.rowcount == 1

    def delete_conversation(self, cid: str) -> bool:
        with self._lock, self.db:
            self.db.execute("DELETE FROM messages WHERE conversation_id=?", (cid,))
            res = self.db.execute("DELETE FROM conversations WHERE id=?", (cid,))
            return res.rowcount == 1

    def set_conversation_summary(self, cid: str, summary: str) -> bool:
        with self._lock, self.db:
            res = self.db.execute("UPDATE conversations SET summary=?, updated=? WHERE id=?",
                                  (redact(str(summary or "")[:2000]), time.time(), cid))
            return res.rowcount == 1

    # ---------- projects / knowledge spaces (R03) ----------
    def save_project(self, name: str, description: str = "", code_dir: str = "", document_folders=None) -> dict:
        import uuid
        name = str(name or "").strip()[:60]
        if not name:
            raise ValueError("Enter a project name between 1 and 60 characters.")
        folders = [str(f).strip() for f in (document_folders or []) if isinstance(f, str) and f.strip()][:20]
        now = time.time()
        with self._lock, self.db:
            row = self.db.execute("SELECT id, created FROM projects WHERE name=?", (name,)).fetchone()
            if row:
                pid, created = row
                self.db.execute(
                    "UPDATE projects SET description=?, code_dir=?, document_folders=? WHERE id=?",
                    (redact(str(description or "")[:500]), str(code_dir or "")[:500], json.dumps(folders), pid),
                )
            else:
                pid, created = uuid.uuid4().hex[:16], now
                self.db.execute(
                    "INSERT INTO projects(id, name, description, code_dir, document_folders, created) VALUES (?,?,?,?,?,?)",
                    (pid, name, redact(str(description or "")[:500]), str(code_dir or "")[:500], json.dumps(folders), created),
                )
        return {"id": pid, "name": name, "description": str(description or "")[:500],
                "code_dir": str(code_dir or "")[:500], "document_folders": folders, "created": created}

    def list_projects(self) -> list:
        with self._lock:
            rows = self.db.execute(
                "SELECT id, name, description, code_dir, document_folders, created FROM projects ORDER BY name"
            ).fetchall()
        return [
            {"id": r[0], "name": r[1], "description": r[2], "code_dir": r[3],
             "document_folders": json.loads(r[4] or "[]"), "created": r[5]}
            for r in rows
        ]

    def delete_project(self, name: str) -> bool:
        with self._lock, self.db:
            res = self.db.execute("DELETE FROM projects WHERE name=?", (name,))
            return res.rowcount == 1

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
    def remember(self, text: str, origin: str = "Jarvis memory tool", project: str = "") -> int:
        text = redact(text.strip())
        vec = self.embed(text) if self.embed else None
        with self._lock:
            cur = self.db.execute(
                "INSERT INTO facts(ts, text, embedding, origin, project) VALUES (?,?,?,?,?)",
                (time.time(), text, json.dumps(vec) if vec else None, str(origin)[:80], str(project or "")[:60]),
            )
            self.db.commit()
            return cur.lastrowid

    def find_duplicate_facts(self, similarity_threshold: float = 0.8) -> list:
        """Identify exact or near-duplicate facts for review and deduplication."""
        facts = self.fact_details()
        groups = []
        seen = set()
        for i, first in enumerate(facts):
            if first["id"] in seen:
                continue
            w1 = _words(first["text"])
            cluster = [first]
            for second in facts[i + 1:]:
                if second["id"] in seen:
                    continue
                if first["text"].casefold().strip() == second["text"].casefold().strip():
                    sim = 1.0
                else:
                    w2 = _words(second["text"])
                    union = len(w1 | w2)
                    sim = (len(w1 & w2) / union) if union else 0.0
                if sim >= similarity_threshold:
                    cluster.append(second)
                    seen.add(second["id"])
            if len(cluster) > 1:
                seen.add(first["id"])
                groups.append(cluster)
        return groups

    def deduplicate_facts(self) -> int:
        """Remove duplicate facts keeping the newest item in each duplicate cluster."""
        groups = self.find_duplicate_facts()
        removed = 0
        for cluster in groups:
            keep = max(cluster, key=lambda item: item["id"])
            for item in cluster:
                if item["id"] != keep["id"] and self.delete_fact(item["id"]):
                    removed += 1
        return removed

    def import_facts(self, items: list, project: str = "") -> int:
        """Safely import validated, redacted facts from a JSON list."""
        if not isinstance(items, list) or len(items) > 500:
            raise ValueError("Import accepts a list of at most 500 facts.")
        existing = {text.casefold().strip() for _, text in self.all_facts()}
        added = 0
        for item in items:
            raw = item.get("text") if isinstance(item, dict) else item
            if not isinstance(raw, str) or not 1 <= len(raw.strip()) <= 4000:
                continue
            cleaned = redact(raw.strip())
            if cleaned.casefold() in existing:
                continue
            self.remember(cleaned, origin="Imported JSON", project=project)
            existing.add(cleaned.casefold())
            added += 1
        return added

    def all_facts(self) -> list:
        self.purge_expired()
        with self._lock:
            return self.db.execute("SELECT id, text FROM facts ORDER BY id").fetchall()

    def purge_expired(self) -> int:
        with self._lock, self.db:
            result = self.db.execute('DELETE FROM facts WHERE expires IS NOT NULL AND expires<=?', (time.time(),))
            return result.rowcount

    def fact_details(self) -> list:
        self.purge_expired()
        with self._lock:
            rows = self.db.execute('SELECT id, text, ts, origin, expires FROM facts ORDER BY id').fetchall()
        return [dict(zip(('id', 'text', 'saved', 'origin', 'expires'), row)) for row in rows]

    def set_fact_expiry(self, fact_id: int, expires) -> bool:
        if expires is not None and (type(expires) not in (int, float) or
                                    not time.time() < expires <= time.time() + 10 * 365 * 86400):
            raise ValueError('Choose a future date within ten years, or clear expiry.')
        with self._lock, self.db:
            result = self.db.execute('UPDATE facts SET expires=? WHERE id=?', (expires, fact_id))
            return result.rowcount == 1

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
        self.purge_expired()
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
