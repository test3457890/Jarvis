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
from urllib.request import Request

from . import net, secure

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
