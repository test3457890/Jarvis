"""Opt-In Mobile Companion Pairing (Android & future iOS architecture).

CRITICAL SECURITY RULES:
- Disabled by default (`remote_companion_enabled = False`).
- Never binds Jarvis to 0.0.0.0 or exposes the assistant to the public internet.
  Companion connections are designed strictly for local ADB port-forwarding or an
  authenticated private VPN tunnel (WireGuard / Tailscale) with TLS.
- Device bearer tokens are stored ONLY as SHA-256 hashes in SQLite with explicit expiration.
- Pairing codes expire after 120 seconds, are single-use, and failed attempts are rate-limited.
- Remote commands are restricted to approved T0 read-only monitoring or queueing confirmations,
  and NEVER bypass Lockdown or T2/T3 human approval.
"""
from collections import deque
import hashlib
import secrets
import threading
import time

from . import secure, skills

PAIR_TTL_SECONDS = 120
DEFAULT_TOKEN_TTL_SECONDS = 30 * 86400
MAX_PAIR_FAILURES = 5
PAIR_WINDOW_SECONDS = 300.0

_PAIR_LOCK = threading.Lock()
_PENDING_CODE: dict | None = None
_PAIR_LIMITER = secure.RateLimiter()
_NOTIFICATIONS: deque[dict] = deque(maxlen=50)


