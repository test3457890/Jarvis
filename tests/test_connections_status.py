"""Connection center reports configuration and scope without leaking credentials."""
import pytest

from jarvis import connections, planner, secure
from jarvis.__main__ import App


def test_connection_status_and_offline_exceptions(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    secrets = {'canvas_feed_url':'https://canvas.example/private-feed?token=very-secret',
               'brave_search_key':'private-search-key', 'smtp_user':'user@example.org',
               'smtp_password':'secret-password', 'github_upload_token':'private-github-token'}
    monkeypatch.setattr(secure, 'get_secret', lambda key, default='': secrets.get(key, default))
    monkeypatch.setattr(secure, 'has_secret', lambda key: bool(secrets.get(key)))
    cfg.update({'allow_internet_tools':False, 'allow_web_search':True,
                'github_upload_repo':'test/repo', 'image_generation_url':'http://127.0.0.1:7860'})
    services = {item['name']:item for item in connections.status(cfg)}
    assert services['Brave public search']['state'] == 'Paused'
    assert services['GitHub upload']['state'] == 'Paused'
    assert services['SMTP email']['state'] == 'Configured'
    assert 'does not pause SMTP' in services['SMTP email']['scope']
    assert services['Canvas calendar feed']['state'] == 'Configured'
    assert services['Project NOMAD']['state'] == 'Address set; not checked'
    assert services['Local image generation']['state'] == 'Address set; not checked'
    assert all('very-secret' not in str(item) and 'secret-password' not in str(item)
               for item in services.values())
    cfg['allow_internet_tools'] = True
    assert {item['name']:item['state'] for item in connections.status(cfg)}['GitHub upload'] == 'Ready'


def test_local_credential_removal_requires_confirmation(isolated_app, monkeypatch):
    cfg, _, _, home = isolated_app
    secrets = {'canvas_feed_url':'https://canvas.example/private.ics', 'brave_search_key':'key'}
    monkeypatch.setattr(secure, 'get_secret', lambda key, default='': secrets.get(key, default))
    monkeypatch.setattr(secure, 'has_secret', lambda key: bool(secrets.get(key)))
    monkeypatch.setattr(secure, 'set_secret', lambda key, value: secrets.__setitem__(key, value))
    monkeypatch.setattr(App, '_watchdog', lambda _: None)
    planner.CANVAS_CACHE.write_text('BEGIN:VCALENDAR\nEND:VCALENDAR', encoding='utf-8')
    app = App(cfg, use_voice=False)
    try:
        with pytest.raises(ValueError, match='confirm'):
            app.connections_operation({'action':'revoke', 'service':'Canvas calendar feed'})
        with pytest.raises(ValueError, match='supported'):
            app.connections_operation({'action':'revoke', 'service':'unknown', 'confirmed':True})
        cfg['lockdown'] = True
        with pytest.raises(ValueError, match='Lockdown'):
            app.connections_operation({'action':'revoke', 'service':'Canvas calendar feed', 'confirmed':True})
        cfg['lockdown'] = False
        result = app.connections_operation({'action':'revoke', 'service':'Canvas calendar feed', 'confirmed':True})
        assert not secrets['canvas_feed_url'] and not planner.CANVAS_CACHE.exists()
        assert result['services'][0]['state'] == 'Needs setup'
        assert 'connection_revoked' in secure.AUDIT_PATH.read_text(encoding='utf-8')
    finally:
        app.memory.db.close()
