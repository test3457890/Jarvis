"""Phase 1 Next-Generation foundation tests:
- Real-time system vitals & process telemetry (telemetry.py)
- 8+ AI provider registry, privacy modes, complexity routing & USD cost estimation (providers.py, cloudprovider.py, net.py)
- Policy-enforced, audited fast-path commands (fastpath.py, brain.py)
- T0-T3 risk tiers, dry-run inspection, tool execution history, stale-target guard & Undo Journal (skills.py, undo.py)
- Authenticated loopback HTTP API boundaries for all new /api/* endpoints (webui.py)
"""
import json
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from jarvis import (
    __main__ as jarvis_main,
    cloudprovider,
    config,
    fastpath,
    memory,
    net,
    providers,
    secure,
    skills,
    telemetry,
    undo,
    webui,
)
from jarvis.brain import Brain


# ------------------------------------------------------------------ Telemetry
def test_telemetry_snapshot_and_history():
    telemetry.clear_history()
    snap1 = telemetry.snapshot(include_processes=True)
    snap2 = telemetry.snapshot(include_processes=False)
    assert snap1["os"]
    assert snap1["cpu"]["logical_cores"] >= 1
    assert "memory" in snap1 and "disk" in snap1 and "network" in snap1
    assert isinstance(snap1["gpus"], list)
    assert isinstance(snap1["processes"], list)
    assert len(snap2["history"]) == 2
    assert snap2["history"][-1]["ts"] >= snap2["history"][0]["ts"]


# ------------------------------------------------------------------ Providers & Privacy
def test_providers_catalog_and_local_privacy_mode(monkeypatch):
    cfg = dict(config.DEFAULTS)
    cfg["allow_internet_tools"] = True
    cfg["allow_cloud_provider"] = True
    cfg["cloud_provider"] = "groq"
    cfg["privacy_mode"] = "local"
    monkeypatch.setattr(secure, "has_secret", lambda k: k == "cloud_groq_key")

    # Local-only privacy mode MUST block cloud providers everywhere
    assert cloudprovider.ready(cfg) is False
    assert ("https", "api.groq.com", 443) not in net.allowed_endpoints(cfg)
    with pytest.raises(ValueError, match="privacy_mode"):
        cloudprovider.ask(cfg, "hello")

    summary = providers.health_summary(cfg, probe_local=False)
    ids = {p["id"] for p in summary["providers"]}
    assert {"ollama", "lmstudio", "openai_local", "openai", "anthropic", "gemini", "nvidia", "openrouter", "groq"} <= ids
    groq_row = next(p for p in summary["providers"] if p["id"] == "groq")
    assert "Local-Only" in groq_row["state"]

    # Switching to hybrid unlocks explicit per-request allowlist
    cfg["privacy_mode"] = "hybrid"
    assert cloudprovider.ready(cfg) is True
    assert ("https", "api.groq.com", 443) in net.allowed_endpoints(cfg)


def test_custom_openai_cloud_provider_requires_https_and_key(monkeypatch):
    cfg = dict(config.DEFAULTS)
    cfg["allow_internet_tools"] = True
    cfg["allow_cloud_provider"] = True
    cfg["privacy_mode"] = "hybrid"
    cfg["cloud_provider"] = "custom_openai"
    cfg["custom_cloud_url"] = "http://insecure.example.com/v1/chat/completions"
    monkeypatch.setattr(secure, "has_secret", lambda k: k == "cloud_custom_openai_key")
    assert cloudprovider.configured_provider(cfg) is None

    cfg["custom_cloud_url"] = "https://llm.example.com/v1/chat/completions"
    found = cloudprovider.configured_provider(cfg)
    assert found is not None
    assert found[1]["host"] == "llm.example.com"
    assert ("https", "llm.example.com", 443) in net.allowed_endpoints(cfg)


