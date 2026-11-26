"""End-to-end local index lifecycle using real SQLite FTS and selected files."""
from pathlib import Path

from jarvis import config, docindex, documents, skills
from jarvis.__main__ import App


def test_index_refreshes_changes_and_deletes_removed_files(isolated_app, monkeypatch):
    cfg, _, ctx, home = isolated_app
    root = home / 'selected'
    root.mkdir()
    a = root / 'a.txt'
    a.write_text('Compass bearings\n', encoding='utf-8')
    cfg['document_folders'] = [str(root)]
    cfg['document_index_enabled'] = True

    first = skills.run(ctx, 'search_documents', {'query': 'compass'})
    assert 'a.txt, lines 1-1' in first and 'Updated 1' in first
    assert docindex.path().exists()
    second = skills.run(ctx, 'search_documents', {'query': 'compass'})
    assert 'Updated 0' in second

    a.write_text('Navigation chart with a revised section', encoding='utf-8')
    assert 'No matching' in skills.run(ctx, 'search_documents', {'query': 'compass'})
    assert 'Navigation chart' in skills.run(ctx, 'search_documents', {'query': 'navigation'})
    a.unlink()
    assert 'No matching' in skills.run(ctx, 'search_documents', {'query': 'navigation'})
    assert docindex.search(cfg, 'navigation').endswith('No matching extracted text found.')


def test_index_excludes_links_and_wipes_on_setup_change(isolated_app, monkeypatch):
    cfg, _, ctx, home = isolated_app
    root = home / 'selected'
    root.mkdir()
    secret = home / 'private.txt'
    secret.write_text('Sensitive outside text', encoding='utf-8')
    try:
        (root / 'linked.txt').symlink_to(secret)
    except OSError:
        pass
    (root / 'inside.md').write_text('Radio checklist', encoding='utf-8')
    cfg['document_folders'] = [str(root)]
    cfg['document_index_enabled'] = True
    assert 'Sensitive outside text' not in documents.search_documents(ctx, 'sensitive')
    assert 'Radio checklist' in documents.search_documents(ctx, 'radio')
    assert docindex.path().exists()

    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    app = App(cfg, use_voice=False)
    app.settings_operation({'document_index_enabled': False})
    assert not docindex.path().exists()
    app.memory.db.close()


def test_index_never_returns_unseen_paths_at_scan_limit(isolated_app, monkeypatch):
    cfg, _, ctx, home = isolated_app
    root = home / 'selected'
    root.mkdir()
    (root / 'a.txt').write_text('Aviation', encoding='utf-8')
    (root / 'b.txt').write_text('Aviation', encoding='utf-8')
    cfg['document_folders'] = [str(root)]
    cfg['document_index_enabled'] = True
    assert 'b.txt' in documents.search_documents(ctx, 'aviation')
    monkeypatch.setattr(documents, 'MAX_FILES', 1)
    limited = documents.search_documents(ctx, 'aviation')
    assert 'Search limit reached' in limited
    assert 'a.txt' in limited and 'b.txt' not in limited
