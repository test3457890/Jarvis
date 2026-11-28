"""Official Service Connectors Registry & Curated MCP Server Catalogue (Phase 6).

Security rules:
- Uses official APIs and OAuth 2.0 PKCE / DPAPI-stored tokens only.
- Never assumes a consumer ChatGPT subscription grants OpenAI API access.
- Every connector is disabled / read-only by default, respects offline mode & Lockdown,
  and never exposes raw credentials in status outputs.
- Curated MCP servers are metadata references only; nothing is installed or enabled
  without explicit user registration and capability approval in mcp_client.py.
"""
import json
import urllib.parse
from urllib.error import HTTPError, URLError
from urllib.request import Request

from . import net, secure

MAX_API_BYTES = 500_000

OAUTH_TOKEN_ENDPOINTS = {
    "google_workspace": {
        "token_url": "https://oauth2.googleapis.com/token",
        "token_secret": "oauth_google_token",
        "refresh_secret": "oauth_google_refresh",
        "client_id_secret": "oauth_google_client_id",
    },
    "microsoft_365": {
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "token_secret": "oauth_microsoft_token",
        "refresh_secret": "oauth_microsoft_refresh",
        "client_id_secret": "oauth_microsoft_client_id",
    },
}

SERVICE_CATALOGUE = {
    "google_workspace": {
        "label": "Google Workspace (Gmail, Calendar, Drive)",
        "auth": "oauth2_pkce",
        "secret_key": "oauth_google_token",
        "host": "www.googleapis.com",
        "read_scopes": ["gmail.readonly", "calendar.readonly", "drive.readonly"],
        "write_scopes": ["gmail.compose", "calendar.events"],
        "requires_credentials": "Google Cloud Desktop OAuth Client ID",
    },
    "microsoft_365": {
        "label": "Microsoft 365 (Outlook, OneDrive, Calendar)",
        "auth": "oauth2_pkce",
        "secret_key": "oauth_microsoft_token",
        "host": "graph.microsoft.com",
        "read_scopes": ["Mail.Read", "Calendars.Read", "Files.Read"],
        "write_scopes": ["Mail.Send", "Calendars.ReadWrite"],
        "requires_credentials": "Azure App Registration Client ID",
    },
    "microsoft_teams": {
        "label": "Microsoft Teams (Graph API)",
        "auth": "oauth2_pkce",
        "secret_key": "oauth_microsoft_token",
        "host": "graph.microsoft.com",
        "read_scopes": ["ChannelMessage.Read.All"],
        "write_scopes": ["ChannelMessage.Send"],
        "requires_credentials": "Azure App Registration with Teams Graph scopes",
    },
    "discord": {
        "label": "Discord Official API",
        "auth": "dpapi_token",
        "secret_key": "discord_bot_token",
        "host": "discord.com",
        "read_scopes": ["messages.read"],
        "write_scopes": ["messages.send"],
        "requires_credentials": "Discord Bot Token (DPAPI)",
    },
    "slack": {
        "label": "Slack Web API",
        "auth": "dpapi_token",
        "secret_key": "slack_bot_token",
        "host": "slack.com",
        "read_scopes": ["channels:history", "channels:read"],
        "write_scopes": ["chat:write"],
        "requires_credentials": "Slack Bot OAuth Token (DPAPI)",
    },
    "github": {
        "label": "GitHub REST API",
        "auth": "dpapi_token",
        "secret_key": "github_upload_token",
        "host": "api.github.com",
        "read_scopes": ["repo:read", "issues:read", "pull_requests:read"],
        "write_scopes": ["issues:write", "contents:write"],
        "requires_credentials": "GitHub Personal Access Token (DPAPI)",
    },
    "telegram": {
        "label": "Telegram Bot API",
        "auth": "dpapi_token",
        "secret_key": "telegram_bot_token",
        "host": "api.telegram.org",
        "read_scopes": ["updates.read"],
        "write_scopes": ["messages.send"],
        "requires_credentials": "Telegram Bot Token (DPAPI)",
    },
    "home_assistant": {
        "label": "Home Assistant REST API",
        "auth": "dpapi_token",
        "secret_key": "home_assistant_token",
        "host": "local_or_https",
        "read_scopes": ["states.read"],
        "write_scopes": ["services.call"],
        "requires_credentials": "Home Assistant URL + Long-Lived Access Token (DPAPI)",
    },
    "music": {
        "label": "Music Playback & Official Media APIs",
        "auth": "local_or_oauth",
        "secret_key": "spotify_oauth_token",
        "host": "api.spotify.com",
        "read_scopes": ["user-read-playback-state"],
        "write_scopes": ["user-modify-playback-state"],
        "requires_credentials": "Local media keys (no key) or Spotify OAuth Client ID",
    },
    "weather": {
        "label": "National Weather Service (NWS)",
        "auth": "public_api",
        "secret_key": "",
        "host": "api.weather.gov",
        "read_scopes": ["forecast.read"],
        "write_scopes": [],
        "requires_credentials": "None (requires Internet ON & coordinate approval)",
    },
    "flights": {
        "label": "Public Flight Tracking (OpenSky)",
        "auth": "public_api",
        "secret_key": "",
        "host": "opensky-network.org",
        "read_scopes": ["states.read"],
        "write_scopes": [],
        "requires_credentials": "None (requires Internet ON & explicit approval)",
    },
}

