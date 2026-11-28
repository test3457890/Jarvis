"""Authorized Smart Home & Camera Center (Phase 5).

Security & Privacy Architecture:
- Supports ONLY explicitly registered, owner-authorized devices:
  Home Assistant, owner ONVIF cameras, owner RTSP cameras, Frigate NVR, and
  public transportation/weather webcams.
- Stores credentials strictly via jarvis.secure (Windows DPAPI) — never plaintext.
- Explicitly REFUSES unauthenticated third-party camera discovery, credential bypass,
  facial identification, and covert monitoring.
- Recording/control actions require explicit owner approval + Lockdown OFF.
"""
import json
import re
import time
import urllib.parse

from . import secure

DEVICE_KINDS = {
    "home_assistant": {"label": "Home Assistant", "requires_auth": True, "supports_control": True},
    "onvif_camera": {"label": "Owner ONVIF Camera", "requires_auth": True, "supports_control": True},
    "rtsp_camera": {"label": "Owner RTSP Camera", "requires_auth": True, "supports_control": False},
    "frigate_nvr": {"label": "Frigate NVR", "requires_auth": True, "supports_control": True},
    "public_webcam": {"label": "Public Weather / Traffic Webcam", "requires_auth": False, "supports_control": False},
}

_SAFE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
_ALLOWED_SCHEMES = {"https", "http", "rtsp", "rtsps"}


