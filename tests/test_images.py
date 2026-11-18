import base64
import io
import json

import pytest
from PIL import Image

from jarvis import images, net, secure, skills
from jarvis.brain import Brain


def _png():
    buffer = io.BytesIO()
    Image.new("RGB", (32, 64), "navy").save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def test_image_search_needs_approval_and_exposes_safe_sources(isolated_app, monkeypatch):
    cfg, db, _, _ = isolated_app
    cfg.update(allow_internet_tools=True, allow_web_search=True)
    monkeypatch.setattr(secure, "get_secret", lambda key: "fake" if key == "brave_search_key" else "")
    brain = Brain(cfg, db)
    emitted = []
    brain.ctx.on_images = emitted.extend
    requests = []

    def respond(req, config, **kwargs):
        requests.append(req.full_url)
        assert kwargs["allow_redirects"] is False and "safesearch=strict" in req.full_url
        return io.BytesIO(json.dumps({"results": [
            {"title": "<b>Mountain</b>", "url": "https://example.org/photo",
             "thumbnail": {"src": "http://127.0.0.1:9000/not-this"}},
            {"title": "Ignore", "url": "javascript:void(0)"},
        ]}).encode())

    monkeypatch.setattr(net, "urlopen", respond)
    assert "confirm image search" in brain.ask("/images mountain")
    assert "confirm image search" in brain.ask("yes")
    assert not requests
    assert "https://example.org/photo" in brain.ask("confirm image search")
    assert len(requests) == 1
    assert emitted == [{"title": "Mountain", "link": "https://example.org/photo", "thumbnail": None}]
    assert "image_search" not in {x["function"]["name"] for x in skills.tool_schemas(cfg)}


def test_lookup_and_generation_use_loopback_and_save_png(isolated_app, monkeypatch):
    cfg, _, _, app_dir = isolated_app
    cfg["image_generation_url"] = "http://127.0.0.1:7860"
    calls = []
    png = _png()

    def respond(req, config, **kwargs):
        assert kwargs["allow_redirects"] is False and kwargs["bypass_proxy"] is True
        assert net.check_url(req.full_url, config)
        calls.append(json.loads(req.data))
        data = ({"message": {"content": "A navy rectangle."}} if req.full_url.endswith("/api/chat")
                else {"images": [png]})
        return io.BytesIO(json.dumps(data).encode())

    monkeypatch.setattr(net, "urlopen", respond)
    assert images.describe(cfg, png, "What colour is it?") == {"text": "A navy rectangle."}
    assert calls[0]["messages"][1]["images"] and "tools" not in calls[0]
    result = images.generate(cfg, "a navy rectangle", "high")
    assert calls[1]["width"] == 1024 and calls[1]["steps"] == 32
    generated = app_dir / "images" / result["name"]
    assert generated.read_bytes() == base64.b64decode(result["image"])
    Image.open(generated).verify()
    assert not cfg["allow_internet_tools"]


def test_private_image_tools_reject_remote_hosts_and_bad_content(isolated_app):
    cfg, _, _, _ = isolated_app
    for endpoint in ("http://example.org:7860", "http://127.0.0.1:7860/extra",
                     "http://something@127.0.0.1:7860", "https://127.0.0.1:7860"):
        assert net.local_image_endpoint(endpoint) is None
    cfg["vision_url"] = "http://example.org:11434"
    with pytest.raises(ValueError, match="loopback"):
        images.describe(cfg, _png(), "")
    with pytest.raises(ValueError, match="unsupported format"):
        images.describe(cfg, base64.b64encode(b"<svg/>").decode(), "")
    with pytest.raises(ValueError, match="High"):
        images.generate(cfg, "test", ["high"])
