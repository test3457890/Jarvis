"""Phase 6 Next-Generation tests:
- Official service connector catalogue & honest credential/offline/Lockdown status
- Fail-closed Telegram & Home Assistant guards
- Curated MCP server catalogue metadata (never auto-enabled)
"""
import pytest

from jarvis import config, net, secure, service_adapters


def test_service_catalogue_reports_honest_status(monkeypatch):
    cfg = dict(config.DEFAULTS)
    monkeypatch.setattr(secure, "has_secret", lambda _k: False)
    rows = service_adapters.catalogue_status(cfg)
    ids = {r["id"] for r in rows}
    assert {"google_workspace", "microsoft_365", "microsoft_teams", "discord", "slack",
            "github", "telegram", "home_assistant", "music", "weather", "flights"} <= ids
    assert all(r["write_enabled"] is False for r in rows)

    # Offline mode reports offline for external APIs
    slack_row = next(r for r in rows if r["id"] == "slack")
    assert "Offline" in slack_row["state"]

    # Lockdown blocks all connectors
    cfg["lockdown"] = True
    locked_rows = service_adapters.catalogue_status(cfg)
    assert all("Lockdown" in r["state"] for r in locked_rows)


def test_telegram_and_home_assistant_fail_closed():
    cfg = dict(config.DEFAULTS)
    with pytest.raises(net.NetworkBlockedError):
        service_adapters.telegram_send(cfg, "12345", "hello")

    prev = service_adapters.telegram_send_preview("12345", "Token sk-1234567890abcdef12345678")
    assert "sk-1234567890" not in prev
    assert "[REDACTED]" in prev

    ha_prev = service_adapters.home_assistant_preview("light", "turn_on", "light.office")
    assert "light.turn_on" in ha_prev
    assert len(service_adapters.MCP_CATALOGUE) >= 10