def _init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS smarthome_devices (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                kind TEXT NOT NULL,
                endpoint TEXT NOT NULL,
                zone TEXT NOT NULL,
                owner_authorized INTEGER NOT NULL DEFAULT 1,
                recording_enabled INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'registered',
                last_event TEXT NOT NULL DEFAULT '',
                created_at REAL NOT NULL
            )"""
        )
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS smarthome_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                summary TEXT NOT NULL,
                created_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def _validate_endpoint(kind: str, endpoint: str) -> str:
    url = str(endpoint or "").strip()
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise ValueError("Endpoint must be a valid http(s):// or rtsp(s):// URL with a hostname.")
    if parsed.username or parsed.password:
        raise ValueError("Do not embed credentials inside the URL. Store them via encrypted credential storage.")
    if kind == "public_webcam" and parsed.scheme.lower() != "https":
        raise ValueError("Public weather/traffic webcams must use HTTPS.")
    return url[:300]


def register_device(
    mem,
    cfg: dict,
    *,
    device_id: str,
    name: str,
    kind: str,
    endpoint: str,
    zone: str = "General",
    owner_authorized: bool = False,
    credential: str = "",
) -> dict:
    """Explicitly register an owner-authorized smart home device or camera."""
    if cfg.get("lockdown"):
        raise PermissionError("Cannot register smart home devices during Lockdown.")
    if not owner_authorized:
        raise PermissionError("Explicit owner authorization is required to register any device or camera.")
    did = str(device_id or "").strip().lower()
    if not _SAFE_ID_RE.match(did):
        raise ValueError("Device ID must be 2-41 lowercase letters, digits, '-' or '_'.")
    k = str(kind or "").strip().lower()
    if k not in DEVICE_KINDS:
        raise ValueError(f"Unsupported device kind '{k}'.")
    clean_ep = _validate_endpoint(k, endpoint)
    clean_name = str(name or did).strip()[:80]
    clean_zone = str(zone or "General").strip()[:40]

    _init_db(mem)
    with mem._lock:
        mem.db.execute(
            """INSERT OR REPLACE INTO smarthome_devices
               (id, name, kind, endpoint, zone, owner_authorized, recording_enabled, status, last_event, created_at)
               VALUES (?, ?, ?, ?, ?, 1, 0, 'registered', '', ?)""",
            (did, clean_name, k, clean_ep, clean_zone, time.time()),
        )
        mem.db.commit()
    if credential:
        secure.set_secret(f"smarthome_{did}", str(credential))
    secure.audit("smarthome_device_registered", {"id": did, "kind": k, "zone": clean_zone})
    return get_device(mem, did)


def get_device(mem, device_id: str) -> dict:
    _init_db(mem)
    with mem._lock:
        row = mem.db.execute(
            "SELECT id, name, kind, endpoint, zone, owner_authorized, recording_enabled, status, last_event, created_at FROM smarthome_devices WHERE id=?",
            (device_id,),
        ).fetchone()
    if not row:
        raise ValueError(f"Smart home device '{device_id}' not found.")
    return {
        "id": row[0], "name": row[1], "kind": row[2], "endpoint": row[3], "zone": row[4],
        "owner_authorized": bool(row[5]), "recording_enabled": bool(row[6]),
        "status": row[7], "last_event": row[8], "created_at": row[9],
        "has_credential": bool(secure.get_secret(f"smarthome_{row[0]}")),
    }


def list_devices(mem) -> list[dict]:
    _init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, kind, endpoint, zone, owner_authorized, recording_enabled, status, last_event, created_at FROM smarthome_devices ORDER BY zone, name"
        ).fetchall()
    return [
        {
            "id": r[0], "name": r[1], "kind": r[2], "endpoint": r[3], "zone": r[4],
            "owner_authorized": bool(r[5]), "recording_enabled": bool(r[6]),
            "status": r[7], "last_event": r[8], "created_at": r[9],
            "has_credential": bool(secure.get_secret(f"smarthome_{r[0]}")),
        }
        for r in rows
    ]


def remove_device(mem, cfg: dict, device_id: str) -> dict:
    if cfg.get("lockdown"):
        raise PermissionError("Cannot remove smart home devices during Lockdown.")
    _init_db(mem)
    with mem._lock:
        mem.db.execute("DELETE FROM smarthome_devices WHERE id=?", (device_id,))
        mem.db.execute("DELETE FROM smarthome_events WHERE device_id=?", (device_id,))
        mem.db.commit()
    try:
        secure.delete_secret(f"smarthome_{device_id}")
    except Exception:
        pass
    secure.audit("smarthome_device_removed", {"id": device_id})
    return {"ok": True, "removed": device_id}


def set_recording(mem, cfg: dict, device_id: str, enabled: bool, *, approved: bool = False) -> dict:
    """Toggle recording on an owner-authorized camera (requires explicit approval + Lockdown OFF)."""
    if cfg.get("lockdown"):
        raise PermissionError("Camera recording controls are disabled during Lockdown.")
    if not approved:
        raise PermissionError("Explicit owner approval is required to change camera recording state.")
    dev = get_device(mem, device_id)
    if dev["kind"] == "public_webcam":
        raise PermissionError("Recording control is not supported on public webcams.")
    with mem._lock:
        mem.db.execute("UPDATE smarthome_devices SET recording_enabled=? WHERE id=?", (1 if enabled else 0, device_id))
        mem.db.commit()
    record_event(mem, device_id, "recording", f"Recording {'enabled' if enabled else 'disabled'} by owner.")
    secure.audit("smarthome_recording_toggled", {"id": device_id, "enabled": bool(enabled)})
    return get_device(mem, device_id)


def record_event(mem, device_id: str, kind: str, summary: str) -> dict:
    """Record a local motion or status event summary (no biometric/facial identification)."""
    clean_summary = str(summary or "").strip()[:240]
    if any(tok in clean_summary.lower() for tok in ("face_id", "facial_recognition", "biometric_match")):
        raise PermissionError("Facial identification and biometric tracking are prohibited by policy.")
    _init_db(mem)
    now = time.time()
    with mem._lock:
        mem.db.execute(
            "INSERT INTO smarthome_events (device_id, kind, summary, created_at) VALUES (?, ?, ?, ?)",
            (device_id, str(kind or "motion")[:40], clean_summary, now),
        )
        mem.db.execute("UPDATE smarthome_devices SET last_event=? WHERE id=?", (clean_summary, device_id))
        mem.db.commit()
    return {"device_id": device_id, "kind": kind, "summary": clean_summary, "created_at": now}


def list_events(mem, limit: int = 30) -> list[dict]:
    _init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, device_id, kind, summary, created_at FROM smarthome_events ORDER BY id DESC LIMIT ?",
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [{"id": r[0], "device_id": r[1], "kind": r[2], "summary": r[3], "created_at": r[4]} for r in rows]


def workspace_state(mem) -> dict:
    return {
        "device_kinds": DEVICE_KINDS,
        "devices": list_devices(mem),
        "events": list_events(mem, 25),
        "policy": {
            "owner_authorization_required": True,
            "third_party_discovery": "disabled",
            "facial_identification": "prohibited",
            "credential_storage": "DPAPI encrypted",
        },
    }
