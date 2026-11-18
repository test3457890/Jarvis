"""First-run setup wizard: prerequisites, profile, model downloads and a storage budget.

The wizard never deletes configuration. It merges its choices into the existing settings
and saves them with the same atomic writer as the rest of Jarvis. Download progress is
kept in setup-state.json so a failed or interrupted download resumes from the first
unfinished step. Ollama and the speech-model cache keep partial files themselves, so a
retry continues those downloads instead of starting again.

Storage limits: Ollama stores models in one shared folder (OLLAMA_MODELS) for every app
on the PC, and faster-whisper uses the shared Hugging Face cache. Neither offers a
per-application quota. Jarvis checks the budget before it starts each download and
refuses downloads that would exceed it. It cannot stop other programs from using the
same caches, and it cannot cap a download that is already running.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import config, net

GB = 1000 ** 3
STATE_NAME = "setup-state.json"

# Approximate download sizes in bytes. Ollama reports the real size of installed models
# and the wizard prefers those numbers. Figures here are planning estimates only.
MODELS = {
    "qwen3:8b": {"bytes": int(5.2 * GB), "role": "TUKI technical model"},
    "qwen3:4b": {"bytes": int(2.5 * GB), "role": "Jarvis everyday model"},
    "qwen2.5-coder:7b": {"bytes": int(4.7 * GB), "role": "Coding model"},
    "qwen2.5-coder:1.5b": {"bytes": int(1.0 * GB), "role": "Coding model (low memory)"},
    "nomic-embed-text": {"bytes": int(0.27 * GB), "role": "Memory recall embeddings"},
    "gemma3:4b": {"bytes": int(3.3 * GB), "role": "Image lookup (optional)"},
}
WHISPER = {"small.en": int(0.49 * GB), "base.en": int(0.15 * GB), "tiny.en": int(0.08 * GB)}

PROFILE_DOWNLOADS = {
    "standard": {"models": ["qwen3:4b", "qwen3:8b", "qwen2.5-coder:7b", "nomic-embed-text"], "whisper": "small.en"},
    "low-memory": {"models": ["qwen3:4b", "qwen2.5-coder:1.5b"], "whisper": "base.en"},
}
OPTIONAL_MODELS = ("gemma3:4b",)

SHARED_CACHE_NOTE = (
    "Ollama models are stored in Ollama's shared model folder and speech models in the shared "
    "Hugging Face cache. Other apps can use the same folders, and Windows cannot give Jarvis a "
    "hard per-app limit there. Jarvis checks your budget before each download starts and will "
    "not start one that would exceed it."
)

_LOCK = threading.RLock()


def state_path():
    return config.APP_DIR / STATE_NAME


def load_state():
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("steps"), list):
            return data
    except (OSError, ValueError):
        pass
    return {"steps": [], "running": False, "error": ""}


def save_state(state):
    config.APP_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=config.APP_DIR, delete=False, encoding="utf-8") as stream:
        json.dump(state, stream, indent=2)
        temporary = Path(stream.name)
    try:
        temporary.replace(state_path())
    finally:
        temporary.unlink(missing_ok=True)


def ollama_models_dir():
    custom = os.environ.get("OLLAMA_MODELS")
    return Path(custom) if custom else Path.home() / ".ollama" / "models"


def hf_cache_dir():
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    base = os.environ.get("HF_HOME") or str(Path.home() / ".cache" / "huggingface")
    return Path(base) / "hub"


def free_bytes(path):
    """Free space on the volume that holds path (or its nearest existing parent)."""
    path = Path(path)
    while not path.exists() and path.parent != path:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def installed_ollama(cfg):
    """Return {model name: size in bytes} reported by Ollama, or None when it is unreachable."""
    try:
        request = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/tags")
        with net.urlopen(request, cfg, timeout=3, purpose="ollama_tags") as response:
            models = json.loads(response.read().decode()).get("models", [])
    except Exception:
        return None
    found = {}
    for item in models:
        name = item.get("name", "")
        found[name] = int(item.get("size") or 0)
        if name.endswith(":latest"):
            found[name.removesuffix(":latest")] = int(item.get("size") or 0)
    return found


def whisper_cached(name):
    folder = hf_cache_dir() / f"models--Systran--faster-whisper-{name}"
    return folder.is_dir() and any(folder.glob("snapshots/*/model.bin"))


def prerequisites(cfg):
    ollama = installed_ollama(cfg)
    checks = [
        {"id": "python", "label": f"Python {sys.version_info.major}.{sys.version_info.minor}",
         "ok": sys.version_info >= (3, 10), "hint": "Install Python 3.12 from python.org."},
        {"id": "ollama_installed", "label": "Ollama installed",
         "ok": bool(shutil.which("ollama")) or ollama is not None,
         "hint": "Install Ollama from https://ollama.com/download, then select Check again."},
        {"id": "ollama_running", "label": "Ollama running", "ok": ollama is not None,
         "hint": "Start the Ollama app. Downloads need it running."},
    ]
    for module, label in (("faster_whisper", "Speech recognition package"),
                          ("sounddevice", "Microphone package"), ("pyttsx3", "Windows voice package")):
        try:
            __import__(module)
            ok = True
        except Exception:
            ok = False
        checks.append({"id": module, "label": label, "ok": ok, "optional": True,
                       "hint": "Run install.ps1 to install Python packages."})
    try:
        import sounddevice
        device = sounddevice.query_devices(kind="input")["name"]
        checks.append({"id": "microphone", "label": f"Microphone: {device}", "ok": True, "optional": True})
    except Exception:
        checks.append({"id": "microphone", "label": "Microphone found", "ok": False, "optional": True,
                       "hint": "Connect a microphone or continue with typing only."})
    return checks, ollama


def plan(cfg, choices):
    """Return the downloads for the user's choices with sizes, disk space and budget checks."""
    profile = choices.get("profile", cfg.get("performance_profile", "standard"))
    if profile not in PROFILE_DOWNLOADS:
        raise ValueError("Choose Standard or 8 GB low memory.")
    selected = list(PROFILE_DOWNLOADS[profile]["models"])
    for name in choices.get("optional_models") or []:
        if name not in OPTIONAL_MODELS:
            raise ValueError("Unknown optional model.")
        selected.append(name)
    voice = bool(choices.get("voice", True))
    budget_gb = choices.get("budget_gb")
    if budget_gb is not None and (not isinstance(budget_gb, (int, float)) or not 1 <= budget_gb <= 2000):
        raise ValueError("Choose a storage budget between 1 and 2000 GB.")
    installed = installed_ollama(cfg)
    items = []
    for name in dict.fromkeys(selected):
        present = installed is not None and name in installed
        size = installed[name] if present and installed[name] else MODELS[name]["bytes"]
        items.append({"kind": "ollama", "name": name, "role": MODELS[name]["role"], "bytes": size,
                      "installed": present, "estimated": not present})
    if voice:
        whisper = PROFILE_DOWNLOADS[profile]["whisper"]
        items.append({"kind": "whisper", "name": whisper, "role": "Speech recognition",
                      "bytes": WHISPER[whisper], "installed": whisper_cached(whisper), "estimated": True})
    needed = sum(item["bytes"] for item in items if not item["installed"])
    total = sum(item["bytes"] for item in items)
    free_ollama = free_bytes(ollama_models_dir())
    free_hf = free_bytes(hf_cache_dir())
    warnings = []
    if budget_gb is not None and total > budget_gb * GB:
        warnings.append(f"These choices use about {total / GB:.1f} GB, above your {budget_gb:g} GB budget. "
                        "Choose the low-memory profile, skip optional models, or raise the budget.")
    if free_ollama is not None and needed > free_ollama:
        warnings.append(f"About {needed / GB:.1f} GB is needed but only {free_ollama / GB:.1f} GB is free.")
    return {"profile": profile, "items": items, "needed_bytes": needed, "total_bytes": total,
            "budget_gb": budget_gb, "free_bytes": free_ollama, "free_bytes_speech": free_hf,
            "ollama_dir": str(ollama_models_dir()), "speech_dir": str(hf_cache_dir()),
            "ollama_reachable": installed is not None, "over_budget": bool(
                budget_gb is not None and total > budget_gb * GB), "warnings": warnings,
            "shared_cache_note": SHARED_CACHE_NOTE}


