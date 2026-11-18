"""Central network allowlist tests (fail-closed)."""
import pytest

from jarvis import net


def test_allowlist_permits_local_ollama_and_nomad(isolated_app):
    cfg, _, _, _ = isolated_app
    assert net.check_url("http://127.0.0.1:11434/api/chat", cfg)
    assert net.check_url("http://127.0.0.1:8090/search?pattern=test", cfg)
    assert net.check_tcp("127.0.0.1", 8080, cfg) == ("127.0.0.1", 8080)


def test_allowlist_blocks_arbitrary_urls_and_schemes(isolated_app):
    cfg, _, _, _ = isolated_app
    for bad in (
        "https://evil.example.com/exfil",
        "http://169.254.169.254/latest/meta-data/",
        "file:///C:/Windows/win.ini",
        "ftp://example.com/file",
        "https://en.wikipedia.org/api/rest_v1/page/summary/Python",  # internet tools off by default
    ):
        with pytest.raises(net.NetworkBlockedError):
            net.check_url(bad, cfg, purpose="test")


def test_wikipedia_allowed_only_when_internet_tools_enabled(isolated_app):
    cfg, _, _, _ = isolated_app
    cfg["allow_internet_tools"] = True
    assert net.check_url("https://en.wikipedia.org/api/rest_v1/page/summary/Python", cfg)
    with pytest.raises(net.NetworkBlockedError):
        net.check_url("https://other-site.org/api", cfg)


def test_canvas_host_allowed_only_when_configured(isolated_app, mock_canvas_secret):
    cfg, _, _, _ = isolated_app
    with pytest.raises(net.NetworkBlockedError):
        net.check_url("https://canvas.university.edu/feeds/calendars/user_123.ics", cfg)

    mock_canvas_secret("https://canvas.university.edu/feeds/calendars/user_123.ics")
    assert net.check_url("https://canvas.university.edu/feeds/calendars/user_123.ics", cfg)
    assert net.check_url("https://canvas.university.edu/api/v1/planner/items", cfg)
    with pytest.raises(net.NetworkBlockedError):
        net.check_url("https://evil.university.edu/api/v1/planner/items", cfg)


def test_tcp_and_smtp_fail_closed(isolated_app):
    cfg, _, _, _ = isolated_app
    with pytest.raises(net.NetworkBlockedError):
        net.check_tcp("8.8.8.8", 443, cfg)
    with pytest.raises(net.NetworkBlockedError):
        net.check_tcp("127.0.0.1", 22, cfg)
    with pytest.raises(net.NetworkBlockedError):
        net.check_smtp("smtp.gmail.com", cfg)  # SMTP not configured
