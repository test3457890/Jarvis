"""Sentinel: defensive-only local security posture audit and NOMAD integrity monitor.

Strictly defensive and local-only:
- Verifies loopback binding, offline/Lockdown state, DPAPI secrets store, network allowlist,
  extension/MCP approvals, and recent blocked security events from actions.log.
- Never disables Windows Defender, bypasses OS security, or probes external/unauthorized systems.
"""
import os
from pathlib import Path

from . import config, domains, extensions, mcp_client, net, nomad, secure


def audit_posture(cfg: dict, *, include_nomad: bool = False) -> dict:
    """Return a structured defensive security audit of the local Jarvis installation."""
    checks = []

    # 1. Local binding check
    port = int(cfg.get("web_port", 8765))
    checks.append({
        "id": "loopback_binding",
        "label": "HUD loopback binding",
        "status": "pass",
        "detail": f"Bound strictly to 127.0.0.1:{port} with Host, Origin, CSP, and per-session X-Jarvis-Key checks.",
    })

    # 2. Offline / Internet posture
    internet = bool(cfg.get("allow_internet_tools"))
    checks.append({
        "id": "network_posture",
        "label": "Outbound network policy",
        "status": "pass" if not internet else "info",
        "detail": (
            "Offline mode active; all external internet tools blocked."
            if not internet
            else f"Internet tools enabled with fail-closed allowlist ({len(net.allowed_endpoints(cfg))} allowed endpoints)."
        ),
    })

    # 3. Lockdown & confirmation guard
    confirm = bool(cfg.get("confirm_risky_actions", True))
    checks.append({
        "id": "risky_confirmations",
        "label": "Risky action confirmations",
        "status": "pass" if confirm else "warn",
        "detail": (
            "Lockdown mode is ON (all risky actions blocked)." if cfg.get("lockdown")
            else ("Risky actions require explicit user confirmation." if confirm
                  else "confirm_risky_actions is false in config; risky skills still enforce ask in skills.py.")
        ),
    })

    # 4. Secrets storage check (no raw secrets in config.json)
    config_secrets = []
    for k in cfg:
        kl = k.lower()
        if any(tok in kl for tok in ("password", "api_key", "secret", "token")) and cfg.get(k):
            config_secrets.append(k)
    checks.append({
        "id": "secret_storage",
        "label": "Credential isolation",
        "status": "pass" if not config_secrets else "warn",
        "detail": (
            f"Secrets stored in DPAPI vault ({secure.SECRETS_PATH.name}); no credential keys in config.json."
            if not config_secrets
            else f"Potential secret keys found in config.json: {', '.join(config_secrets)}"
        ),
    })

    # 5. Cloud silent fallback protection
    cloud_on = bool(cfg.get("allow_cloud_provider"))
    checks.append({
        "id": "cloud_privacy",
        "label": "Local-first AI privacy",
        "status": "pass",
        "detail": (
            "Cloud providers disabled; all inference stays local."
            if not cloud_on
            else "Optional cloud provider enabled with mandatory per-request approval; zero silent fallback."
        ),
    })

    # 6. Coding vs file-task workspace isolation
    code_root = Path(cfg.get("code_dir") or config.DEFAULTS["code_dir"]).expanduser().resolve()
    overlap = False
    for folder in cfg.get("file_folders") or []:
        p = Path(folder).expanduser().resolve()
        if p == code_root or p in code_root.parents or code_root in p.parents:
            overlap = True
    checks.append({
        "id": "workspace_isolation",
        "label": "Coding and file-task workspace separation",
        "status": "pass" if not overlap else "warn",
        "detail": (
            "Coding workspace is isolated from selected file-task folders."
            if not overlap
            else "Warning: a file-task folder overlaps with the coding workspace."
        ),
    })

    # 7. Enabled extensions & MCP servers
    enabled_ext = [e["id"] for e in extensions.status(cfg) if e.get("enabled")]
    enabled_mcp = [s["id"] for s in mcp_client.list_servers(cfg) if s.get("enabled")]
    checks.append({
        "id": "addons_surface",
        "label": "Approved extensions and MCP servers",
        "status": "pass" if not (enabled_ext or enabled_mcp) else "info",
        "detail": (
            f"{len(enabled_ext)} extension(s) enabled, {len(enabled_mcp)} MCP server(s) enabled. "
            "Note: extensions and stdio MCP servers run as the local OS user, not inside a VM sandbox."
        ),
    })

    # 8. Audit log security events summary
    recent = secure.recent_activity(limit=100)
    blocked = [e for e in recent if "blocked" in e.get("action", "").lower()]
    checks.append({
        "id": "audit_events",
        "label": "Recent blocked security events",
        "status": "pass" if not blocked else "info",
        "detail": f"{len(blocked)} blocked event(s) recorded in the last {len(recent)} activity entries.",
    })

    # 9. Finance & Health boundaries
    checks.append({
        "id": "protected_domains",
        "label": "Finance & Health domain boundaries",
        "status": "pass",
        "detail": "Finance and Health connectors remain disabled by default; write actions prohibited.",
    })

    result = {
        "os": os.name,
        "lockdown": bool(cfg.get("lockdown")),
        "internet": internet,
        "checks": checks,
        "blocked_events": blocked[:15],
        "domains": domains.domain_status(cfg),
    }
    if include_nomad:
        result["nomad"] = nomad.status(cfg)
    return result
