"""Approved connector architecture (C01, C02, C03, C05).

Provides:
- Unified connector registry covering built-in services, saved RSS subscriptions,
  optional cloud AI providers, and OAuth 2.0 PKCE scaffolding for Google Workspace
  (Drive, Calendar, Gmail) and Microsoft 365 (Outlook, OneDrive, Teams).
- Strict read-only vs write permission separation.
- Honest status reporting: connectors without real credentials or OAuth tokens are
  marked as 'Needs OAuth setup' or 'Needs setup' and never pretend to be operational.
"""
import hashlib
import base64
import secrets
from urllib.parse import urlencode

from . import cloudprovider, config, net, online, secure

OAUTH_CONNECTORS = {
    "google_workspace": {
        "name": "Google Workspace (Drive, Calendar, Gmail)",
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "client_id_secret": "google_oauth_client_id",
        "token_secret": "google_oauth_token",
        "read_scopes": [
            "https://www.googleapis.com/auth/calendar.readonly",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ],
        "write_scopes": [
            "https://www.googleapis.com/auth/calendar.events",
            "https://www.googleapis.com/auth/gmail.compose",
        ],
        "setup_note": "Requires user-provided Google Cloud OAuth Desktop client ID and browser authorization.",
    },
    "microsoft_365": {
        "name": "Microsoft 365 (Outlook, OneDrive, Teams)",
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "client_id_secret": "ms365_oauth_client_id",
        "token_secret": "ms365_oauth_token",
        "read_scopes": [
            "Calendars.Read",
            "Mail.Read",
            "Files.Read",
            "Chat.Read",
        ],
        "write_scopes": [
            "Calendars.ReadWrite",
            "Mail.ReadWrite",
        ],
        "setup_note": "Requires user-provided Azure App Registration client ID and explicit tenant/account sign-in.",
    },
}

MAX_SAVED_FEEDS = 20


def pkce_challenge() -> tuple[str, str]:
    """Generate an RFC 7636 S256 PKCE verifier and challenge pair."""
    verifier = secrets.token_urlsafe(48)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def build_oauth_url(connector_id: str, redirect_uri: str, write_access: bool = False) -> dict:
    """Build a read-only-by-default PKCE OAuth authorization URL for a configured connector."""
    if connector_id not in OAUTH_CONNECTORS:
        raise ValueError("Unsupported OAuth connector.")
    spec = OAUTH_CONNECTORS[connector_id]
    client_id = secure.get_secret(spec["client_id_secret"])
    if not client_id:
        raise ValueError(f"{spec['name']} requires a configured OAuth client ID first. {spec['setup_note']}")
    if not redirect_uri.startswith("http://127.0.0.1:"):
        raise ValueError("OAuth redirect URI must use loopback http://127.0.0.1:<port>.")
    verifier, challenge = pkce_challenge()
    state = secrets.token_urlsafe(24)
    scopes = list(spec["read_scopes"]) + (list(spec["write_scopes"]) if write_access else [])
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return {
        "connector": connector_id,
        "url": spec["auth_url"] + "?" + urlencode(params),
        "state": state,
        "code_verifier": verifier,
        "scopes": scopes,
        "mode": "read_write" if write_access else "read_only",
    }


def disconnect_oauth(connector_id: str) -> None:
    if connector_id not in OAUTH_CONNECTORS:
        raise ValueError("Unsupported OAuth connector.")
    spec = OAUTH_CONNECTORS[connector_id]
    secure.set_secret(spec["token_secret"], "")
    secure.audit("connector_disconnected", {"connector": connector_id})


def oauth_status(cfg: dict) -> list:
    internet = bool(cfg.get("allow_internet_tools"))
    rows = []
    for cid, spec in OAUTH_CONNECTORS.items():
        has_client = secure.has_secret(spec["client_id_secret"])
        has_token = secure.has_secret(spec["token_secret"])
        write_allowed = bool((cfg.get("connector_write_permissions") or {}).get(cid, False))
        if has_token:
            state = "Authorized locally" if internet else "Authorized locally (paused — Internet off)"
        elif has_client:
            state = "Client ID set; sign-in required"
        else:
            state = "Needs OAuth credentials"
        rows.append({
            "id": cid,
            "name": spec["name"],
            "state": state,
            "permission_mode": "read+write (previewed)" if write_allowed else "read-only",
            "revocable": has_token,
            "read_scopes": spec["read_scopes"],
            "write_scopes": spec["write_scopes"],
            "setup_note": spec["setup_note"],
        })
    return rows


