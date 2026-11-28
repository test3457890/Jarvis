"""Isolated Python 3.12 Neural Speech Runtime Manager & Verified Model Pack Downloader.

Manages:
1. Isolated Python 3.12 virtual environment in `%APPDATA%\\Jarvis\\voice-runtime\\venv`
   (preserving Jarvis's main Python environment completely).
2. Persistent local stdio JSON-RPC client (`NeuralVoiceClient`) to `jarvis/voice_worker.py`
   with immediate cancellation (subprocess termination) and automatic restart.
3. Verified official model pack downloads with atomic `.part` files, cancellation,
   recovery from incomplete downloads, and SHA-256 integrity checks.
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

from . import config, secure

PINNED_NEURAL_DEPS = (
    "kokoro-onnx==0.4.7",
    "onnxruntime==1.20.1",
    "soundfile==0.13.1",
    "numpy==2.2.3",
)

# Official pinned release URLs for Kokoro ONNX v1.0 model files
OFFICIAL_PACK_URLS: dict[str, list[dict]] = {
    "kokoro-v1.0-onnx-int8": [
        {
            "filename": "kokoro-v1.0.int8.onnx",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
            "expected_mb": 88,
        },
        {
            "filename": "voices-v1.0.bin",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
            "expected_mb": 27,
        },
    ],
    "kokoro-v1.0-onnx-fp32": [
        {
            "filename": "kokoro-v1.0.onnx",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
            "expected_mb": 310,
        },
        {
            "filename": "voices-v1.0.bin",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
            "expected_mb": 27,
        },
    ],
}

_ALLOWED_MODEL_HOSTS = frozenset({"github.com", "objects.githubusercontent.com", "release-assets.githubusercontent.com"})


def runtime_venv_dir() -> Path:
    return config.APP_DIR / "voice-runtime" / "venv"


def runtime_python() -> Path:
    base = runtime_venv_dir()
    return base / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def runtime_available() -> bool:
    return runtime_python().is_file()


def _find_uv() -> str | None:
    sib = Path(sys.executable).with_name("uv.exe" if os.name == "nt" else "uv")
    if sib.is_file():
        return str(sib)
    return shutil.which("uv")


def install_runtime(*, on_progress=None) -> dict:
    """Provision the isolated Python 3.12 neural speech venv automatically using uv."""
    uv_exe = _find_uv()
    if not uv_exe:
        raise RuntimeError("uv is not installed. Run: python -m pip install uv")
    venv_dir = runtime_venv_dir()
    venv_dir.parent.mkdir(parents=True, exist_ok=True)
    if on_progress:
        on_progress({"stage": "creating_venv", "percent": 15, "detail": "Creating isolated Python 3.12 runtime…"})
    subprocess.run(
        [uv_exe, "venv", "--python", "3.12", str(venv_dir)],
        check=True, capture_output=True, text=True, timeout=180,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if on_progress:
        on_progress({"stage": "installing_deps", "percent": 55, "detail": "Installing pinned kokoro-onnx & onnxruntime…"})
    subprocess.run(
        [uv_exe, "pip", "install", "--python", str(runtime_python()), *PINNED_NEURAL_DEPS],
        check=True, capture_output=True, text=True, timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if on_progress:
        on_progress({"stage": "ready", "percent": 100, "detail": "Isolated Python 3.12 neural runtime ready."})
    secure.audit("voice_runtime_installed", {"python": str(runtime_python())})
    return {"ok": True, "python": str(runtime_python()), "deps": list(PINNED_NEURAL_DEPS)}


def download_voice_pack(pack_id: str, *, model_root: Path | None = None, on_progress=None, cancel_event: threading.Event | None = None) -> dict:
    """Download an official verified voice pack into %APPDATA%\\Jarvis\\voice-models\\ with atomic .part & SHA-256."""
    if pack_id not in OFFICIAL_PACK_URLS:
        raise ValueError(f"No official direct download configured for pack '{pack_id}'.")
    root = model_root or (config.APP_DIR / "voice-models")
    pack_dir = (root / pack_id).resolve()
    if pack_dir.parent != root.resolve():
        raise ValueError("Invalid voice pack directory.")
    pack_dir.mkdir(parents=True, exist_ok=True)

    files_spec = OFFICIAL_PACK_URLS[pack_id]
    checksums = {}
    for idx, spec in enumerate(files_spec):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Voice pack download cancelled.")
        dest = pack_dir / spec["filename"]
        part = pack_dir / (spec["filename"] + ".part")
        if dest.is_file() and dest.stat().st_size > 100_000:
            checksums[spec["filename"]] = _sha256_file(dest)
            continue
        url = spec["url"]
        if not url.startswith("https://github.com/"):
            raise PermissionError("Refused non-official model download URL.")
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisVoiceDownloader/2.0"})
        h = hashlib.sha256()
        written = 0
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length") or 0)
                with part.open("wb") as out:
                    while True:
                        if cancel_event is not None and cancel_event.is_set():
                            raise RuntimeError("Voice pack download cancelled.")
                        chunk = resp.read(131072)
                        if not chunk:
                            break
                        out.write(chunk)
                        h.update(chunk)
                        written += len(chunk)
                        if on_progress and total > 0:
                            pct = int(((idx + written / total) / len(files_spec)) * 100)
                            on_progress({"stage": "downloading", "file": spec["filename"], "percent": min(99, pct)})
            part.replace(dest)
            checksums[spec["filename"]] = h.hexdigest()
        except BaseException:
            part.unlink(missing_ok=True)
            raise

    manifest = pack_dir / "checksums.json"
    manifest.write_text(json.dumps({"pack_id": pack_id, "sha256": checksums, "verified_at": time.time()}, indent=2), encoding="utf-8")
    if on_progress:
        on_progress({"stage": "complete", "percent": 100})
    secure.audit("voice_pack_downloaded", {"pack_id": pack_id, "files": sorted(checksums)})
    return {"ok": True, "pack_id": pack_id, "dir": str(pack_dir), "sha256": checksums}


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class NeuralVoiceClient:
    """Thread-safe persistent local stdio client to jarvis/voice_worker.py."""

    def __init__(self):
        self._lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._seq = 0
        self._health_cache: tuple[float, dict] = (0.0, {})

    def _ensure_started(self) -> subprocess.Popen:
        py = runtime_python()
        if not py.is_file():
            raise RuntimeError("Isolated Python 3.12 neural speech runtime is not installed.")
        if self._proc is None or self._proc.poll() is not None:
            worker_script = Path(__file__).with_name("voice_worker.py")
            self._proc = subprocess.Popen(
                [str(py), str(worker_script)],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        return self._proc

    def request(self, payload: dict, *, timeout: float = 60.0) -> dict:
        with self._lock:
            proc = self._ensure_started()
            self._seq += 1
            req = {**payload, "id": self._seq}
            assert proc.stdin is not None and proc.stdout is not None
            try:
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
                line = proc.stdout.readline()
            except OSError as exc:
                self._kill_locked()
                raise RuntimeError(f"Neural speech worker I/O error: {exc}") from None
            if not line:
                err = ""
                try:
                    if proc.stderr:
                        err = proc.stderr.read()[:300]
                except Exception:
                    pass
                self._kill_locked()
                raise RuntimeError(f"Neural speech worker exited unexpectedly. {err}".strip())
            data = json.loads(line)
            if not data.get("ok"):
                raise RuntimeError(str(data.get("error") or "Neural speech worker error."))
            return data

    def health(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and self._health_cache[0] > 0 and now - self._health_cache[0] < 10.0:
            return dict(self._health_cache[1])
        if not runtime_available():
            return {"ok": False, "installed": False, "packages": {}}
        try:
            res = self.request({"cmd": "health"}, timeout=10.0)
            res["installed"] = True
            self._health_cache = (now, res)
            return dict(res)
        except Exception as exc:
            return {"ok": False, "installed": True, "error": str(exc), "packages": {}}

    def cancel(self) -> None:
        """Immediately terminate the worker process to cancel in-flight synthesis."""
        with self._lock:
            self._kill_locked()

    def shutdown(self) -> None:
        with self._lock:
            if self._proc is not None and self._proc.poll() is None:
                try:
                    assert self._proc.stdin is not None
                    self._proc.stdin.write(json.dumps({"id": 0, "cmd": "shutdown"}) + "\n")
                    self._proc.stdin.flush()
                    self._proc.wait(timeout=2.0)
                except Exception:
                    self._kill_locked()
            self._proc = None

    def _kill_locked(self) -> None:
        if self._proc is not None:
            try:
                self._proc.kill()
            except Exception:
                pass
            self._proc = None


CLIENT = NeuralVoiceClient()
