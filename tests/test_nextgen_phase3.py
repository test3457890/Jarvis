"""Phase 3 Next-Generation tests:
- Clipboard history manager with secret redaction, pinning & search (clipboard.py)
- Desktop window enumeration, screenshot organizer & safe project scaffolding (desktop.py)
- Approved Playwright browser URL SSRF & offline/Lockdown guards (browser_auto.py)
"""
import pytest

from jarvis import browser_auto, clipboard, config, desktop, memory, net, undo


def test_clipboard_history_redacts_pins_and_searches(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    mem = memory.Memory()

    c1 = clipboard.capture(mem, "Meeting notes about Jarvis 2.0 architecture")
    c2 = clipboard.capture(mem, "Secret token sk-1234567890abcdef12345678 in snippet")
    assert "sk-1234567890" not in c2["text"]
    assert "[REDACTED]" in c2["text"]

    clipboard.set_pinned(mem, c1["id"], True)
    pinned = clipboard.list_entries(mem, pinned_only=True)
    assert len(pinned) == 1 and pinned[0]["id"] == c1["id"]

    hits = clipboard.search_entries(mem, "architecture")
    assert len(hits) == 1 and hits[0]["id"] == c1["id"]

    clipboard.delete_entry(mem, c2["id"])
    assert len(clipboard.list_entries(mem)) == 1


def test_desktop_windows_screenshots_and_safe_scaffolding(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)
    monkeypatch.setattr(memory, "DB_PATH", tmp_path / "mem.db")
    mem = memory.Memory()

    # Window enumeration must never crash (returns list on Windows or [] elsewhere)
    wins = desktop.list_windows(10)
    assert isinstance(wins, list)

    # Screenshot tagging inside APP_DIR/screenshots
    sdir = desktop.screenshots_dir()
    (sdir / "sample.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    desktop.tag_screenshot(mem, "sample.png", ["hud", "audit"])
    shots = desktop.list_screenshots(mem)
    assert len(shots) == 1 and shots[0]["tags"] == ["hud", "audit"]

    # Safe project scaffolding strictly inside code_dir
    cfg = dict(config.DEFAULTS, code_dir=str(tmp_path / "code"))
    undo.JOURNAL.clear()
    res = desktop.scaffold_project(cfg, "demo_cli", template="python-cli")
    assert (tmp_path / "code" / "demo_cli" / "main.py").is_file()
    assert res["template"] == "python-cli"
    assert any(e["tool"] == "scaffold_project" for e in undo.JOURNAL.list_entries())

    # Rejects traversal, reserved Windows names, and overwrite
    for bad in ("../escape", "CON", "demo_cli"):
        with pytest.raises(ValueError):
            desktop.scaffold_project(cfg, bad)


def test_browser_auto_enforces_offline_lockdown_and_ssrf_blocks():
    cfg = dict(config.DEFAULTS)
    with pytest.raises(net.NetworkBlockedError):
        browser_auto.inspect_page(cfg, "https://example.com")

    cfg["allow_internet_tools"] = True
    cfg["lockdown"] = True
    with pytest.raises(net.NetworkBlockedError):
        browser_auto.inspect_page(cfg, "https://example.com")

    # Non-HTTPS, credentials, loopback, and private IPs MUST be blocked
    for bad_url in (
        "http://example.com",
        "https://user:pass@example.com",
        "https://127.0.0.1/",
        "https://192.168.1.1/",
        "https://169.254.169.254/latest/meta-data/",
    ):
        with pytest.raises(net.NetworkBlockedError):
            browser_auto.validate_public_https_url(bad_url)
