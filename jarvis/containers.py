"""Hardened Container & Isolated Execution Manager (Phase 7).

Security Invariants:
- NEVER exposes `/var/run/docker.sock` or `//./pipe/docker_engine` to any container.
- NEVER allows `--privileged`, `--cap-add=SYS_ADMIN`, `--pid=host`, or `--network=host`.
- Enforces non-root execution (`--user 65534:65534`), read-only rootfs (`--read-only`),
  `--cap-drop=ALL`, `--security-opt=no-new-privileges:true`, `--network=none` by default,
  memory/CPU/PID limits, and strict workspace mount validation.
- Provides graceful status reporting when Docker CLI is installed but daemon is stopped.
"""
import json
from pathlib import Path
import re
import shutil
import subprocess

from . import secure

_SAFE_IMAGE_RE = re.compile(r"^[a-z0-9][a-z0-9._/:@-]{1,120}$")
_SAFE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{1,60}$")
_FORBIDDEN_MOUNT_TOKENS = ("docker.sock", "docker_engine", "/etc", "/proc", "/sys", "c:\\windows", "system32")


def docker_available() -> dict:
    exe = shutil.which("docker")
    if not exe:
        return {"cli_installed": False, "daemon_running": False, "version": "", "reason": "Docker CLI not found on PATH."}
    try:
        proc = subprocess.run(
            [exe, "version", "--format", "{{json .}}"],
            capture_output=True, text=True, timeout=2.5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if proc.returncode != 0:
            return {"cli_installed": True, "daemon_running": False, "version": "", "reason": (proc.stderr or "Docker daemon not running.").strip()[:180]}
        data = json.loads(proc.stdout)
        cli_ver = (data.get("Client") or {}).get("Version", "")
        srv_ver = (data.get("Server") or {}).get("Version", "")
        return {"cli_installed": True, "daemon_running": bool(srv_ver), "version": srv_ver or cli_ver, "reason": "Ready" if srv_ver else "Docker daemon stopped."}
    except Exception as exc:
        return {"cli_installed": True, "daemon_running": False, "version": "", "reason": str(exc)[:180]}


def list_containers() -> list[dict]:
    st = docker_available()
    if not st["daemon_running"]:
        return []
    proc = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rows = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            rows.append({
                "id": obj.get("ID", ""),
                "name": obj.get("Names", ""),
                "image": obj.get("Image", ""),
                "status": obj.get("Status", ""),
                "state": obj.get("State", ""),
            })
        except ValueError:
            continue
    return rows[:60]


def list_images() -> list[dict]:
    st = docker_available()
    if not st["daemon_running"]:
        return []
    proc = subprocess.run(
        ["docker", "images", "--format", "{{json .}}"],
        capture_output=True, text=True, timeout=8,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    rows = []
    for line in (proc.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            rows.append({
                "repository": obj.get("Repository", ""),
                "tag": obj.get("Tag", ""),
                "id": obj.get("ID", ""),
                "size": obj.get("Size", ""),
            })
        except ValueError:
            continue
    return rows[:60]


def validate_mount_path(host_path: str | Path, allowed_root: str | Path) -> Path:
    """Ensure mounted workspace stays strictly inside allowed_root and never exposes Docker socket or OS paths."""
    raw = str(host_path or "").strip()
    low = raw.lower()
    for bad in _FORBIDDEN_MOUNT_TOKENS:
        if bad in low:
            secure.audit("container_mount_blocked", {"reason": bad})
            raise PermissionError(f"Blocked forbidden container mount containing '{bad}'.")
    target = Path(raw).expanduser().resolve()
    root = Path(allowed_root).expanduser().resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise PermissionError("Container mount must stay strictly inside the approved workspace root.")
    return target


def build_hardened_run_args(
    image: str,
    command: list[str],
    *,
    name: str = "",
    workspace_mount: str | Path | None = None,
    allowed_root: str | Path | None = None,
    read_only_mount: bool = True,
    memory_mb: int = 512,
    cpus: float = 1.0,
    pids_limit: int = 128,
    allow_network: bool = False,
) -> list[str]:
    """Build a hardened `docker run` argument vector enforcing non-root, read-only rootfs, cap-drop=ALL, and no docker.sock."""
    img = str(image or "").strip()
    if not _SAFE_IMAGE_RE.match(img):
        raise ValueError("Invalid container image reference.")
    if allow_network:
        raise PermissionError("Container network access requires a destination allowlist, which is not implemented.")
    if not command or not isinstance(command, list):
        raise ValueError("Provide a non-empty command list to run inside the container.")
    mem = max(64, min(int(memory_mb), 4096))
    cpu = max(0.25, min(float(cpus), 4.0))
    pids = max(16, min(int(pids_limit), 512))

    args = [
        "docker", "run", "--rm", "--pull=never",
        "--read-only",
        "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m",
        "--user", "65534:65534",
        "--cap-drop=ALL",
        "--security-opt=no-new-privileges:true",
        "--memory", f"{mem}m",
        "--cpus", f"{cpu:.2f}",
        "--pids-limit", str(pids),
        "--network", "none",
    ]
    if name:
        clean = str(name).strip()
        if not _SAFE_NAME_RE.match(clean):
            raise ValueError("Invalid container name.")
        args += ["--name", clean]
    if workspace_mount is not None:
        if allowed_root is None:
            raise PermissionError("An explicit allowed_root is required whenever mounting a host path.")
        safe_path = validate_mount_path(workspace_mount, allowed_root)
        mode = "ro" if read_only_mount else "rw"
        args += ["-v", f"{safe_path}:/workspace:{mode}", "-w", "/workspace"]
    args.append(img)
    args.extend(str(c) for c in command[:32])
    return args


def emergency_kill_container(cfg: dict, container_id: str, *, approved: bool = False) -> dict:
    """Immediately stop/kill a named container (requires Lockdown OFF + approval)."""
    if cfg.get("lockdown"):
        raise PermissionError("Container actions are blocked during Lockdown.")
    if not approved:
        raise PermissionError("Explicit approval is required to kill a container.")
    cid = str(container_id or "").strip()
    if not _SAFE_NAME_RE.match(cid):
        raise ValueError("Invalid container ID or name.")
    st = docker_available()
    if not st["daemon_running"]:
        raise RuntimeError(st["reason"])
    subprocess.run(
        ["docker", "kill", cid],
        check=True, capture_output=True, text=True, timeout=10,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    secure.audit("container_killed", {"id": cid})
    return {"ok": True, "killed": cid}


def workspace_state() -> dict:
    st = docker_available()
    container_rows = []
    image_rows = []
    if st["daemon_running"]:
        try:
            container_rows = list_containers()
            image_rows = list_images()
        except (subprocess.TimeoutExpired, OSError) as exc:
            st = {**st, "inventory_error": f"Docker inventory unavailable: {type(exc).__name__}. Retry later."}
    return {
        "docker": st,
        "containers": container_rows,
        "images": image_rows,
        "security_defaults": {
            "non_root_uid_gid": "65534:65534",
            "read_only_rootfs": True,
            "cap_drop": "ALL",
            "no_new_privileges": True,
            "default_network": "none",
            "docker_socket_mount": "prohibited",
            "privileged_mode": "prohibited",
        },
    }
