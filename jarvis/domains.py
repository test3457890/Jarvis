"""Foundational permission boundaries for Phase 13 Finance and Health domains.

Per the approved roadmap:
- No live banking, brokerage, or medical accounts are connected by default.
- All finance and health capabilities remain disabled unless explicitly enabled and
  authorized by the user in a future dedicated expansion.
- Read-only and write boundaries are declared centrally so future modules inherit
  Jarvis's fail-closed permission model.
"""

DOMAIN_POLICIES = {
    "finance": {
        "enabled_by_default": False,
        "status": "Foundation only — no live banking or brokerage connectors active",
        "read_only_boundary": "Portfolio/budget CSV or local summary inspection only when explicitly imported.",
        "write_boundary": "Order placement, transfers, and brokerage writes are strictly prohibited without dedicated future authorization.",
        "requires_lockdown_off": True,
        "requires_explicit_consent": True,
    },
    "health": {
        "enabled_by_default": False,
        "status": "Foundation only — no medical portal or wearable account connected",
        "read_only_boundary": "Local exported fitness/wellness summaries only when explicitly provided by the user.",
        "write_boundary": "Medical advice, diagnoses, and health-portal writes are prohibited.",
        "requires_lockdown_off": True,
        "requires_explicit_consent": True,
    },
}


def domain_status(cfg: dict) -> list:
    rows = []
    for name, policy in DOMAIN_POLICIES.items():
        enabled = bool((cfg.get("domain_permissions") or {}).get(name, False))
        rows.append({
            "domain": name,
            "enabled": enabled and not cfg.get("lockdown"),
            "status": policy["status"],
            "read_only_boundary": policy["read_only_boundary"],
            "write_boundary": policy["write_boundary"],
        })
    return rows


def check_domain_access(cfg: dict, domain: str, write: bool = False) -> None:
    """Fail-closed guard for future finance and health modules."""
    if domain not in DOMAIN_POLICIES:
        raise ValueError(f"Unknown protected domain: {domain}")
    if cfg.get("lockdown"):
        raise PermissionError(f"{domain.title()} domain is blocked during Lockdown.")
    if write:
        raise PermissionError(f"Write operations in the {domain} domain are prohibited in this release.")
    if not (cfg.get("domain_permissions") or {}).get(domain, False):
        raise PermissionError(f"The {domain} domain is disabled by default and requires explicit user authorization.")