# ------------------------------------------------------------ Saved RSS subscriptions (C05)
def list_feeds(cfg: dict) -> list:
    feeds = cfg.get("saved_feeds") or []
    clean = []
    for item in feeds[:MAX_SAVED_FEEDS]:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and item["url"].startswith("https://"):
            clean.append({
                "name": str(item.get("name") or item["url"])[:80],
                "url": item["url"][:2000],
                "include_in_briefing": bool(item.get("include_in_briefing", False)),
            })
    return clean


def add_feed(cfg: dict, name: str, url: str, include_in_briefing: bool = False) -> list:
    if cfg.get("lockdown"):
        raise ValueError("Turn off Lockdown to manage feed subscriptions.")
    name = str(name or "").strip()[:80]
    url = str(url or "").strip()
    if not name:
        raise ValueError("Enter a short name for this feed.")
    if not url.startswith("https://") or len(url) > 2000 or any(ord(c) < 33 for c in url):
        raise ValueError("Feed URL must be a valid public HTTPS URL.")
    feeds = [f for f in list_feeds(cfg) if f["url"] != url]
    if len(feeds) >= MAX_SAVED_FEEDS:
        raise ValueError(f"At most {MAX_SAVED_FEEDS} feed subscriptions can be saved.")
    feeds.append({"name": name, "url": url, "include_in_briefing": bool(include_in_briefing)})
    updated = {**cfg, "saved_feeds": feeds}
    config.save(updated)
    cfg.update(updated)
    secure.audit("feed_subscription_added", {"name": name})
    return feeds


def remove_feed(cfg: dict, url: str) -> list:
    if cfg.get("lockdown"):
        raise ValueError("Turn off Lockdown to manage feed subscriptions.")
    feeds = [f for f in list_feeds(cfg) if f["url"] != url]
    updated = {**cfg, "saved_feeds": feeds}
    config.save(updated)
    cfg.update(updated)
    secure.audit("feed_subscription_removed", {"remaining": len(feeds)})
    return feeds


def all_connector_summary(cfg: dict) -> dict:
    from . import connections
    return {
        "internet": bool(cfg.get("allow_internet_tools")),
        "services": connections.status(cfg),
        "oauth": oauth_status(cfg),
        "cloud_providers": cloudprovider.status(cfg),
        "feeds": list_feeds(cfg),
        "catalogue_count": len(CONNECTOR_CATALOGUE),
    }


