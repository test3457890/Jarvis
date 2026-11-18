import base64
import io
import json
from pathlib import Path

import pytest

from jarvis import net, online, secure, skills
from jarvis.brain import Brain


def test_talk_ignores_model_tool_calls_and_keeps_conversation(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg["mode"] = "talk"
    brain = Brain(cfg, db)
    monkeypatch.setattr(brain, "embed", lambda _: None)

    def fake_chat(messages, use_tools):
        assert not use_tools
        assert "Overheard phrase" not in messages[0]["content"]
        return {"content": "Of course, Brett.", "tool_calls": [
            {"function": {"name": "run_code", "arguments": {"filename": "one.py"}}}
        ]}

    monkeypatch.setattr(brain, "_chat", fake_chat)
    assert brain.ask("Let's chat.", "Overheard phrase") == "Of course, Brett."
    assert brain.ctx.pending is None
    assert brain.history[-2]["content"] == "Let's chat."
    assert "Talk mode" in brain.ask("/search tomorrow")


def test_coding_reviews_exact_change_then_undoes(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg["mode"] = "coding"
    brain = Brain(cfg, db)
    source = Path(cfg["code_dir"]) / "budget.py"
    source.write_bytes(b"total = 1\r\n")
    related = Path(cfg["code_dir"]) / "rules.txt"
    related.write_text("The total should be two.", encoding="utf-8")
    calls = []

    def generate(messages, model):
        calls.append(json.loads(messages[1]["content"]))
        return "```python\ntotal = 2\n```"

    monkeypatch.setattr(brain, "raw_chat", generate)
    assert "+total = 2" in brain.ask("/fix budget.py | update total | rules.txt")
    assert calls[0]["references"] == {"rules.txt": "The total should be two."}
    assert source.read_bytes() == b"total = 1\r\n"
    assert "Updated budget.py" in brain.ask("/apply")
    assert source.read_bytes() == b"total = 2\r\n"
    assert len(calls) == 1
    assert "Restored" in brain.ask("/undo")
    assert source.read_bytes() == b"total = 1\r\n"


def test_coding_rejects_a_stale_proposal(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg["mode"] = "coding"
    brain = Brain(cfg, db)
    source = Path(cfg["code_dir"]) / "budget.py"
    source.write_bytes(b"total = 1\n")
    monkeypatch.setattr(brain, "raw_chat", lambda *a, **kw: "```python\ntotal = 2\n```")
    brain.ask("/fix budget.py | update total")
    source.write_bytes(b"total = 9\n")
    assert "file changed" in brain.ask("/apply")
    assert source.read_bytes() == b"total = 9\n"


def _services(cfg, monkeypatch):
    cfg.update(allow_internet_tools=True, allow_web_search=True, github_upload_repo="owner/repo")
    tokens = {"brave_search_key": "search-test-token", "github_upload_token": "upload-test-token"}
    monkeypatch.setattr(secure, "get_secret", lambda name, default="": tokens.get(name, default))


def test_brave_search_requires_matching_confirmation(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    brain = Brain(cfg, db)
    assert "off" in brain.ask("/search sample query")
    _services(cfg, monkeypatch)
    requests = []

    def send(req, settings, purpose, allow_redirects):
        requests.append(req)
        assert purpose == "brave_search" and not allow_redirects
        assert net.check_url(req.full_url, settings)
        return io.BytesIO(json.dumps({"web": {"results": [
            {"title": "Source", "url": "https://example.org", "description": "Example answer"}
        ]}}).encode())

    monkeypatch.setattr(net, "urlopen", send)
    brain.ask("/search sample query")
    pending_id = brain.ctx.pending["id"]
    assert "expired" in brain.confirm_pending(True, expected_id="older-id")
    assert "confirm search" in brain.ask("yes")
    assert not requests
    assert "https://example.org" in brain.confirm_pending(True, expected_id=pending_id)
    assert len(requests) == 1 and "q=sample+query" in requests[0].full_url


def test_upload_is_manual_and_uses_approved_bytes(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    _services(cfg, monkeypatch)
    brain = Brain(cfg, db)
    assert "github_upload" not in {schema["function"]["name"] for schema in skills.tool_schemas(cfg)}
    path = Path(cfg["code_dir"]) / "file name.txt"
    path.write_bytes(b"first")
    requests = []

    def send(req, settings, purpose, allow_redirects):
        requests.append(req)
        assert purpose == "github_upload" and not allow_redirects
        assert req.method == "PUT"
        assert net.check_url(req.full_url, settings)
        assert req.full_url.endswith("/contents/uploads/file%20name.txt")
        assert base64.b64decode(json.loads(req.data)["content"]) == b"second"
        assert "sha" not in json.loads(req.data)
        return io.BytesIO(b'{"commit": {"sha": "testsha"}}')

    monkeypatch.setattr(net, "urlopen", send)
    assert "owner/repo" in brain.ask("/upload file name.txt")
    assert "confirm upload" in brain.ask("yes")
    path.write_bytes(b"second")
    assert "file changed" in brain.ask("confirm upload")
    assert not requests
    brain.ask("/upload file name.txt")
    assert "/blob/testsha/uploads/file%20name.txt" in brain.ask("confirm upload")
    assert len(requests) == 1


def test_api_hosts_are_opt_in_and_upload_rejects_private_paths(isolated_app, monkeypatch):
    cfg, _, ctx, _ = isolated_app
    for url in ("https://api.github.com", "https://api.search.brave.com"):
        with pytest.raises(net.NetworkBlockedError):
            net.check_url(url, cfg)

    _services(cfg, monkeypatch)
    for name in (".env", "../private.txt", "NUL.txt"):
        assert "uploads/" not in online.prepare_upload(ctx, name)
        assert ctx.pending is None
    with pytest.raises(net.NetworkBlockedError):
        net.check_url("https://unconfigured.example", cfg)


def test_hud_mode_theme_and_confirmation(isolated_app, monkeypatch):
    import socket
    import urllib.error
    import urllib.request

    from jarvis import __main__ as main, config, webui

    cfg, _, _, _ = isolated_app
    _services(cfg, monkeypatch)
    cfg["speak_replies"] = False
    app = main.App(cfg, use_voice=False)
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    server = webui.serve(app, port)
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(url, timeout=5) as data:
            html = data.read().decode()
            assert "fonts.googleapis.com" not in data.headers["Content-Security-Policy"]
        key = html.split('const KEY = "')[1].split('"')[0]

        def post(path, value):
            request = urllib.request.Request(
                url + "/api/" + path, data=json.dumps(value).encode(),
                headers={"Content-Type": "application/json", "X-Jarvis-Key": key},
            )
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.load(response)

        assert post("preferences", {"key": "theme", "value": "light"})["theme"] == "light"
        assert post("preferences", {"key": "mode", "value": "coding"})["mode"] == "coding"
        assert config.load()["theme"] == "light"
        brain = app.brain
        brain.ask("/search example")
        pending_id = brain.ctx.pending["id"]
        assert "expired" in post("confirm", {"yes": True, "id": "old"})["result"]
        assert "Cancelled" in post("confirm", {"yes": False, "id": pending_id})["result"]
        brain.ask("/search example")
        assert post("preferences", {"key": "mode", "value": "talk"})["pending"] is None
        with urllib.request.urlopen(url, timeout=5) as page:
            assert b'data-theme="light" data-mode="talk"' in page.read()
        with pytest.raises(urllib.error.HTTPError) as error:
            post("preferences", {"key": "theme", "value": "invalid"})
        assert error.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
