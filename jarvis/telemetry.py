"""Real-time local system vitals and process telemetry.

Collects authentic CPU, RAM, GPU/VRAM/temperature, disk, battery, network throughput,
and top process metrics using psutil and nvidia-smi where available. Never fabricates
sensor readings: unavailable sensors are reported as None.
"""
from collections import deque
import os
import platform
import shutil
import subprocess
import threading
import time
from pathlib import Path

GB = 1024 ** 3
MB = 1024 ** 2

_LOCK = threading.Lock()
_HISTORY: deque[dict] = deque(maxlen=60)
_LAST_NET: tuple[float, int, int] | None = None
_GPU_CACHE: tuple[float, list[dict]] = (0.0, [])
_GPU_TTL_S = 2.0


def _detect_gpus_live() -> list[dict]:
    """Query NVIDIA GPUs via nvidia-smi with a short cache so HUD polling stays fast."""
    global _GPU_CACHE
    now = time.monotonic()
    with _LOCK:
        cached_at, cached = _GPU_CACHE
        if now - cached_at < _GPU_TTL_S and cached_at > 0:
            return [dict(g) for g in cached]

    exe = shutil.which("nvidia-smi")
    if not exe:
        with _LOCK:
            _GPU_CACHE = (now, [])
        return []
    try:
        result = subprocess.run(
            [
                exe,
                "--query-gpu=name,memory.total,memory.used,memory.free,utilization.gpu,temperature.gpu,driver_version",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            gpus = []
        else:
            gpus = []
            for line in result.stdout.splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) < 7:
                    continue
                try:
                    total_mib = float(parts[1])
                    used_mib = float(parts[2])
                    free_mib = float(parts[3])
                except ValueError:
                    continue
                util = _opt_float(parts[4])
                temp = _opt_float(parts[5])
                vram_pct = round((used_mib / total_mib) * 100.0, 1) if total_mib > 0 else None
                gpus.append({
                    "name": parts[0][:120],
                    "vram_total_gb": round(total_mib / 1024.0, 2),
                    "vram_used_gb": round(used_mib / 1024.0, 2),
                    "vram_free_gb": round(free_mib / 1024.0, 2),
                    "vram_percent": vram_pct,
                    "utilization_percent": round(util, 1) if util is not None else None,
                    "temperature_c": round(temp, 1) if temp is not None else None,
                    "driver": parts[6][:40],
                })
    except Exception:
        gpus = []

    with _LOCK:
        _GPU_CACHE = (now, gpus)
    return [dict(g) for g in gpus]


def _opt_float(value: str) -> float | None:
    if value in ("", "[N/A]", "N/A", "[Not Supported]"):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _collect_network() -> dict:
    global _LAST_NET
    try:
        import psutil
        io = psutil.net_io_counters()
        if io is None:
            return {"up_kbps": None, "down_kbps": None, "total_sent_mb": None, "total_recv_mb": None}
        now = time.monotonic()
        with _LOCK:
            prev = _LAST_NET
            _LAST_NET = (now, io.bytes_sent, io.bytes_recv)
        up_kbps = 0.0
        down_kbps = 0.0
        if prev is not None:
            dt = max(now - prev[0], 0.05)
            up_kbps = round(max(0, io.bytes_sent - prev[1]) / dt / 1024.0, 1)
            down_kbps = round(max(0, io.bytes_recv - prev[2]) / dt / 1024.0, 1)
        return {
            "up_kbps": up_kbps,
            "down_kbps": down_kbps,
            "total_sent_mb": round(io.bytes_sent / MB, 1),
            "total_recv_mb": round(io.bytes_recv / MB, 1),
        }
    except Exception:
        return {"up_kbps": None, "down_kbps": None, "total_sent_mb": None, "total_recv_mb": None}


def _collect_top_processes(limit: int = 8) -> list[dict]:
    try:
        import psutil
        rows = []
        for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
            try:
                info = proc.info
                mem = info.get("memory_info")
                mem_mb = round(mem.rss / MB, 1) if mem else 0.0
                cpu = round(float(info.get("cpu_percent") or 0.0), 1)
                name = str(info.get("name") or "unknown")[:60]
                rows.append({
                    "pid": int(info.get("pid") or 0),
                    "name": name,
                    "cpu_percent": cpu,
                    "memory_mb": mem_mb,
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
        rows.sort(key=lambda r: (r["cpu_percent"], r["memory_mb"]), reverse=True)
        return rows[:max(1, min(limit, 20))]
    except Exception:
        return []


def snapshot(disk_path=None, include_processes: bool = True, record_history: bool = True) -> dict:
    """Return a real-time snapshot of local system vitals."""
    cpu_pct = None
    per_core = []
    freq_mhz = None
    physical = None
    logical = os.cpu_count() or 1
    mem = {"total_gb": None, "used_gb": None, "available_gb": None, "percent": None}
    battery = None

    try:
        import psutil
        cpu_pct = round(float(psutil.cpu_percent(interval=None)), 1)
        per_core = [round(float(v), 1) for v in psutil.cpu_percent(interval=None, percpu=True)[:32]]
        freq = psutil.cpu_freq()
        if freq and freq.current:
            freq_mhz = round(float(freq.current), 0)
        physical = psutil.cpu_count(logical=False)
        logical = psutil.cpu_count(logical=True) or logical
        vm = psutil.virtual_memory()
        mem = {
            "total_gb": round(vm.total / GB, 2),
            "used_gb": round(vm.used / GB, 2),
            "available_gb": round(vm.available / GB, 2),
            "percent": round(vm.percent, 1),
        }
        bat = psutil.sensors_battery()
        if bat is not None:
            secs = bat.secsleft if isinstance(bat.secsleft, (int, float)) and bat.secsleft >= 0 else None
            battery = {
                "percent": round(float(bat.percent), 1),
                "plugged": bool(bat.power_plugged),
                "secs_left": int(secs) if secs is not None else None,
            }
    except Exception:
        pass

    target = Path(disk_path) if disk_path else Path.home()
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        du = shutil.disk_usage(target)
        disk = {
            "path": str(target),
            "total_gb": round(du.total / GB, 2),
            "used_gb": round(du.used / GB, 2),
            "free_gb": round(du.free / GB, 2),
            "percent": round((du.used / du.total) * 100.0, 1) if du.total > 0 else None,
        }
    except OSError:
        disk = {"path": str(target), "total_gb": None, "used_gb": None, "free_gb": None, "percent": None}

    gpus = _detect_gpus_live()
    network = _collect_network()
    processes = _collect_top_processes(limit=8) if include_processes else []
    ts = round(time.time(), 2)

    point = {
        "ts": ts,
        "cpu_percent": cpu_pct,
        "mem_percent": mem["percent"],
        "gpu_percent": gpus[0]["utilization_percent"] if gpus else None,
        "vram_percent": gpus[0]["vram_percent"] if gpus else None,
        "net_up_kbps": network["up_kbps"],
        "net_down_kbps": network["down_kbps"],
    }
    with _LOCK:
        if record_history:
            _HISTORY.append(point)
        history = list(_HISTORY)

    return {
        "ts": ts,
        "os": f"{platform.system()} {platform.release()}",
        "cpu": {
            "percent": cpu_pct,
            "per_core": per_core,
            "freq_mhz": freq_mhz,
            "physical_cores": physical,
            "logical_cores": logical,
        },
        "memory": mem,
        "gpus": gpus,
        "disk": disk,
        "battery": battery,
        "network": network,
        "processes": processes,
        "history": history,
    }


def history() -> list[dict]:
    with _LOCK:
        return list(_HISTORY)


def clear_history() -> None:
    global _LAST_NET, _GPU_CACHE
    with _LOCK:
        _HISTORY.clear()
        _LAST_NET = None
        _GPU_CACHE = (0.0, [])