MCP_CATALOGUE = [
    {"id": "filesystem", "name": "Filesystem MCP", "capability": "read_only", "description": "Read-only file inspection inside user-approved directories."},
    {"id": "git", "name": "Git MCP", "capability": "read_only", "description": "Inspect local Git status, log, and diffs."},
    {"id": "sqlite", "name": "SQLite MCP", "capability": "read_only", "description": "Query local SQLite databases."},
    {"id": "memory", "name": "Knowledge Graph Memory MCP", "capability": "write_or_effect", "description": "Structured entity/relation memory store."},
    {"id": "github", "name": "GitHub MCP", "capability": "write_or_effect", "description": "Official GitHub repository, issue, and PR tools (requires PAT)."},
    {"id": "fetch", "name": "Web Fetch MCP", "capability": "read_only", "description": "Fetch explicitly approved public web pages."},
    {"id": "slack", "name": "Slack MCP", "capability": "write_or_effect", "description": "Slack workspace channels and messages (requires Slack token)."},
    {"id": "google-drive", "name": "Google Drive MCP", "capability": "read_only", "description": "Search and read Google Drive files (requires OAuth)."},
    {"id": "postgres", "name": "PostgreSQL MCP", "capability": "read_only", "description": "Read-only schema inspection and SQL queries."},
    {"id": "time", "name": "Time & Timezone MCP", "capability": "read_only", "description": "Timezone conversion and scheduling math."},
]


def catalogue_status(cfg: dict) -> list[dict]:
    """Report honest local configuration status for every official service connector."""
    internet = bool(cfg.get("allow_internet_tools"))
    lockdown = bool(cfg.get("lockdown"))
    write_perms = cfg.get("connector_write_permissions") or {}
    rows = []
    for cid, spec in SERVICE_CATALOGUE.items():
        has_cred = True if spec["auth"] == "public_api" else bool(spec["secret_key"] and secure.has_secret(spec["secret_key"]))
        if lockdown:
            state = "Blocked (Lockdown ON)"
        elif not internet and spec["host"] != "local_or_https":
            state = "Offline (Internet OFF)"
        elif not has_cred:
            state = f"Needs credentials ({spec['requires_credentials']})"
        else:
            state = "Configured (read-only default; writes require approval)"
        rows.append({
            "id": cid,
            "label": spec["label"],
            "auth": spec["auth"],
            "host": spec["host"],
            "configured": has_cred,
            "write_enabled": bool(write_perms.get(cid, False)) and not lockdown,
            "state": state,
            "read_scopes": spec["read_scopes"],
            "write_scopes": spec["write_scopes"],
        })
    return rows


def telegram_send_preview(chat_id: str, text: str) -> str:
    clean = secure.redact(str(text or "").strip())
    if not chat_id or not clean:
        raise ValueError("Provide a Telegram chat_id and non-empty message.")
    return f"send a Telegram message to chat '{chat_id}' ({len(clean)} chars): \"{clean[:160]}\""


