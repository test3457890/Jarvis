"""A selected repository stays inside the coding grant and keeps per-root undo."""
import pytest

from jarvis import coder, planner
from jarvis.__main__ import App


def test_select_existing_repository_and_reset(isolated_app, monkeypatch):
    cfg, _, _, home = isolated_app
    repository = home / 'example'
    repository.mkdir()
    (repository / '.git').mkdir()
    (repository / 'package.json').write_text('{"scripts": {"test": "node test.js"}}', encoding='utf-8')
    (repository / 'test.js').write_text('console.log("ok")', encoding='utf-8')
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    try:
        with pytest.raises(ValueError, match='not a Git'):
            app.repository_operation({'action':'select', 'path':str(home)})
        summary = app.repository_operation({'action':'select', 'path':str(repository)})
        assert summary['is_repository'] and summary['path'] == str(repository)
        assert summary['root'] == '.' and 'test.js' in summary['files']
        assert coder.project_root(cfg, repository / 'test.js') == repository
        with pytest.raises(ValueError):
            coder._safe_path(cfg, '.git/config')
        with pytest.raises(ValueError):
            coder._safe_path(cfg, '../outside.py')
        assert '.git' not in coder.list_code(app.brain.ctx)
        cfg['lockdown'] = True
        with pytest.raises(ValueError, match='Lockdown'):
            app.repository_operation({'action':'reset'})
        cfg['lockdown'] = False
        assert app.repository_operation({'action':'reset'})['is_repository'] is False
    finally:
        app.memory.db.close()


def test_repository_switch_keeps_old_undo_in_old_workspace(isolated_app, monkeypatch):
    cfg, _, _, home = isolated_app
    old = home / 'old'
    old.mkdir()
    cfg['code_dir'] = str(old)
    repository = home / 'repo'
    repository.mkdir()
    (repository / '.git').mkdir()
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    try:
        planner.kv_set(app.memory, 'code-undo', [{'filename':'example.py', 'original':None, 'code':'example'}])
        app.repository_operation({'action':'select', 'path':str(repository)})
        assert coder._restore_undo(app.brain.ctx) is None
        assert planner.kv_get(app.memory, 'code-undo') is None
        cfg['code_dir'] = str(old)
        assert coder._restore_undo(app.brain.ctx) is not None
    finally:
        app.memory.db.close()


def test_selected_repo_rejects_file_task_overlap(isolated_app, monkeypatch):
    cfg, _, _, home = isolated_app
    repository = home / 'repo'
    repository.mkdir()
    (repository / '.git').mkdir()
    cfg['file_folders'] = [str(home)]
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    try:
        with pytest.raises(ValueError, match='separate'):
            app.repository_operation({'action':'select', 'path':str(repository)})
    finally:
        app.memory.db.close()
