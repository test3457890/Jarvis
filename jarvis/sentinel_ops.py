"""Sentinel Defensive Cybersecurity Workspace (Phase 6).

Strictly Defensive Architecture:
- Authorized local network/port listener monitoring (psutil).
- Read-only IDS alert ingestion for Suricata EVE JSON / Zeek / Wazuh local alert logs.
- Optional local Trivy vulnerability & YARA rule scanner adapters (detected, never auto-downloaded).
- File Integrity Monitoring (FIM) with SHA-256 SQLite baselines.
- Workspace Secret Exposure Detection (AWS/GitHub/OpenAI/Private Key patterns).
- Defensive Firewall Rule Preview (dry-run only unless explicitly approved by owner).
- Incident Evidence Pack exporter (bounded JSON snapshot + SHA-256 manifest).
- PROHIBITED: retaliatory DDoS, unauthorized exploitation, credential theft, malware, offensive automation.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

from . import config, secure

OPTIONAL_SECURITY_TOOLS = {
    "wazuh": {"repo": "https://github.com/wazuh/wazuh", "license": "GPL-2.0", "role": "SIEM / Endpoint HIDS"},
    "suricata": {"repo": "https://github.com/OISF/suricata", "license": "GPL-2.0", "role": "Network IDS/IPS (EVE JSON)"},
    "zeek": {"repo": "https://github.com/zeek/zeek", "license": "BSD-3-Clause", "role": "Network Security Monitor"},
    "yara": {"repo": "https://github.com/VirusTotal/yara", "license": "BSD-3-Clause", "role": "Pattern / Malware Rule Matcher"},
    "velociraptor": {"repo": "https://github.com/Velocidex/velociraptor", "license": "AGPL-3.0", "role": "DFIR Endpoint Telemetry"},
    "trivy": {"repo": "https://github.com/aquasecurity/trivy", "license": "Apache-2.0", "role": "Container & Dependency Vulnerability Scanner"},
}

_SECRET_PATTERNS = [
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github_pat", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{24,}\b")),
    ("openai_key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("private_key_header", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----")),
]


def _init_fim_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS sentinel_fim (
                path TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                size_bytes INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def detect_security_integrations() -> list[dict]:
    """Check which optional external defensive security binaries are installed locally."""
    out = []
    for name, meta in OPTIONAL_SECURITY_TOOLS.items():
        exe = shutil.which(name)
        out.append({"id": name, **meta, "installed": exe is not None, "path": exe or ""})
    return out


def local_network_listeners(limit: int = 40) -> list[dict]:
    """List local listening TCP/UDP sockets on this machine (authorized read-only T0)."""
    try:
        import psutil
    except ImportError:
        return []
    rows = []
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.status == "LISTEN" or conn.type.name == "SOCK_DGRAM":
                laddr = f"{conn.laddr.ip}:{conn.laddr.port}" if conn.laddr else ""
                rows.append({
                    "proto": "TCP" if conn.type.name == "SOCK_STREAM" else "UDP",
                    "local_address": laddr,
                    "status": conn.status or "OPEN",
                    "pid": conn.pid,
                })
                if len(rows) >= max(1, min(limit, 100)):
                    break
    except Exception:
        pass
    return rows


def parse_ids_eve_alerts(log_path: str | Path, *, limit: int = 50) -> dict:
    """Parse Suricata/Wazuh JSONL/EVE alert entries safely (read-only)."""
    p = Path(log_path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(f"IDS alert log not found: {p.name}")
    alerts = []
    with p.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except ValueError:
                continue
            if obj.get("event_type") == "alert" or "alert" in obj or "rule" in obj:
                al = obj.get("alert") or obj.get("rule") or {}
                alerts.append({
                    "timestamp": str(obj.get("timestamp") or "")[:40],
                    "signature": str(al.get("signature") or al.get("description") or "Alert")[:140],
                    "severity": al.get("severity") or al.get("level") or 3,
                    "src_ip": str(obj.get("src_ip") or "")[:64],
                    "dest_port": obj.get("dest_port"),
                })
                if len(alerts) >= max(1, min(limit, 200)):
                    break
    return {"file": p.name, "alert_count": len(alerts), "alerts": alerts}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fim_baseline(mem, paths: list[str | Path]) -> dict:
    """Record SHA-256 File Integrity Monitoring baselines for specified local files."""
    _init_fim_db(mem)
    recorded = []
    now = time.time()
    for raw in paths[:50]:
        p = Path(raw).expanduser().resolve()
        if not p.is_file():
            continue
        digest = _sha256(p)
        size = p.stat().st_size
        with mem._lock:
            mem.db.execute(
                "INSERT OR REPLACE INTO sentinel_fim (path, sha256, size_bytes, updated_at) VALUES (?, ?, ?, ?)",
                (str(p), digest, size, now),
            )
            mem.db.commit()
        recorded.append({"path": str(p), "sha256": digest, "size_bytes": size})
    secure.audit("sentinel_fim_baseline", {"files": len(recorded)})
    return {"ok": True, "recorded": len(recorded), "files": recorded}


def fim_verify(mem) -> dict:
    """Verify all baselined files against their stored SHA-256 digests."""
    _init_fim_db(mem)
    with mem._lock:
        rows = mem.db.execute("SELECT path, sha256, size_bytes FROM sentinel_fim").fetchall()
    intact, modified, missing = [], [], []
    for fpath, expected, _sz in rows:
        p = Path(fpath)
        if not p.is_file():
            missing.append(fpath)
            continue
        actual = _sha256(p)
        if actual == expected:
            intact.append(fpath)
        else:
            modified.append({"path": fpath, "expected": expected[:16], "actual": actual[:16]})
    return {
        "ok": len(modified) == 0 and len(missing) == 0,
        "intact": len(intact),
        "modified": modified,
        "missing": missing,
    }


def scan_secrets(root_dir: str | Path, *, max_files: int = 120) -> dict:
    """Scan local text files for accidental secret/key exposure (never logs actual secret values)."""
    root = Path(root_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Scan directory does not exist.")
    findings = []
    scanned = 0
    skip_dirs = {".git", ".venv", "node_modules", "__pycache__", "dist", "target"}
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fname in files:
            if scanned >= max_files:
                break
            fp = Path(cur) / fname
            if fp.suffix.lower() not in (".py", ".js", ".ts", ".json", ".env", ".yml", ".yaml", ".toml", ".txt", ".md"):
                continue
            try:
                if fp.stat().st_size > 256_000:
                    continue
                content = fp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            scanned += 1
            for kind, rx in _SECRET_PATTERNS:
                if rx.search(content):
                    findings.append({"file": str(fp.relative_to(root)), "kind": kind})
    secure.audit("sentinel_secret_scan", {"scanned": scanned, "findings": len(findings)})
    return {"scanned_files": scanned, "finding_count": len(findings), "findings": findings}


def preview_defensive_firewall_rule(name: str, remote_ip: str, *, direction: str = "Inbound", action: str = "Block") -> dict:
    """Generate a dry-run preview of a defensive Windows Firewall rule (never executes automatically)."""
    clean_name = re.sub(r"[^A-Za-z0-9 _-]", "", str(name or "JarvisDefensiveBlock")).strip()[:60]
    ip = str(remote_ip or "").strip()
    if not re.match(r"^(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?$", ip):
        raise ValueError("Provide a valid IPv4 address or CIDR block (e.g. 203.0.113.10).")
    if direction not in ("Inbound", "Outbound") or action not in ("Block", "Allow"):
        raise ValueError("Direction must be Inbound/Outbound and Action must be Block/Allow.")
    cmd = f"New-NetFirewallRule -DisplayName '{clean_name}' -Direction {direction} -RemoteAddress {ip} -Action {action}"
    return {
        "dry_run": True,
        "requires_admin_approval": True,
        "command_preview": cmd,
        "safety_note": "Preview only. Defensive containment rules require explicit administrator approval.",
    }


def export_incident_evidence(mem, *, out_dir: Path | None = None, title: str = "incident") -> dict:
    """Export a bounded, SHA-256-verified local incident evidence bundle (read-only snapshot)."""
    dest_root = out_dir or (config.APP_DIR / "incident-evidence")
    dest_root.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9_-]", "", str(title or "incident").lower())[:32] or "incident"
    fname = f"evidence_{slug}_{int(time.time())}.json"
    out_path = dest_root / fname
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "title": title[:80],
        "listeners": local_network_listeners(30),
        "fim_status": fim_verify(mem),
        "integrations": detect_security_integrations(),
    }
    raw = json.dumps(payload, indent=2).encode("utf-8")
    out_path.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    secure.audit("sentinel_evidence_exported", {"file": fname, "sha256": digest[:16]})
    return {"ok": True, "path": str(out_path), "sha256": digest, "bytes": len(raw)}


def workspace_state(mem) -> dict:
    return {
        "integrations": detect_security_integrations(),
        "listeners": local_network_listeners(25),
        "fim": fim_verify(mem),
        "policy": {
            "defensive_only": True,
            "offensive_automation": "prohibited",
            "firewall_execution": "dry_run_preview_only",
        },
    }
