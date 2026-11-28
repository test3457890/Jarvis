"""Opt-In Mobile Companion Pairing (Android & future iOS architecture).

CRITICAL SECURITY RULES:
- Disabled by default (`remote_companion_enabled = False`).
- Never binds Jarvis to 0.0.0.0 or exposes the assistant to the public internet.
  Companion connections are designed strictly for local ADB port-forwarding or an
  authenticated private VPN tunnel (WireGuard / Tailscale) with TLS.
- Device bearer tokens are stored ONLY as SHA-256 hashes in SQLite.
- Pairing codes expire after 120 seconds and are single-use.
- Remote commands never bypass Lockdown or T2/T3 human confirmation.
"""
import hashlib
import secrets
import threading
import time

from . import secure

PAIR_TTL_SECONDS = 120
_PAIR_LOCK = threading.Lock()
_PENDING_CODE: dict | None = None


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
                revoked INTEGER NOT NULL DEFAULT 0
            )"""
        )
        mem.db.commit()


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


def complete_pairing(mem, cfg: dict, *, code: str, device_name: str, platform: str = "android") -> dict:
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
    with _PAIR_LOCK:
        pending = _PENDING_CODE
        if not pending or time.time() > pending["expires"] or not secrets.compare_digest(str(code or ""), pending["code"]):
            raise PermissionError("Invalid or expired pairing code.")
        _PENDING_CODE = None

    device_id = f"dev-{secrets.token_hex(4)}"
    raw_token = secrets.token_urlsafe(32)
    now = time.time()
    with mem._lock:
        mem.db.execute(
            "INSERT INTO paired_devices (id, name, platform, token_hash, paired_at, last_seen, revoked) VALUES (?, ?, ?, ?, ?, ?, 0)",
            (device_id, clean_name, plat, _hash_token(raw_token), now, now),
        )
        mem.db.commit()
    secure.audit("companion_device_paired", {"id": device_id, "platform": plat})
    return {"device_id": device_id, "name": clean_name, "platform": plat, "token": raw_token}


def verify_device_token(mem, cfg: dict, token: str) -> dict | None:
    init_db(mem)
    if not is_enabled(cfg) or not token:
        return None
    digest = _hash_token(token)
    with mem._lock:
        row = mem.db.execute(
            "SELECT id, name, platform, token_hash, revoked FROM paired_devices WHERE revoked=0"
        ).fetchall()
    for dev_id, name, plat, stored_hash, _ in row:
        if secrets.compare_digest(digest, stored_hash):
            with mem._lock:
                mem.db.execute("UPDATE paired_devices SET last_seen=? WHERE id=?", (time.time(), dev_id))
                mem.db.commit()
            return {"id": dev_id, "name": name, "platform": plat}
    return None


def list_devices(mem, cfg: dict) -> dict:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, platform, paired_at, last_seen, revoked FROM paired_devices ORDER BY paired_at DESC"
        ).fetchall()
    return {
        "enabled": is_enabled(cfg),
        "remote_exposure": "disabled (loopback / private VPN only)",
        "devices": [
            {"id": r[0], "name": r[1], "platform": r[2], "paired_at": r[3], "last_seen": r[4], "revoked": bool(r[5])}
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