CONNECTOR_CATALOGUE = [
    {"id": "gods-eye-view-mcp", "name": "God's Eye View Geospatial MCP", "category": "geospatial", "license": "MIT", "repo": "https://github.com/bilawalsidhu/gods-eye-view", "permissions": ["internet_public_feeds"], "dependencies": ["Node.js 18+"], "security_review": "Public spatial feeds only; optional Cesium ion token for 3D tiles. No private tracking.", "version": "1.0"},
    {"id": "home-assistant-mcp", "name": "Home Assistant Local API", "category": "smarthome", "license": "Apache-2.0", "repo": "https://www.home-assistant.io", "permissions": ["local_network", "dpapi_token"], "dependencies": ["Home Assistant instance"], "security_review": "Owner long-lived token stored in DPAPI; explicit device authorization required.", "version": "2026.x"},
    {"id": "frigate-nvr", "name": "Frigate Local NVR", "category": "smarthome", "license": "MIT", "repo": "https://github.com/blakeblackshear/frigate", "permissions": ["local_network"], "dependencies": ["Frigate NVR"], "security_review": "Owner-configured local NVR events only; facial identification disabled.", "version": "0.14+"},
    {"id": "wazuh-siem", "name": "Wazuh Defensive SIEM Adapter", "category": "security", "license": "GPL-2.0", "repo": "https://github.com/wazuh/wazuh", "permissions": ["read_alerts"], "dependencies": ["Wazuh Manager / local EVE JSON"], "security_review": "Read-only defensive alert ingestion.", "version": "4.x"},
    {"id": "suricata-ids", "name": "Suricata EVE JSON Alert Reader", "category": "security", "license": "GPL-2.0", "repo": "https://github.com/OISF/suricata", "permissions": ["read_local_logs"], "dependencies": ["Suricata"], "security_review": "Local EVE JSON log parsing; no packet injection.", "version": "7.x"},
    {"id": "zeek-nsm", "name": "Zeek Network Security Monitor", "category": "security", "license": "BSD-3-Clause", "repo": "https://github.com/zeek/zeek", "permissions": ["read_local_logs"], "dependencies": ["Zeek"], "security_review": "Passive local network log analysis.", "version": "6.x"},
    {"id": "trivy-scanner", "name": "Aqua Trivy Vulnerability Scanner", "category": "security", "license": "Apache-2.0", "repo": "https://github.com/aquasecurity/trivy", "permissions": ["read_workspace", "read_containers"], "dependencies": ["trivy CLI"], "security_review": "Defensive dependency and container CVE scanning.", "version": "0.58+"},
    {"id": "yara-rules", "name": "YARA Pattern Scanner", "category": "security", "license": "BSD-3-Clause", "repo": "https://github.com/VirusTotal/yara", "permissions": ["read_workspace"], "dependencies": ["yara CLI"], "security_review": "Read-only defensive file pattern matching.", "version": "4.5+"},
    {"id": "github-mcp", "name": "GitHub Official API", "category": "developer", "license": "MIT", "repo": "https://github.com/github/github-mcp-server", "permissions": ["internet_api", "dpapi_token"], "dependencies": ["GitHub PAT"], "security_review": "Scoped token in DPAPI; write actions require confirmation.", "version": "1.x"},
    {"id": "sqlite-local-mcp", "name": "Local SQLite Inspector MCP", "category": "data", "license": "MIT", "repo": "https://modelcontextprotocol.io", "permissions": ["read_local_db"], "dependencies": ["Python / Node"], "security_review": "Scoped strictly to approved workspace databases.", "version": "1.x"},
    {"id": "filesystem-scoped-mcp", "name": "Scoped Local Filesystem MCP", "category": "files", "license": "MIT", "repo": "https://modelcontextprotocol.io", "permissions": ["read_approved_folders"], "dependencies": ["Node.js"], "security_review": "Restricted to explicitly approved user directories; never system/credential dirs.", "version": "1.x"},
    {"id": "playwright-mcp", "name": "Playwright Local Browser Automation", "category": "automation", "license": "Apache-2.0", "repo": "https://github.com/microsoft/playwright", "permissions": ["browser_session"], "dependencies": ["Playwright + Chromium"], "security_review": "Enforces network allowlist and refuses password/auth automation.", "version": "1.50+"},
    {"id": "google-workspace-oauth", "name": "Google Workspace (Drive, Calendar, Gmail)", "category": "productivity", "license": "Apache-2.0", "repo": "https://developers.google.com/workspace", "permissions": ["oauth_pkce_readonly"], "dependencies": ["Google Cloud OAuth Client ID"], "security_review": "Read-only by default via RFC 7636 PKCE; write requires explicit toggle.", "version": "v2"},
    {"id": "microsoft-365-oauth", "name": "Microsoft 365 (Outlook, OneDrive, Teams)", "category": "productivity", "license": "MIT", "repo": "https://learn.microsoft.com/graph", "permissions": ["oauth_pkce_readonly"], "dependencies": ["Azure App Registration"], "security_review": "Read-only by default via RFC 7636 PKCE; write requires explicit toggle.", "version": "v1.0"},
    {"id": "docker-hardened", "name": "Docker Hardened Local Sandbox", "category": "containers", "license": "Apache-2.0", "repo": "https://www.docker.com", "permissions": ["local_docker_cli"], "dependencies": ["Docker Desktop / Engine"], "security_review": "Enforces --read-only, --cap-drop=ALL, non-root, no docker.sock mounts.", "version": "27.x"},
    {"id": "canvas-lms", "name": "Canvas LMS Academic Sync", "category": "academic", "license": "AGPL-3.0 (API client)", "repo": "https://canvas.instructure.com", "permissions": ["internet_api", "dpapi_token"], "dependencies": ["Canvas API Token"], "security_review": "Read-only course/deadline retrieval via pinned HTTPS.", "version": "v1"},
]


def search_catalogue(query: str = "", category: str = "") -> list[dict]:
    """Search the vetted connector & MCP server catalogue without installing anything automatically."""
    q = str(query or "").strip().lower()
    cat = str(category or "").strip().lower()
    out = []
    for item in CONNECTOR_CATALOGUE:
        if cat and item["category"] != cat:
            continue
        hay = f"{item['id']} {item['name']} {item['category']} {item['security_review']}".lower()
        if not q or q in hay:
            out.append({**item, "requires_approval": True, "auto_install": False})
    return out


def preview_catalogue_install(connector_id: str) -> dict:
    """Return a full security, dependency, license, and permission preview before explicit approval."""
    cid = str(connector_id or "").strip().lower()
    for item in CONNECTOR_CATALOGUE:
        if item["id"] == cid:
            return {
                "ok": True,
                "connector": item,
                "requires_explicit_approval": True,
                "auto_install_policy": "Disabled — Jarvis never automatically installs arbitrary code from GitHub.",
            }
    raise ValueError(f"Connector '{connector_id}' not found in catalogue.")
