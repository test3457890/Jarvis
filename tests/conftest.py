import pytest

from jarvis import config, memory as mem_mod, planner, secure, skills


@pytest.fixture()
def isolated_app(tmp_path, monkeypatch):
    """Isolate all runtime files (DB, config, secrets, audit log, notes, code) to tmp_path."""
    app_dir = tmp_path / "appdata_jarvis"
    app_dir.mkdir(parents=True, exist_ok=True)
    notes_dir = app_dir / "notes"
    notes_dir.mkdir(parents=True, exist_ok=True)
    code_dir = tmp_path / "jarvis_code"
    code_dir.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(config, "APP_DIR", app_dir)
    monkeypatch.setattr(config, "CONFIG_PATH", app_dir / "config.json")
    monkeypatch.setattr(mem_mod, "APP_DIR", app_dir)
    monkeypatch.setattr(mem_mod, "DB_PATH", app_dir / "memory.db")
    monkeypatch.setattr(secure, "APP_DIR", app_dir)
    monkeypatch.setattr(secure, "SECRETS_PATH", app_dir / "secrets.bin")
    monkeypatch.setattr(secure, "AUDIT_PATH", app_dir / "actions.log")
    monkeypatch.setattr(planner, "APP_DIR", app_dir)
    monkeypatch.setattr(planner, "CANVAS_CACHE", app_dir / "canvas.ics")

    cfg = dict(config.DEFAULTS)
    cfg["notes_dir"] = str(notes_dir)
    cfg["code_dir"] = str(code_dir)
    cfg["speak_replies"] = False

    db = mem_mod.Memory()
    planner.init_db(db)
    from jarvis import comms
    comms.init_db(db)
    ctx = skills.Context(cfg, db)
    yield cfg, db, ctx, app_dir
    db.db.close()
