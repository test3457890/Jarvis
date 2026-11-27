"""Activity view exposes useful local action metadata without raw inputs."""
from jarvis import secure, skills


def test_activity_is_bounded_redacted_and_has_undo_hint(isolated_app):
    assert secure.recent_activity() == []
    secure.audit('code_edit_applied', {'files':['cart.py'], 'secret':'do not show'})
    secure.audit('execute_folder_job', {'args':{'job_id':'abc', 'message':'private'}, 'result':'Done'})
    secure.audit('network_blocked', {'purpose':'web_search', 'host':'private.example'})
    secure.audit('send_email', {'args':{'body':'private email body'}})
    with secure.AUDIT_PATH.open('a', encoding='utf-8') as stream:
        stream.write('not JSON\n')
    rows = secure.recent_activity(2)
    assert len(rows) == 2
    assert rows[0]['action'] == 'Email sent' and rows[0]['target'] == ''
    assert rows[1]['action'] == 'Network request blocked' and rows[1]['target'] == 'web_search'
    all_rows = secure.recent_activity()
    assert all_rows[2]['undo'] == 'File tasks: Show task history'
    assert all_rows[3]['undo'] == 'Coding mode: /undo'
    assert all_rows[3]['target'] == 'cart.py'
    assert 'private' not in str(all_rows) and 'do not show' not in str(all_rows)


def test_activity_reads_only_recent_log_tail(isolated_app):
    secure.AUDIT_PATH.write_bytes(b'old secret\n' * 30000)
    secure.audit('lockdown_blocked', {'skill':'run_project_tests'})
    rows = secure.recent_activity(500)
    assert len(rows) == 1 and rows[0]['target'] == 'run_project_tests'


def test_risky_tool_log_does_not_store_message_body(isolated_app, monkeypatch):
    _, _, ctx, _ = isolated_app
    secret = 'private message content'
    monkeypatch.setitem(skills.SKILLS, 'send_email', {
        'fn': lambda ctx, body: 'Finished ' + body,
        'description': 'test', 'params': {'body': ('string', 'text', True)},
        'risky': True, 'internet': False, 'untrusted': False,
        'preview': None, 'available': None, 'manual': False,
    })
    assert secret in skills.run(ctx, 'send_email', {'body': secret}, confirmed=True)
    assert secret not in secure.AUDIT_PATH.read_text(encoding='utf-8')
