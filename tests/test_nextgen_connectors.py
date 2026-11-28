"""Step 3 Completion — Mocked Integration Tests for Official External Connectors & OAuth 2.0.

NOTE: These tests use mocked HTTP responses to verify OAuth PKCE token exchange/refresh,
allowlist enforcement, DPAPI storage, write-scope boundaries, and API response parsing.
Live account verification requires user-owned OAuth Client IDs and Bot tokens.
"""
import io
import json
import urllib.parse
import pytest

from jarvis import config, net, secure, service_adapters


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *_a):
        self.close()


def test_oauth_pkce_exchange_and_refresh_store_secrets_in_dpapi(monkeypatch):
    vault = {"oauth_google_client_id": "client-123"}
    monkeypatch.setattr(secure, "get_secret", lambda k, default="": vault.get(k, default))
    monkeypatch.setattr(secure, "has_secret", lambda k: bool(vault.get(k)))
    monkeypatch.setattr(secure, "set_secret", lambda k, v: vault.__setitem__(k, v))

    def fake_urlopen(req, cfg, **_kw):
        net.check_url(req.full_url, cfg)
        body = req.data.decode("utf-8")
        if "authorization_code" in body:
            return _FakeResp(json.dumps({"access_token": "acc-1", "refresh_token": "ref-1", "expires_in": 3600}).encode())
        return _FakeResp(json.dumps({"access_token": "acc-2", "expires_in": 3600}).encode())

    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    cfg = dict(config.DEFAULTS, allow_internet_tools=True)

    ex = service_adapters.oauth_exchange_code(
        cfg, "google_workspace", code="auth-code", code_verifier="verif", redirect_uri="http://127.0.0.1:8765/cb"
    )
    assert ex["ok"] is True
    assert vault["oauth_google_token"] == "acc-1"
    assert vault["oauth_google_refresh"] == "ref-1"

    ref = service_adapters.oauth_refresh_token(cfg, "google_workspace")
    assert ref["ok"] is True
    assert vault["oauth_google_token"] == "acc-2"


def test_mocked_google_ms365_teams_slack_discord_and_home_assistant(monkeypatch):
    vault = {
        "oauth_google_token": "g-tok",
        "oauth_microsoft_token": "m-tok",
        "slack_bot_token": "xoxb-tok",
        "discord_bot_token": "disc-tok",
        "home_assistant_token": "ha-tok",
    }
    monkeypatch.setattr(secure, "get_secret", lambda k, default="": vault.get(k, default))
    monkeypatch.setattr(secure, "has_secret", lambda k: bool(vault.get(k)))

    def fake_urlopen(req, cfg, **_kw):
        net.check_url(req.full_url, cfg)
        u = req.full_url
        if "calendar/v3" in u:
            return _FakeResp(json.dumps({"items": [{"id": "e1", "summary": "Standup", "start": {"dateTime": "2026-11-28T09:00Z"}}]}).encode())
        if "gmail/v1" in u:
            return _FakeResp(json.dumps({"messages": [{"id": "m1", "threadId": "t1"}]}).encode())
        if "me/messages" in u:
            return _FakeResp(json.dumps({"value": [{"id": "o1", "subject": "Quarterly Review", "receivedDateTime": "2026-11-28"}]}).encode())
        if "joinedTeams" in u:
            return _FakeResp(json.dumps({"value": [{"id": "tm1", "displayName": "Engineering"}]}).encode())
        if urllib.parse.urlsplit(u).hostname == "slack.com":
            return _FakeResp(json.dumps({"ok": True, "channels": [{"id": "C1", "name": "general"}]}).encode())
        if urllib.parse.urlsplit(u).hostname == "discord.com":
            return _FakeResp(json.dumps([{"id": "d1", "author": {"username": "alice"}, "content": "Hello team"}]).encode())
        if "/api/states" in u:
            return _FakeResp(json.dumps([{"entity_id": "light.office", "state": "on"}]).encode())
        if "/api/services/" in u:
            return _FakeResp(b"{}")
        raise AssertionError(f"Unexpected URL: {u}")

    monkeypatch.setattr(net, "urlopen", fake_urlopen)
    cfg = dict(config.DEFAULTS, allow_internet_tools=True, home_assistant_url="http://127.0.0.1:8123")

    assert service_adapters.google_calendar_upcoming(cfg)[0]["summary"] == "Standup"
    assert service_adapters.google_gmail_list(cfg)[0]["id"] == "m1"
    assert service_adapters.ms365_messages_list(cfg)[0]["subject"] == "Quarterly Review"
    assert service_adapters.ms_teams_joined_list(cfg)[0]["name"] == "Engineering"
    assert service_adapters.slack_channels_list(cfg)[0]["name"] == "general"
    assert service_adapters.discord_channel_messages(cfg, "1234567890")[0]["content"] == "Hello team"
    assert service_adapters.home_assistant_states(cfg)[0]["entity_id"] == "light.office"

    # Home Assistant writes MUST fail closed unless connector_write_permissions enables them
    with pytest.raises(PermissionError, match="write actions are disabled"):
        service_adapters.home_assistant_call_service(cfg, domain="light", service="turn_off", entity_id="light.office")
    cfg["connector_write_permissions"] = {"home_assistant": True}
    assert service_adapters.home_assistant_call_service(cfg, domain="light", service="turn_off", entity_id="light.office")["ok"] is True

    # Connection tester works cleanly
    assert service_adapters.test_connection(cfg, "slack")["ok"] is True
    assert service_adapters.test_connection(cfg, "google_workspace")["ok"] is True
