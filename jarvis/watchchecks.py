"""Opt-in daily checks of explicitly selected local documents."""
import hashlib
import re
from datetime import datetime

from . import skills


def init_db(memory):
    with memory._lock, memory.db:
        memory.db.execute("""CREATE TABLE IF NOT EXISTS document_watches (
            id INTEGER PRIMARY KEY, query TEXT NOT NULL, daily_time TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1, last_date TEXT,
            last_hash TEXT, status TEXT NOT NULL DEFAULT 'Waiting for first run')""")


def list_watches(memory):
    with memory._lock:
        rows = memory.db.execute(
            "SELECT id, query, daily_time, enabled, last_date, status "
            "FROM document_watches ORDER BY id DESC").fetchall()
    return [dict(zip(('id', 'query', 'daily_time', 'enabled', 'last_date', 'status'), row))
            for row in rows]


def operate(memory, data):
    action = data.get('action')
    if action == 'add':
        query, daily_time = data.get('query'), data.get('daily_time')
        if not isinstance(query, str) or not 1 <= len(query.strip()) <= 500:
            raise ValueError('Enter a document query between 1 and 500 characters.')
        if not isinstance(daily_time, str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', daily_time):
            raise ValueError('Choose a local time in HH:MM format.')
        with memory._lock, memory.db:
            if memory.db.execute('SELECT COUNT(*) FROM document_watches').fetchone()[0] >= 20:
                raise ValueError('At most 20 document checks can be saved.')
            memory.db.execute('INSERT INTO document_watches(query, daily_time) VALUES (?, ?)',
                              (query.strip(), daily_time))
    elif action in ('pause', 'resume', 'delete'):
        watch_id = data.get('id')
        if type(watch_id) is not int or watch_id < 1:
            raise ValueError('Choose a valid document check.')
        with memory._lock, memory.db:
            if action == 'delete':
                changed = memory.db.execute('DELETE FROM document_watches WHERE id=?', (watch_id,))
            else:
                changed = memory.db.execute(
                    'UPDATE document_watches SET enabled=?, status=? WHERE id=?',
                    (int(action == 'resume'), 'Waiting for next run' if action == 'resume' else 'Paused', watch_id))
            if not changed.rowcount:
                raise ValueError('Document check not found.')
    else:
        raise ValueError('Unknown document check action.')
    return list_watches(memory)


def run_due(memory, cfg, notify, now=None):
    """Run due jobs once per local calendar date. Only changed matches notify."""
    now = now or datetime.now().astimezone()
    today, clock = now.strftime('%Y-%m-%d'), now.strftime('%H:%M')
    with memory._lock:
        rows = memory.db.execute(
            "SELECT id, query, last_hash FROM document_watches "
            "WHERE enabled=1 AND daily_time<=? AND (last_date IS NULL OR last_date!=?)",
            (clock, today)).fetchall()
    for watch_id, query, old_hash in rows:
        status, digest = 'No matching text', None
        try:
            if not cfg.get('document_folders'):
                status = 'Choose document folders in Setup'
            elif skills.permission_level(cfg, 'search_documents') != 'allowed':
                status = 'Enable automatic document search in skill permissions'
            else:
                ctx = skills.Context(cfg, memory)
                result = skills.run(ctx, 'search_documents', {'query': query})
                if ctx.injection_seen:
                    status = 'Blocked unsafe document instructions'
                elif 'No matching extracted text found.' in result:
                    digest = hashlib.sha256(b'no matches').hexdigest()
                elif '\n[1] ' in result:
                    # Ignore scanner counters and index update metadata, which change
                    # even when the matched source excerpts stay exactly the same.
                    evidence = result[result.index('\n[1] ') + 1:]
                    digest = hashlib.sha256(evidence.encode('utf-8')).hexdigest()
                    status = 'Matched text checked'
                else:
                    status = 'Search unavailable or incomplete'
        except Exception:
            status = 'Search failed; review document setup'
        with memory._lock, memory.db:
            changed = memory.db.execute(
                "UPDATE document_watches SET last_date=?, last_hash=COALESCE(?, last_hash), status=? "
                "WHERE id=? AND enabled=1 AND (last_date IS NULL OR last_date!=?)",
                (today, digest, status, watch_id, today))
        if changed.rowcount and digest and old_hash and digest != old_hash:
            notify(f'Document check changed: {query}. Search selected documents to review the matching excerpts.')