def test_complexity_classifier_and_cost_estimator():
    simple = providers.classify_complexity("What time is it?")
    assert simple["tier"] == "fast"
    assert simple["score"] < 0.35

    complex_q = providers.classify_complexity(
        "Architect and benchmark a Rust async concurrency algorithm and compare tradeoffs:\n```rust\nfn main() {}\n```"
    )
    assert complex_q["tier"] == "smart"
    assert complex_q["score"] >= 0.35
    assert "code_snippet" in complex_q["reasons"]

    # Cost estimation: local is $0.00, known cloud is accurate, unknown cloud is None (never fabricated)
    assert providers.estimate_cost("ollama", "qwen3:8b", 1000, 500) == 0.0
    assert providers.estimate_cost("lmstudio", "any-model", 1000, 500) == 0.0
    cost = providers.estimate_cost("openai", "gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.75, rel=1e-4)
    assert providers.estimate_cost("openai", "unknown-future-model", 1000, 1000) is None

    tracker = providers.UsageTracker()
    tracker.record("openai", "gpt-4o-mini", input_tokens=100_000, output_tokens=50_000, latency_s=0.42)
    tracker.record("fast_path", "calculate", input_tokens=0, output_tokens=0, latency_s=0.0, fast_path=True)
    s = tracker.summary()
    assert s["requests"] == 2
    assert s["fast_path_hits"] == 1
    assert s["input_tokens"] == 100_000
    assert s["output_tokens"] == 50_000
    assert s["estimated_cost_usd"] == pytest.approx(0.045, rel=1e-4)


# ------------------------------------------------------------------ Fast-Path
def test_fastpath_enforces_permissions_and_runs_without_llm(tmp_path):
    cfg = dict(config.DEFAULTS)
    cfg["notes_dir"] = str(tmp_path / "notes")
    Path(cfg["notes_dir"]).mkdir(parents=True, exist_ok=True)
    mem = memory.Memory(tmp_path / "mem.db")
    brain = Brain(cfg, mem)

    # Instant arithmetic without calling Ollama
    reply = brain.ask("what is 12 * 14")
    assert "168" in reply
    assert brain.model_used == "fast-path:calculate"

    # Disabling a skill in skill_permissions MUST be respected by fast-path
    cfg["skill_permissions"] = {"get_time_date": "off"}
    handled, res, tool = fastpath.try_execute(brain.ctx, "what time is it")
    assert handled is True
    assert tool == "get_time_date"
    assert "disabled" in res.lower()

    # Setting a skill to 'ask' MUST trigger confirmation preview even on fast-path
    cfg["skill_permissions"] = {"get_time_date": "ask"}
    handled, res, tool = fastpath.try_execute(brain.ctx, "what time is it")
    assert handled is True
    assert brain.ctx.pending is not None
    assert brain.ctx.pending["name"] == "get_time_date"
    brain.ctx.pending = None

    # Talk mode disables fast-path
    cfg["mode"] = "talk"
    handled, _, _ = fastpath.try_execute(brain.ctx, "what is 2 + 2")
    assert handled is False


# ------------------------------------------------------------------ Risk Tiers, Dry-Run, Stale-Target & Undo
def test_risk_tiers_dry_run_and_tool_history(tmp_path):
    cfg = dict(config.DEFAULTS)
    mem = memory.Memory(tmp_path / "mem.db")
    ctx = skills.Context(cfg, mem)

    assert skills.risk_tier("get_time_date") == "T0"
    assert skills.risk_tier("write_note") == "T1"
    assert skills.risk_tier("web_search") == "T2"
    assert skills.risk_tier("power") == "T3"

    dr = skills.dry_run(ctx, "power", {"action": "shutdown"})
    assert dr["tier"] == "T3"
    assert dr["requires_confirmation"] is True
    assert dr["ok"] is True

    cfg["lockdown"] = True
    dr_locked = skills.dry_run(ctx, "power", {"action": "shutdown"})
    assert dr_locked["ok"] is False
    assert "Lockdown" in (dr_locked["blocked_reason"] or "")

    cfg["lockdown"] = False
    skills.run(ctx, "calculate", {"expression": "6 * 7"})
    hist = skills.recent_tool_history(limit=5)
    assert hist and hist[0]["tool"] == "calculate"
    assert hist[0]["tier"] == "T0"
    assert hist[0]["status"] == "ok"


def test_stale_target_fingerprint_blocks_modified_file(tmp_path):
    target = tmp_path / "doc.txt"
    target.write_text("original", encoding="utf-8")
    fp = undo.file_fingerprint(target)
    ok, _ = undo.verify_fingerprint(target, fp)
    assert ok is True

    # Mutate file while awaiting approval
    target.write_text("tampered content!", encoding="utf-8")
    ok2, reason = undo.verify_fingerprint(target, fp)
    assert ok2 is False
    assert "modified" in reason.lower()

    # Verify skills.run() blocks confirmed execution when pending carries stale fingerprint
    cfg = dict(config.DEFAULTS)
    mem = memory.Memory(tmp_path / "mem.db")
    ctx = skills.Context(cfg, mem)
    ctx.pending = {"name": "get_time_date", "args": {}, "preview": "test", "id": "abc", "fingerprint": fp}
    out = skills.run(ctx, "get_time_date", {}, confirmed=True)
    assert "Blocked for safety" in out


def test_undo_journal_redacts_and_tracks():
    j = undo.UndoJournal(maxlen=10)
    entry = j.record(
        category="coding",
        tool="apply_code",
        summary="Applied patch with token sk-1234567890abcdef12345678",
        target="app.py",
        undo_hint="/undo",
    )
    assert entry["undone"] is False
    assert "sk-1234567890" not in entry["summary"]
    marked = j.mark_undone(entry["id"])
    assert marked is not None and marked["undone"] is True
    assert j.list_entries()[0]["undone"] is True


# ------------------------------------------------------------------ HTTP API Boundaries
def test_phase1_http_endpoints_enforce_auth_and_lockdown(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_PATH", tmp_path / "config.json")
    cfg = dict(config.DEFAULTS)
    cfg["notes_dir"] = str(tmp_path / "notes")
    Path(cfg["notes_dir"]).mkdir(parents=True, exist_ok=True)
    config.save(cfg)

    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "memory.db")
    import re as _re
    import socket as _socket

    with _socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]

    app = jarvis_main.App(cfg, use_voice=False)
    server = webui.serve(app, port)
    base = f"http://127.0.0.1:{port}"
    with urllib.request.urlopen(base + "/", timeout=5) as resp:
        html = resp.read().decode("utf-8")
    m = _re.search(r"\bKEY\s*=\s*['\"]([^'\"]+)['\"]", html)
    assert m, "Session key not found in HUD HTML"
    key = m.group(1)
    headers = {"X-Jarvis-Key": key, "Origin": base, "Content-Type": "application/json"}

    try:
        # Unauthenticated GET must fail with 403
        for path in ("/api/vitals", "/api/providers", "/api/tools/history", "/api/undo"):
            with pytest.raises(urllib.error.HTTPError) as exc:
                urllib.request.urlopen(base + path, timeout=5)
            assert exc.value.code == 403

        # Authenticated GETs succeed
        for path in ("/api/vitals", "/api/providers", "/api/tools/history", "/api/undo"):
            req = urllib.request.Request(base + path, headers=headers)
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
                assert isinstance(data, dict)

        # Authenticated POST /api/tools/dry-run
        req = urllib.request.Request(
            base + "/api/tools/dry-run",
            data=json.dumps({"tool": "power", "args": {"action": "shutdown"}}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            dr = json.loads(resp.read())
            assert dr["tier"] == "T3"
            assert dr["requires_confirmation"] is True

        # Privacy mode update works when Lockdown is OFF, blocked when Lockdown is ON
        req = urllib.request.Request(
            base + "/api/providers",
            data=json.dumps({"action": "privacy_mode", "privacy_mode": "hybrid"}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            pdata = json.loads(resp.read())
            assert pdata["privacy_mode"] == "hybrid"

        app.cfg["lockdown"] = True
        req = urllib.request.Request(
            base + "/api/providers",
            data=json.dumps({"action": "privacy_mode", "privacy_mode": "local"}).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=5)
        assert exc.value.code == 400
    finally:
        server.shutdown()
        server.server_close()
