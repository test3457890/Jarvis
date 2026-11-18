"""Tests for lockdown mode, per-skill permissions, comms rate limits, and HUD auth."""
import json
import socket
import urllib.error
import urllib.request

from jarvis import __main__ as main_mod, skills, webui


def test_lockdown_disables_all_risky_skills(isolated_app):
    cfg, _, ctx, _ = isolated_app
    cfg["lockdown"] = True

    names = {t["function"]["name"] for t in skills.tool_schemas(cfg)}
    for name, meta in skills.SKILLS.items():
        if meta["risky"]:
            assert name not in names, f"Risky skill {name} exposed in lockdown"
            res = skills.run(ctx, name, {}, confirmed=True)
            assert "Lockdown mode is active" in res


def test_per_skill_permissions_never_allow_risky_bypass(isolated_app):
    cfg, _, ctx, _ = isolated_app
    # Even if someone tries to set a risky skill to "allowed" in config, it MUST stay "ask".
    cfg["skill_permissions"] = {
        "phone_call": "allowed",
        "run_code": "allowed",
        "tell_joke": "off",
        "calculate": "ask",
    }
    assert skills.permission_level(cfg, "phone_call") == "ask"
    assert skills.permission_level(cfg, "run_code") == "ask"
    assert skills.permission_level(cfg, "tell_joke") == "off"
    assert skills.permission_level(cfg, "calculate") == "ask"

    # Off skill is hidden and blocked
    names = {t["function"]["name"] for t in skills.tool_schemas(cfg)}
    assert "tell_joke" not in names
    assert "disabled" in skills.run(ctx, "tell_joke", {})

    # Safe skill set to "ask" requires confirmation
    res = skills.run(ctx, "calculate", {"expression": "2+2"})
    assert "NOT DONE YET" in res
    assert ctx.pending is not None

    # Risky skill still requires confirmation despite "allowed" in config
    ctx.pending = None
    res2 = skills.run(ctx, "phone_call", {"who": "5551234567"})
    assert "NOT DONE YET" in res2
    assert ctx.pending is not None


def test_comms_rate_limit(isolated_app, monkeypatch):
    cfg, _, ctx, _ = isolated_app
    cfg["comms_rate_limit_max"] = 2
    cfg["comms_rate_limit_window_seconds"] = 300
    monkeypatch.setattr("os.startfile", lambda *a, **kw: None)

    r1 = skills.run(ctx, "phone_call", {"who": "5551112222"}, confirmed=True)
    r2 = skills.run(ctx, "phone_call", {"who": "5551112222"}, confirmed=True)
    r3 = skills.run(ctx, "phone_call", {"who": "5551112222"}, confirmed=True)
    assert "Calling" in r1
    assert "Calling" in r2
    assert "Rate limit reached" in r3


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_hud_auth_and_lockdown_toggle(isolated_app):
    cfg, _, _, _ = isolated_app
    app = main_mod.App(cfg, use_voice=False)
    port = _free_port()
    server = webui.serve(app, port)
    try:
        # Grab session key from "/"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=5) as r:
            html = r.read().decode()
        key = html.split("const KEY = ")[1].split(";")[0].strip("\"'")

        # Missing key -> 403
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/api/state", timeout=5)
            assert False, "Expected 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # Spoofed Host -> 403
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state",
                                     headers={"Host": "evil.com", "X-Jarvis-Key": key})
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # Foreign Origin -> 403
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/state",
                                     headers={"Origin": "https://evil.com", "X-Jarvis-Key": key})
        try:
            urllib.request.urlopen(req, timeout=5)
            assert False, "Expected 403"
        except urllib.error.HTTPError as e:
            assert e.code == 403

        # Toggle lockdown via HUD endpoint
        app.brain.ctx.pending = {"name": "phone_call", "args": {"who": "5551234567"}, "preview": "call"}
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/toggle",
            data=json.dumps({"what": "lockdown"}).encode(),
            headers={"Content-Type": "application/json", "X-Jarvis-Key": key,
                     "Origin": f"http://127.0.0.1:{port}"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            st = json.loads(r.read().decode())
        assert st["lockdown"] is True
        assert app.brain.ctx.pending is None
    finally:
        server.shutdown()
        server.server_close()
