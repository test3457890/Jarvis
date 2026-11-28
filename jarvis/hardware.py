"""Hardware detection and honest local model recommendations.

Reports actual CPU, RAM, disk and NVIDIA GPU readings where available. Model memory
figures are planning estimates, never measured runtime claims.
"""
import os
import platform
import shutil
import subprocess
from pathlib import Path

GB = 1024 ** 3


def detect_cpu() -> dict:
    physical = None
    logical = os.cpu_count() or 1
    try:
        import psutil
        physical = psutil.cpu_count(logical=False)
        logical = psutil.cpu_count(logical=True) or logical
    except Exception:
        pass
    return {
        "processor": platform.processor() or platform.machine() or "Unknown CPU",
        "physical_cores": physical,
        "logical_cores": logical,
    }


def detect_memory() -> dict:
    try:
        import psutil
        vm = psutil.virtual_memory()
        return {
            "total_gb": round(vm.total / GB, 2),
            "available_gb": round(vm.available / GB, 2),
            "percent_used": round(vm.percent, 1),
        }
    except Exception:
        return {"total_gb": None, "available_gb": None, "percent_used": None}


def detect_gpu() -> list:
    """Detect NVIDIA GPUs via nvidia-smi without assuming CUDA drivers are installed."""
    exe = shutil.which("nvidia-smi")
    if not exe:
        return []
    try:
        result = subprocess.run(
            [exe, "--query-gpu=name,memory.total,memory.free,utilization.gpu,driver_version",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=4,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode != 0:
            return []
        gpus = []
        for line in result.stdout.splitlines():
            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 5:
                continue
            try:
                total_mib = float(parts[1])
                free_mib = float(parts[2])
                util = float(parts[3]) if parts[3] not in ("", "[N/A]", "N/A") else None
            except ValueError:
                continue
            gpus.append({
                "name": parts[0][:120],
                "vram_total_gb": round(total_mib / 1024.0, 2),
                "vram_free_gb": round(free_mib / 1024.0, 2),
                "utilization_percent": round(util, 1) if util is not None else None,
                "driver": parts[4][:40],
            })
        return gpus
    except Exception:
        return []


def detect_disk(path=None) -> dict:
    target = Path(path) if path else Path.home()
    while not target.exists() and target.parent != target:
        target = target.parent
    try:
        usage = shutil.disk_usage(target)
        return {
            "path": str(target),
            "total_gb": round(usage.total / GB, 2),
            "free_gb": round(usage.free / GB, 2),
        }
    except OSError:
        return {"path": str(target), "total_gb": None, "free_gb": None}


def recommend_profile(memory: dict, gpus: list) -> dict:
    """Suggest a Jarvis profile and local models based on actual detected RAM and VRAM."""
    ram_gb = memory.get("total_gb")
    max_vram = max((g.get("vram_total_gb") or 0.0 for g in gpus), default=0.0)
    if ram_gb is not None and ram_gb <= 10.0 and max_vram < 6.0:
        return {
            "profile": "low-memory",
            "tier": "8 GB / low-memory CPU",
            "everyday_model": "qwen3:4b",
            "technical_model": "qwen3:4b",
            "coder_model": "qwen2.5-coder:1.5b",
            "whisper_model": "base.en",
            "estimated_ram_gb": 5.5,
            "reason": f"Detected {ram_gb:.1f} GB system RAM with no >=6 GB dedicated GPU; smaller models keep memory pressure manageable.",
            "note": "Estimates only; real speed and memory use depend on quantization and active apps.",
        }
    if max_vram >= 12.0 and (ram_gb is None or ram_gb >= 16.0):
        return {
            "profile": "standard",
            "tier": "GPU-accelerated workstation",
            "everyday_model": "qwen3:4b",
            "technical_model": "qwen3:8b",
            "coder_model": "qwen2.5-coder:7b",
            "whisper_model": "small.en",
            "estimated_ram_gb": 9.0,
            "reason": f"Detected {max_vram:.1f} GB GPU VRAM" + (f" and {ram_gb:.1f} GB RAM" if ram_gb else "") + "; standard models fit comfortably with GPU acceleration.",
            "note": "Estimates only; real speed depends on Ollama GPU offload and drivers.",
        }
    return {
        "profile": "standard",
        "tier": "Standard desktop (16 GB+ RAM)",
        "everyday_model": "qwen3:4b",
        "technical_model": "qwen3:8b",
        "coder_model": "qwen2.5-coder:7b",
        "whisper_model": "small.en",
        "estimated_ram_gb": 9.0,
        "reason": "Standard profile balances quality and responsiveness on systems with 16 GB+ RAM.",
        "note": "Estimates only; switch to low-memory if other heavy applications are open.",
    }


def summary(disk_path=None) -> dict:
    cpu = detect_cpu()
    mem = detect_memory()
    gpus = detect_gpu()
    disk = detect_disk(disk_path)
    return {
        "os": f"{platform.system()} {platform.release()} ({platform.version()[:40]})",
        "cpu": cpu,
        "memory": mem,
        "gpus": gpus,
        "gpu_detected": bool(gpus),
        "disk": disk,
        "recommendation": recommend_profile(mem, gpus),
    }