def telegram_send(cfg: dict, chat_id: str, text: str) -> dict:
    """Send an explicitly approved Telegram message via official Bot API (fail-closed)."""
    if not cfg.get("allow_internet_tools") or cfg.get("lockdown"):
        raise net.NetworkBlockedError("Telegram requires Internet ON and Lockdown OFF.")
    token = secure.get_secret("telegram_bot_token")
    if not token:
        raise ValueError("Telegram bot token is not configured in DPAPI secrets.")
    clean = str(text or "").strip()[:4000]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    req = Request(
        url,
        data=json.dumps({"chat_id": str(chat_id), "text": clean}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with net.urlopen(req, cfg, timeout=15, purpose="telegram_send", allow_redirects=False) as resp:
        data = json.loads(resp.read(100_000))
    secure.audit("telegram_sent", {"chat_id": str(chat_id), "chars": len(clean)})
    return {"ok": bool(data.get("ok")), "chat_id": str(chat_id)}


def home_assistant_preview(domain: str, service: str, entity_id: str) -> str:
    if not domain or not service or not entity_id:
        raise ValueError("Provide domain, service, and entity_id.")
    return f"call Home Assistant service '{domain}.{service}' on entity '{entity_id}'"


# ------------------------------------------------------------------ Shared HTTP Helper
def _api_json(cfg: dict, url: str, *, method: str = "GET", headers: dict | None = None, body: bytes | None = None, purpose: str = "connector") -> dict | list:
    if not cfg.get("allow_internet_tools") or cfg.get("lockdown"):
        raise net.NetworkBlockedError("External connector requests require Internet ON and Lockdown OFF.")
    req = Request(url, data=body, headers=headers or {}, method=method)
    try:
        with net.urlopen(req, cfg, timeout=15, purpose=purpose, allow_redirects=False) as resp:
            raw = resp.read(MAX_API_BYTES + 1)
    except HTTPError as err:
        raise ValueError(f"Service returned HTTP {err.code}. Check token scopes and account access.") from None
    except URLError as err:
        raise ValueError(f"Could not reach service: {err.reason}") from None
    if len(raw) > MAX_API_BYTES:
        raise ValueError("Service response exceeded the 500 KB safety limit.")
    return json.loads(raw or b"{}")


# ------------------------------------------------------------------ OAuth 2.0 PKCE Exchange & Refresh
def oauth_exchange_code(cfg: dict, provider: str, *, code: str, code_verifier: str, redirect_uri: str) -> dict:
    """Exchange an OAuth 2.0 PKCE authorization code for DPAPI-stored access & refresh tokens."""
    if provider not in OAUTH_TOKEN_ENDPOINTS:
        raise ValueError(f"Unsupported OAuth provider '{provider}'.")
    spec = OAUTH_TOKEN_ENDPOINTS[provider]
    client_id = secure.get_secret(spec["client_id_secret"])
    if not client_id:
        raise ValueError(f"Configure {spec['client_id_secret']} in DPAPI secrets first.")
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": client_id,
        "code": str(code or "").strip(),
        "code_verifier": str(code_verifier or "").strip(),
        "redirect_uri": str(redirect_uri or "").strip(),
    }).encode("utf-8")
    data = _api_json(
        cfg, spec["token_url"], method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=form, purpose=f"oauth_exchange_{provider}",
    )
    access = str(data.get("access_token") or "")
    if not access:
        raise ValueError("OAuth token endpoint did not return an access_token.")
    secure.set_secret(spec["token_secret"], access)
    if data.get("refresh_token"):
        secure.set_secret(spec["refresh_secret"], str(data["refresh_token"]))
    secure.audit("oauth_token_exchanged", {"provider": provider, "has_refresh": bool(data.get("refresh_token"))})
    return {"ok": True, "provider": provider, "expires_in": data.get("expires_in"), "scope": data.get("scope", "")}


