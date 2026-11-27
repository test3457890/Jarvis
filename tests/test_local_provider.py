"""Real loopback HTTP, strict completed tool parsing and no cloud fallback."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from jarvis import config, localprovider, net
from jarvis.brain import Brain
from jarvis.__main__ import App


def completion(content="Local answer", calls=None, reason="stop"):
    return {"choices":[{"finish_reason":reason, "message":{"role":"assistant", "content":content, "tool_calls":calls or []}}]}


@pytest.fixture
def local_server():
    fixture = SimpleNamespace(requests=[], replies=[])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            fixture.requests.append(("GET", self.path, None))
            self.send_response(200); self.end_headers()
            self.wfile.write(b'{"data":[{"id":"test-local"}]}')
        def do_POST(self):
            payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            fixture.requests.append(("POST", self.path, payload))
            self.send_response(200); self.end_headers()
            self.wfile.write(json.dumps(fixture.replies.pop(0)).encode())
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    fixture.url = f"http://127.0.0.1:{server.server_port}"
    yield fixture
    server.shutdown(); server.server_close()


def provider_config(cfg, server):
    cfg.update(chat_provider="openai_local", local_chat_url=server.url, local_chat_model="test-local",
               allow_internet_tools=False)
    return cfg


def test_loopback_provider_works_offline_and_uses_actual_model_label(isolated_app, local_server):
    cfg, db, _, _ = isolated_app
    provider_config(cfg, local_server)
    brain = Brain(cfg, db)
    assert brain.installed_models() == ["test-local"]
    local_server.replies.append(completion())
    assert "Local answer" in brain.ask("Hello")
    assert brain.model_used == "test-local"
    method, path, payload = local_server.requests[-1]
    assert method == "POST" and path == "/v1/chat/completions"
    assert payload["model"] == "test-local" and payload["stream"] is False
    assert "keep_alive" not in payload and "think" not in payload
    assert brain.embed("private fact") is None


def test_tool_call_round_trip_keeps_ids_and_existing_permission_controls(isolated_app, local_server):
    cfg, db, _, _ = isolated_app
    provider_config(cfg, local_server)
    brain = Brain(cfg, db)
    call = {"id":"calc-1", "type":"function", "function":{"name":"calculate", "arguments":'{"expression":"2+3"}'}}
    local_server.replies.extend([completion(calls=[call], reason="tool_calls"), completion("The result is five.")])
    assert "five" in brain.ask("Calculate this")
    tool = local_server.requests[-1][2]["messages"][-1]
    assert tool["role"] == "tool" and tool["tool_call_id"] == "calc-1" and "= 5" in tool["content"]
    # The provider can request an action, but cannot turn that into permission.
    call["function"] = {"name":"power", "arguments":'{"action":"shutdown"}'}
    local_server.replies.append(completion(calls=[call], reason="tool_calls"))
    brain.ask("Show an action preview")
    assert brain.ctx.pending and brain.ctx.pending["name"] == "power"


@pytest.mark.parametrize("url", ["https://api.example.com", "http://localhost:8081", "http://127.0.0.1:8081/v1",
                                  "http://127.0.0.1:8081?secret=x", "http://user:pass@127.0.0.1:8081", "http://127.0.0.1:0"])
def test_remote_or_ambiguous_endpoints_are_refused(url):
    with pytest.raises(ValueError):
        localprovider.endpoint({"local_chat_url":url})


@pytest.mark.parametrize("data", [
    {}, {"choices":[]}, completion(reason=None), completion(reason="content_filter"),
    completion(calls=[{"id":"x", "type":"function", "function":{"name":"power", "arguments":"[]"}}], reason="tool_calls"),
    completion(calls=[{"id":"x", "type":"function", "function":{"name":"power", "arguments":"{"}}], reason="tool_calls"),
    completion(calls=[{"id":"x", "type":"function", "function":{"name":"power", "arguments":"{}"}}], reason="length"),
    completion(reason="tool_calls"),
])
def test_incomplete_and_malformed_responses_cannot_produce_tool_calls(data):
    with pytest.raises(ValueError):
        localprovider.normalise(data)


def test_duplicate_tool_ids_and_non_object_arguments_are_refused():
    call={"id":"x", "type":"function", "function":{"name":"calculate", "arguments":"{}"}}
    with pytest.raises(ValueError, match="repeated"):
        localprovider.normalise(completion(calls=[call, call], reason="tool_calls"))


def test_cancelled_reply_cannot_return_any_tool_calls(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    cfg.update(chat_provider="openai_local", local_chat_model="test-local")
    cancelled=threading.Event()
    def reply(*args):
        cancelled.set()
        return completion()
    monkeypatch.setattr(localprovider, "_json", reply)
    with pytest.raises(ValueError, match="Stopped"):
        localprovider.chat(cfg, {"messages":[]}, cancelled, lambda *a:None, 1)


def test_provider_selection_is_explicit_atomic_and_does_not_change_ollama_roles(isolated_app, monkeypatch):
    cfg, _, _, _ = isolated_app
    monkeypatch.setattr(App, "_watchdog", lambda _:None)
    app=App(cfg, use_voice=False)
    old={key:cfg[key] for key in ("model","coder_model","everyday_model")}
    try:
        app.provider_operation({"action":"save", "provider":"openai_local", "url":"http://127.0.0.1:8081", "model":"test-local"})
        assert app.state()["model"] == "test-local" and config.load()["chat_provider"] == "openai_local"
        with pytest.raises(ValueError):
            app.provider_operation({"action":"save", "provider":"openai_local", "url":"https://cloud.invalid", "model":"other"})
        assert cfg["local_chat_model"] == "test-local"
        cfg["lockdown"]=True
        with pytest.raises(ValueError, match="Lockdown"):
            app.provider_operation({"action":"save", "provider":"ollama"})
        cfg["lockdown"]=False
        app.provider_operation({"action":"save", "provider":"ollama"})
        assert all(cfg[key] == value for key,value in old.items())
        assert ("http","127.0.0.1",8081) not in net.allowed_endpoints(cfg)
    finally:
        app.memory.db.close()


def test_unknown_provider_never_falls_back_to_ollama(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg["chat_provider"] = "unsupported"
    brain = Brain(cfg, db)
    monkeypatch.setattr(net, "urlopen", lambda *a, **kw: pytest.fail("Unexpected fallback request"))
    assert "Unknown chat provider" in brain.ask("Hello")


def test_malformed_tool_response_does_not_queue_an_action(isolated_app, local_server):
    cfg, db, _, _ = isolated_app
    provider_config(cfg, local_server)
    brain = Brain(cfg, db)
    local_server.replies.append(completion(calls=[{"id":"x", "type":"function", "function":{
        "name":"power", "arguments":'{"action":"shutdown"'}}], reason="tool_calls"))
    answer = brain.ask("Review an action")
    assert "malformed tool arguments" in answer and brain.ctx.pending is None
    assert len(local_server.requests) == 1
