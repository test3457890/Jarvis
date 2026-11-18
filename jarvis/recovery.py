"""Atomic backups of the local SQLite data, with validated transactional restore."""
import json
import sqlite3
import uuid
from pathlib import Path

from . import config


def backup(memory):
    folder = config.APP_DIR / 'backups'
    folder.mkdir(parents=True, exist_ok=True)
    name = 'Jarvis ' + uuid.uuid4().hex + '.db'
    path = folder / name
    temporary = path.with_suffix('.partial')
    try:
        with memory._lock, sqlite3.connect(temporary) as destination:
            memory.db.backup(destination)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
    return name


def restore(memory, name):
    if not isinstance(name, str) or Path(name).name != name or not name.startswith('Jarvis ') or not name.endswith('.db'):
        raise ValueError('Select a Jarvis backup from this PC.')
    path = (config.APP_DIR / 'backups' / name)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 100_000_000:
        raise ValueError('Backup is missing or exceeds the 100 MB restore limit.')
    # Read a copy to avoid a concurrent change to the backup during validation.
    raw = path.read_bytes()
    source = sqlite3.connect(':memory:')
    try:
        source.deserialize(raw)
        source.execute('PRAGMA trusted_schema=OFF')
        if source.execute('PRAGMA integrity_check').fetchone() != ('ok',):
            raise ValueError('Backup integrity check failed.')
        tables = {row[0] for row in source.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        required = {'messages', 'facts', 'reminders', 'tasks', 'events', 'kv', 'contacts'}
        if not required <= tables:
            raise ValueError('This file is not a complete Jarvis backup.')
        if source.execute("SELECT 1 FROM sqlite_master WHERE type IN ('trigger','view')").fetchone():
            raise ValueError('Backups containing views or triggers cannot be restored.')
        # Require the current column definitions before restoring any rows.
        with memory._lock:
            names = sorted(tables)
            if not tables <= {row[0] for row in memory.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}:
                raise ValueError('Backup schema differs from this Jarvis version.')
            contents = {}
            for table in names:
                if not table.replace('_','').isalnum():
                    raise ValueError('Invalid backup table.')
                columns = list(source.execute(f'PRAGMA table_info("{table}")'))
                if columns != list(memory.db.execute(f'PRAGMA table_info("{table}")')):
                    raise ValueError('Backup schema differs from this Jarvis version.')
                contents[table] = source.execute(f'SELECT * FROM "{table}"').fetchall()
        rescue = backup(memory)
        with memory._lock, memory.db:
            for table, rows in contents.items():
                memory.db.execute(f'DELETE FROM "{table}"')
                if rows:
                    placeholders = ','.join('?' for _ in rows[0])
                    memory.db.executemany(f'INSERT INTO "{table}" VALUES ({placeholders})', rows)
        return rescue
    except sqlite3.DatabaseError as error:
        raise ValueError('The backup could not be read or restored.') from error
    finally:
        source.close()


def list_backups():
    folder = config.APP_DIR / 'backups'
    return sorted(p.name for p in folder.glob('Jarvis *.db') if p.is_file() and not p.is_symlink())
