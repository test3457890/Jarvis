"""Real loopback request tests with an inert application. No model or OS actions."""
import http.client
import json
import socket
from types import SimpleNamespace

import pytest

from jarvis import net, secure, webui


@pytest.mark.parametrize('value', [None, 7, '', 'http://[broken', 'http://localhost:bad',
                                  'http://localhost:65536', 'http://localhost:0',
                                  'http://name:PRIVATE@localhost:8080', 'http://local\nhost:8080'])
def test_invalid_endpoints_fail_closed(value, isolated_app):
    cfg, _, _, _ = isolated_app
    assert net._parse_endpoint(value) is None
    with pytest.raises(net.NetworkBlockedError):
        net.check_url(value, cfg)


def test_blocked_url_does_not_disclose_private_path_or_query(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    events = []
    monkeypatch.setattr(secure, 'audit', lambda name, data: events.append((name, data)))
    with pytest.raises(net.NetworkBlockedError) as error:
        net.check_url('https://example.invalid/PRIVATE_FEED?token=PRIVATE_TOKEN', cfg, purpose='test')
    assert 'PRIVATE' not in str(error.value)
    assert 'PRIVATE' not in json.dumps(events)
    assert events[0][1]['endpoint'] == ['https', 'example.invalid', 443]


@pytest.fixture
def server(monkeypatch):
    monkeypatch.setattr(webui, 'REQUEST_BODY_TIMEOUT', 0.15)
    app = SimpleNamespace(cfg={}, bus=webui.EventBus(), state=lambda: {'fixture': True},
                          toggle=lambda value: {'toggle': value},
                          dictation_operation=lambda data: {'action':data.get('action')},
                          provider_operation=lambda data=None: {'provider':'ollama'},
                          workflows_operation=lambda data=None: {'templates':[], 'runs':[]})
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        port = probe.getsockname()[1]
    service = webui.serve(app, port)
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    connection.request('GET', '/')
    page = connection.getresponse().read().decode()
    key = page.split('const KEY = "')[1].split('"')[0]
    connection.close()
    yield port, key
    service.shutdown()
    service.server_close()


def request(server, lengths, body=b'', transfer=None, half_close=False):
    port, key = server
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    connection.putrequest('POST', '/api/toggle')
    connection.putheader('X-Jarvis-Key', key)
    for length in lengths:
        connection.putheader('Content-Length', str(length))
    if transfer:
        connection.putheader('Transfer-Encoding', transfer)
    connection.endheaders(body)
    if half_close:
        connection.sock.shutdown(socket.SHUT_WR)
    response = connection.getresponse()
    result = response.status, response.read(), response.getheader('Cache-Control')
    connection.close()
    return result


@pytest.mark.parametrize('lengths,transfer', [([], None), ([2, 2], None), ([2], 'chunked'), ([-1], None), ([100001], None)])
def test_ambiguous_or_oversized_request_is_rejected(server, lengths, transfer):
    assert request(server, lengths, b'{}', transfer)[0] == 400


def test_incomplete_and_stalled_bodies_are_rejected(server):
    assert request(server, [10], b'{}', half_close=True)[0] == 400
    assert request(server, [10])[0] == 408


def test_valid_json_and_private_response_caching(server):
    status, data, cache = request(server, [2], b'{}')
    assert status == 200 and json.loads(data) == {'toggle': ''}
    assert cache == 'no-store'


@pytest.mark.parametrize('method,path', [('POST','/api/dictation'), ('POST','/api/workflows'), ('GET','/api/workflows'),
                                        ('GET','/api/provider'), ('POST','/api/provider')])
@pytest.mark.parametrize('credential', ['missing', 'foreign-origin', 'valid'])
def test_new_local_actions_require_session_key_and_same_origin(server, method, path, credential):
    port, key = server
    headers = {'Content-Type':'application/json'}
    if credential != 'missing':
        headers['X-Jarvis-Key'] = key
    if credential == 'foreign-origin':
        headers['Origin'] = 'https://attacker.invalid'
    connection = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
    try:
        connection.request(method, path, b'{"action":"start"}' if method == 'POST' else None, headers)
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == (200 if credential == 'valid' else 403)
        if credential == 'valid':
            expected = {'action':'start'} if path == '/api/dictation' else {'provider':'ollama'} if path == '/api/provider' else {'templates':[], 'runs':[]}
            assert payload == expected
        assert response.getheader('Cache-Control') == 'no-store'
    finally:
        connection.close()