def oauth_refresh_token(cfg: dict, provider: str) -> dict:
    """Refresh an expired OAuth 2.0 access token using the DPAPI-stored refresh token."""
    if provider not in OAUTH_TOKEN_ENDPOINTS:
        raise ValueError(f"Unsupported OAuth provider '{provider}'.")
    spec = OAUTH_TOKEN_ENDPOINTS[provider]
    client_id = secure.get_secret(spec["client_id_secret"])
    refresh = secure.get_secret(spec["refresh_secret"])
    if not client_id or not refresh:
        raise ValueError(f"Missing client_id or refresh token for {provider}.")
    form = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "client_id": client_id,
        "refresh_token": refresh,
    }).encode("utf-8")
    data = _api_json(
        cfg, spec["token_url"], method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=form, purpose=f"oauth_refresh_{provider}",
    )
    access = str(data.get("access_token") or "")
    if not access:
        raise ValueError("OAuth refresh did not return a new access_token.")
    secure.set_secret(spec["token_secret"], access)
    secure.audit("oauth_token_refreshed", {"provider": provider})
    return {"ok": True, "provider": provider, "expires_in": data.get("expires_in")}


# ------------------------------------------------------------------ Official API Operations
def google_calendar_upcoming(cfg: dict, *, max_results: int = 10) -> list[dict]:
    token = secure.get_secret("oauth_google_token")
    if not token:
        raise ValueError("Google Workspace OAuth token is not configured.")
    n = max(1, min(int(max_results), 25))
    data = _api_json(
        cfg, f"https://www.googleapis.com/calendar/v3/calendars/primary/events?maxResults={n}&singleEvents=true",
        headers={"Authorization": f"Bearer {token}"}, purpose="google_calendar_read",
    )
    items = data.get("items") if isinstance(data, dict) else []
    return [
        {"id": str(i.get("id", "")), "summary": secure.redact(str(i.get("summary", "(no title)"))[:160]),
         "start": (i.get("start") or {}).get("dateTime") or (i.get("start") or {}).get("date", "")}
        for i in (items or [])[:n]
    ]


def google_gmail_list(cfg: dict, *, max_results: int = 10) -> list[dict]:
    token = secure.get_secret("oauth_google_token")
    if not token:
        raise ValueError("Google Workspace OAuth token is not configured.")
    n = max(1, min(int(max_results), 25))
    data = _api_json(
        cfg, f"https://www.googleapis.com/gmail/v1/users/me/messages?maxResults={n}",
        headers={"Authorization": f"Bearer {token}"}, purpose="google_gmail_read",
    )
    msgs = data.get("messages") if isinstance(data, dict) else []
    return [{"id": str(m.get("id", "")), "threadId": str(m.get("threadId", ""))} for m in (msgs or [])[:n]]


def ms365_messages_list(cfg: dict, *, top: int = 10) -> list[dict]:
    token = secure.get_secret("oauth_microsoft_token")
    if not token:
        raise ValueError("Microsoft 365 OAuth token is not configured.")
    n = max(1, min(int(top), 25))
    data = _api_json(
        cfg, f"https://graph.microsoft.com/v1.0/me/messages?$top={n}&$select=id,subject,receivedDateTime",
        headers={"Authorization": f"Bearer {token}"}, purpose="ms365_mail_read",
    )
    rows = data.get("value") if isinstance(data, dict) else []
    return [
        {"id": str(m.get("id", "")), "subject": secure.redact(str(m.get("subject", "(no subject)"))[:160]),
         "received": str(m.get("receivedDateTime", ""))}
        for m in (rows or [])[:n]
    ]


def ms_teams_joined_list(cfg: dict) -> list[dict]:
    token = secure.get_secret("oauth_microsoft_token")
    if not token:
        raise ValueError("Microsoft 365 / Teams OAuth token is not configured.")
    data = _api_json(
        cfg, "https://graph.microsoft.com/v1.0/me/joinedTeams",
        headers={"Authorization": f"Bearer {token}"}, purpose="ms_teams_read",
    )
    rows = data.get("value") if isinstance(data, dict) else []
    return [{"id": str(t.get("id", "")), "name": str(t.get("displayName", ""))[:120]} for t in (rows or [])[:30]]


def slack_channels_list(cfg: dict) -> list[dict]:
    token = secure.get_secret("slack_bot_token")
    if not token:
        raise ValueError("Slack bot token is not configured.")
    data = _api_json(
        cfg, "https://slack.com/api/conversations.list?limit=30&types=public_channel",
        headers={"Authorization": f"Bearer {token}"}, purpose="slack_channels_read",
    )
    if isinstance(data, dict) and not data.get("ok", True):
        raise ValueError(f"Slack API error: {data.get('error', 'unknown')}")
    chans = data.get("channels") if isinstance(data, dict) else []
    return [{"id": str(c.get("id", "")), "name": str(c.get("name", ""))[:80]} for c in (chans or [])[:30]]


