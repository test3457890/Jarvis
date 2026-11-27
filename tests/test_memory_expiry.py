"""Saved fact provenance and expiration across the old SQLite schema."""
import sqlite3
import time

import pytest

from jarvis import memory as mem_mod
from jarvis.__main__ import App


def test_fact_expiry_removes_stored_text_and_recall(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    fact_id = db.remember('Aviation compass is in the drawer')
    fact = db.fact_details()[0]
    assert fact['id'] == fact_id and fact['origin'] == 'Jarvis memory tool'
    assert fact['saved'] > 0 and fact['expires'] is None
    soon = time.time() + 100
    assert db.set_fact_expiry(fact_id, soon)
    assert db.recall('aviation compass')
    monkeypatch.setattr(mem_mod.time, 'time', lambda: soon + 1)
    assert db.recall('aviation compass') == []
    assert db.fact_details() == []
    assert db.db.execute('SELECT COUNT(*) FROM facts').fetchone()[0] == 0


def test_old_facts_migrate_and_expiry_controls(isolated_app, monkeypatch):
    cfg, db, _, home = isolated_app
    db.db.close()
    path = home / 'memory.db'
    connection = sqlite3.connect(path)
    connection.execute('DROP TABLE facts')
    connection.execute('CREATE TABLE facts (id INTEGER PRIMARY KEY, ts REAL, text TEXT, embedding TEXT)')
    connection.execute('INSERT INTO facts(ts,text) VALUES (?,?)', (100, 'Old project detail'))
    connection.commit()
    connection.close()
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    try:
        rows = app.memory_operation()['facts']
        assert rows[0]['origin'] == 'Saved before source tracking'
        with pytest.raises(ValueError):
            app.memory_operation({'action':'expire', 'id':rows[0]['id'], 'expires':True})
        with pytest.raises(ValueError):
            app.memory_operation({'action':'expire', 'id':rows[0]['id']})
        expiry = time.time() + 86400
        assert app.memory_operation({'action':'expire', 'id':rows[0]['id'], 'expires':expiry})['facts'][0]['expires'] == expiry
        assert app.memory_operation({'action':'clear_expiry', 'id':rows[0]['id']})['facts'][0]['expires'] is None
        cfg['lockdown'] = True
        with pytest.raises(ValueError, match='Lockdown'):
            app.memory_operation({'action':'expire', 'id':rows[0]['id'], 'expires':expiry})
    finally:
        app.memory.db.close()