def _clean_folders(values, label):
    if values is None:
        return None
    if not isinstance(values, list) or len(values) > 20 or any(not isinstance(v, str) or not v.strip() for v in values):
        raise ValueError(f"Enter up to 20 {label}, one per line.")
    resolved = [str(Path(v).expanduser().resolve()) for v in values]
    if any(not Path(v).is_dir() for v in resolved):
        raise ValueError(f"Every selected {label[:-1]} must exist.")
    return resolved


def apply_choices(cfg, choices):
    """Merge wizard choices into the existing configuration. Nothing else is removed."""
    updated = config.apply_profile(cfg, choices["profile"]) if "profile" in choices else dict(cfg)
    folders = _clean_folders(choices.get("document_folders"), "document folders")
    if folders is not None:
        updated["document_folders"] = folders
    file_folders = _clean_folders(choices.get("file_folders"), "file folders")
    if file_folders is not None:
        code = Path(updated.get("code_dir") or "").expanduser().resolve()
        for value in file_folders:
            path = Path(value)
            if path == code or code in path.parents or path in code.parents:
                raise ValueError("Keep file-task folders separate from the Jarvis Code workspace.")
        updated["file_folders"] = file_folders
    if choices.get("code_dir"):
        code_dir = Path(str(choices["code_dir"])).expanduser().resolve()
        code_dir.mkdir(parents=True, exist_ok=True)
        updated["code_dir"] = str(code_dir)
    if "voice" in choices:
        updated["voice_enabled"] = bool(choices["voice"])
    if "online_tools" in choices:
        updated["allow_internet_tools"] = bool(choices["online_tools"])
    if choices.get("budget_gb") is not None:
        updated["storage_budget_gb"] = float(choices["budget_gb"])
    return updated