def init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS paired_devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                platform TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                paired_at REAL NOT NULL,
                last_seen REAL,
                expires_at REAL NOT NULL DEFAULT 0,
                revoked INTEGER NOT NULL DEFAULT 0
            )"""
        )
        cols = {r[1] for r in mem.db.execute("PRAGMA table_info(paired_devices)").fetchall()}
        if "expires_at" not in cols:
            mem.db.execute("ALTER TABLE paired_devices ADD COLUMN expires_at REAL NOT NULL DEFAULT 0")
        mem.db.commit()


def reset_rate_limiter() -> None:
    _PAIR_LIMITER.reset()


def is_enabled(cfg: dict) -> bool:
    return bool(cfg.get("remote_companion_enabled", False)) and not bool(cfg.get("lockdown"))


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_pairing_code(cfg: dict) -> dict:
    """Generate a single-use 6-digit pairing code valid for 120 seconds (opt-in only)."""
    global _PENDING_CODE
    if not is_enabled(cfg):
        raise PermissionError("Mobile companion pairing is disabled by default (or blocked by Lockdown).")
    code = f"{secrets.randbelow(900000) + 100000}"
    expires = time.time() + PAIR_TTL_SECONDS
    with _PAIR_LOCK:
        _PENDING_CODE = {"code": code, "expires": expires}
    secure.audit("companion_pair_code_created", {"expires_in_s": PAIR_TTL_SECONDS})
    return {"code": code, "expires_in_s": PAIR_TTL_SECONDS}


def complete_pairing(
    mem,
    cfg: dict,
    *,
    code: str,
    device_name: str,
    platform: str = "android",
    token_ttl_seconds: int = DEFAULT_TOKEN_TTL_SECONDS,
    client_id: str = "default",
) -> dict:
    global _PENDING_CODE
    init_db(mem)
    if not is_enabled(cfg):
        raise PermissionError("Mobile companion pairing is disabled.")
    plat = str(platform or "android").strip().lower()
    if plat not in ("android", "ios"):
        raise ValueError("Platform must be 'android' or 'ios'.")
    clean_name = str(device_name or "").strip()[:60]
    if not clean_name:
        raise ValueError("Device name is required.")
    ttl = max(60, min(int(token_ttl_seconds), 90 * 86400))

    with _PAIR_LOCK:
        pending = _PENDING_CODE
        valid = bool(pending and time.time() <= pending["expires"] and secrets.compare_digest(str(code or ""), pending["code"]))
        if not valid:
            if not _PAIR_LIMITER.allow(f"pair_fail:{client_id}", MAX_PAIR_FAILURES, PAIR_WINDOW_SECONDS):
                _PENDING_CODE = None
                secure.audit("companion_pair_rate_limited", {"client": client_id})
                raise PermissionError("Too many failed pairing attempts. Generate a new pairing code later.")
            secure.audit("companion_pair_failed", {"client": client_id})
            raise PermissionError("Invalid or expired pairing code.")
        _PENDING_CODE = None

    device_id = f"dev-{secrets.token_hex(4)}"
    raw_token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + ttl
    with mem._lock:
        mem.db.execute(
            "INSERT INTO paired_devices (id, name, platform, token_hash, paired_at, last_seen, expires_at, revoked) VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (device_id, clean_name, plat, _hash_token(raw_token), now, now, expires_at),
        )
        mem.db.commit()
    secure.audit("companion_device_paired", {"id": device_id, "platform": plat, "ttl_s": ttl})
    return {
        "device_id": device_id,
        "name": clean_name,
        "platform": plat,
        "token": raw_token,
        "expires_at": round(expires_at, 2),
    }


def verify_device_token(mem, cfg: dict, token: str, *, now: float | None = None) -> dict | None:
    init_db(mem)
    if not is_enabled(cfg) or not token:
        return None
    check_time = time.time() if now is None else float(now)
    digest = _hash_token(token)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, platform, token_hash, expires_at FROM paired_devices WHERE revoked=0"
        ).fetchall()
    for dev_id, name, plat, stored_hash, expires_at in rows:
        if secrets.compare_digest(digest, stored_hash):
            if expires_at and check_time > expires_at:
                secure.audit("companion_token_expired", {"id": dev_id})
                return None
            with mem._lock:
                mem.db.execute("UPDATE paired_devices SET last_seen=? WHERE id=?", (check_time, dev_id))
                mem.db.commit()
            return {"id": dev_id, "name": name, "platform": plat, "expires_at": expires_at}
    return None


def list_devices(mem, cfg: dict) -> dict:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, platform, paired_at, last_seen, expires_at, revoked FROM paired_devices ORDER BY paired_at DESC"
        ).fetchall()
    return {
        "enabled": is_enabled(cfg),
        "remote_exposure": "disabled (loopback / private VPN only)",
        "devices": [
            {
                "id": r[0], "name": r[1], "platform": r[2],
                "paired_at": r[3], "last_seen": r[4], "expires_at": r[5], "revoked": bool(r[6]),
            }
            for r in rows
        ],
    }


def revoke_device(mem, device_id: str) -> bool:
    init_db(mem)
    with mem._lock:
        cur = mem.db.execute("UPDATE paired_devices SET revoked=1 WHERE id=?", (device_id,))
        mem.db.commit()
    secure.audit("companion_device_revoked", {"id": device_id})
    return cur.rowcount > 0


def push_notification(title: str, body: str, *, level: str = "info") -> dict:
    item = {
        "id": secrets.token_hex(4),
        "ts": round(time.time(), 2),
        "level": level if level in ("info", "warn", "alert") else "info",
        "title": secure.redact(str(title or "")[:100]),
        "body": secure.redact(str(body or "")[:400]),
    }
    _NOTIFICATIONS.appendleft(item)
    return item


def recent_notifications(limit: int = 20) -> list[dict]:
    return list(_NOTIFICATIONS)[:max(1, min(limit, 50))]


APPROVED_REMOTE_TOOLS = frozenset({"get_time_date", "system_status", "list_reminders", "list_tasks", "briefing"})


def execute_approved_command(mem, ctx: skills.Context, *, token: str, tool: str, args: dict | None = None) -> dict:
    """Execute a strictly allowlisted T0 read-only command from a verified paired device."""
    device = verify_device_token(mem, ctx.cfg, token)
    if not device:
        raise PermissionError("Unauthorized, expired, or revoked companion device token.")
    if tool not in APPROVED_REMOTE_TOOLS or skills.risk_tier(tool) != "T0":
        secure.audit("companion_command_blocked", {"device": device["id"], "tool": tool})
        raise PermissionError(f"Remote command '{tool}' is not on the approved read-only companion allowlist.")
    out = skills.run(ctx, tool, args or {})
    secure.audit("companion_command_executed", {"device": device["id"], "tool": tool})
    return {"ok": True, "device": device["name"], "tool": tool, "output": secure.redact(out[:4000])}