def discord_channel_messages(cfg: dict, channel_id: str, *, limit: int = 10) -> list[dict]:
    token = secure.get_secret("discord_bot_token")
    if not token:
        raise ValueError("Discord bot token is not configured.")
    cid = str(channel_id or "").strip()
    if not cid.isdigit():
        raise ValueError("Discord channel_id must be a numeric snowflake ID.")
    n = max(1, min(int(limit), 25))
    data = _api_json(
        cfg, f"https://discord.com/api/v10/channels/{cid}/messages?limit={n}",
        headers={"Authorization": f"Bot {token}"}, purpose="discord_messages_read",
    )
    rows = data if isinstance(data, list) else []
    return [
        {"id": str(m.get("id", "")), "author": str((m.get("author") or {}).get("username", ""))[:60],
         "content": secure.redact(str(m.get("content", ""))[:400])}
        for m in rows[:n]
    ]


def home_assistant_states(cfg: dict) -> list[dict]:
    base = str(cfg.get("home_assistant_url") or "").strip().rstrip("/")
    token = secure.get_secret("home_assistant_token")
    if not base or not token:
        raise ValueError("Configure home_assistant_url and home_assistant_token first.")
    data = _api_json(
        cfg, f"{base}/api/states",
        headers={"Authorization": f"Bearer {token}"}, purpose="ha_states_read",
    )
    rows = data if isinstance(data, list) else []
    return [
        {"entity_id": str(r.get("entity_id", ""))[:80], "state": str(r.get("state", ""))[:60]}
        for r in rows[:50]
    ]


def home_assistant_call_service(cfg: dict, *, domain: str, service: str, entity_id: str) -> dict:
    base = str(cfg.get("home_assistant_url") or "").strip().rstrip("/")
    token = secure.get_secret("home_assistant_token")
    if not base or not token:
        raise ValueError("Configure home_assistant_url and home_assistant_token first.")
    if not (cfg.get("connector_write_permissions") or {}).get("home_assistant", False):
        raise PermissionError("Home Assistant write actions are disabled in connector_write_permissions.")
    body = json.dumps({"entity_id": str(entity_id)}).encode("utf-8")
    _api_json(
        cfg, f"{base}/api/services/{domain}/{service}", method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        body=body, purpose="ha_service_call",
    )
    secure.audit("ha_service_called", {"domain": domain, "service": service, "entity_id": entity_id})
    return {"ok": True, "domain": domain, "service": service, "entity_id": entity_id}


def test_connection(cfg: dict, connector_id: str) -> dict:
    """Safely test a configured connector without leaking secrets."""
    if connector_id not in SERVICE_CATALOGUE:
        raise ValueError(f"Unknown connector '{connector_id}'.")
    try:
        if connector_id == "google_workspace":
            items = google_calendar_upcoming(cfg, max_results=1)
            return {"ok": True, "connector": connector_id, "detail": f"Connected ({len(items)} event(s) visible)."}
        if connector_id == "microsoft_365":
            items = ms365_messages_list(cfg, top=1)
            return {"ok": True, "connector": connector_id, "detail": f"Connected ({len(items)} message(s) visible)."}
        if connector_id == "microsoft_teams":
            items = ms_teams_joined_list(cfg)
            return {"ok": True, "connector": connector_id, "detail": f"Connected ({len(items)} team(s) visible)."}
        if connector_id == "slack":
            items = slack_channels_list(cfg)
            return {"ok": True, "connector": connector_id, "detail": f"Connected ({len(items)} channel(s) visible)."}
        if connector_id == "home_assistant":
            items = home_assistant_states(cfg)
            return {"ok": True, "connector": connector_id, "detail": f"Connected ({len(items)} entity state(s))."}
        return {"ok": False, "connector": connector_id, "detail": "Live probe requires service-specific parameters or credentials."}
    except Exception as exc:
        return {"ok": False, "connector": connector_id, "detail": str(exc)}