def start(cfg, choices, *, pull=None, fetch_whisper=None):
    """Save choices and begin (or resume) downloads in the background."""
    with _LOCK:
        state = load_state()
        if state.get("running"):
            raise ValueError("Setup downloads are already running.")
        details = plan(cfg, choices)
        if details["over_budget"] and not choices.get("accept_over_budget"):
            raise ValueError(details["warnings"][0])
        updated = apply_choices(cfg, choices)
        config.save(updated)
        cfg.update(updated)
        previous = {(s["kind"], s["name"]): s for s in state.get("steps", [])}
        steps = []
        for item in details["items"]:
            old = previous.get((item["kind"], item["name"]), {})
            done = item["installed"] or old.get("status") == "done"
            steps.append({"kind": item["kind"], "name": item["name"], "bytes": item["bytes"],
                          "status": "done" if done else "pending", "completed": old.get("completed", 0),
                          "error": ""})
        state = {"steps": steps, "running": True, "error": "", "started": time.time(),
                 "budget_gb": choices.get("budget_gb"),
                 "accepted_over_budget": bool(choices.get("accept_over_budget"))}
        save_state(state)
    worker = threading.Thread(target=_run, args=(cfg, pull or _pull_ollama, fetch_whisper or _fetch_whisper),
                              daemon=True, name="setup-downloads")
    worker.start()
    return worker


def _run(cfg, pull, fetch_whisper):
    state = load_state()
    try:
        for step in state["steps"]:
            if step["status"] == "done":
                continue
            budget = state.get("budget_gb")
            if budget is not None and not state.get("accepted_over_budget"):
                planned = sum(s["bytes"] for s in state["steps"])
                if planned > budget * GB:
                    raise RuntimeError("Downloads would exceed the storage budget. Nothing more was started.")
            step["status"] = "running"
            save_state(state)

            def progress(completed, total=None, step=step):
                step["completed"] = int(completed)
                if total:
                    step["bytes"] = int(total)
                save_state(state)

            try:
                if step["kind"] == "ollama":
                    pull(cfg, step["name"], progress)
                else:
                    fetch_whisper(step["name"])
            except Exception as error:
                step["status"] = "failed"
                step["error"] = str(error)[:500]
                raise
            step["status"] = "done"
            save_state(state)
        state["finished"] = time.time()
        cfg["setup_complete"] = True
        config.save(cfg)
    except Exception as error:
        state["error"] = (str(error) or type(error).__name__)[:500] + " Select Resume setup to continue."
    finally:
        state["running"] = False
        save_state(state)


def _pull_ollama(cfg, name, progress):
    payload = json.dumps({"model": name, "stream": True}).encode()
    request = urllib.request.Request(cfg["ollama_url"].rstrip("/") + "/api/pull", data=payload,
                                     headers={"Content-Type": "application/json"})
    with net.urlopen(request, cfg, timeout=3600, purpose="ollama") as response:
        for raw in response:
            chunk = json.loads(raw or b"{}")
            if chunk.get("error"):
                raise RuntimeError(f"Ollama could not download {name}: {chunk['error']}")
            if chunk.get("completed") is not None:
                progress(chunk["completed"], chunk.get("total"))
            if chunk.get("status") == "success":
                return


def _fetch_whisper(name):
    # Runs in a separate process so HF_HUB_OFFLINE stays on for the rest of Jarvis.
    env = {**os.environ, "HF_HUB_OFFLINE": "0"}
    code = ("from faster_whisper import WhisperModel; "
            f"WhisperModel({name!r}, device='cpu', compute_type='int8')")
    result = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True,
                            timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError("Speech model download failed. " + result.stderr.strip()[-300:])


def summary(cfg):
    checks, _ = prerequisites(cfg)
    state = load_state()
    return {"first_run": not cfg.get("setup_complete"), "checks": checks, "state": state,
            "profile": cfg.get("performance_profile", "standard"),
            "document_folders": cfg.get("document_folders", []),
            "file_folders": cfg.get("file_folders", []), "code_dir": cfg.get("code_dir"),
            "voice": cfg.get("voice_enabled", True), "online_tools": bool(cfg.get("allow_internet_tools")),
            "budget_gb": cfg.get("storage_budget_gb"), "optional_models": list(OPTIONAL_MODELS),
            "shared_cache_note": SHARED_CACHE_NOTE}


def finish_without_downloads(cfg, choices):
    """Save choices and mark setup done when the user wants to download models later."""
    updated = apply_choices(cfg, choices)
    updated["setup_complete"] = True
    config.save(updated)
    cfg.update(updated)
    return summary(cfg)
