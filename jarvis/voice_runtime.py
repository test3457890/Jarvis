"""Isolated Python 3.12 Neural Speech Runtime Manager, Non-Blocking Stdio Client & Verified Downloader.

Reliability & Security Architecture:
- Dedicated background stdout reader thread (routes responses by request ID; rejects stale IDs).
- Dedicated background stderr drainer thread (bounded ring buffer; prevents pipe deadlock).
- Non-blocking `cancel()`: terminates the worker subprocess immediately without contending on
  an in-flight `request()` lock, waking all waiting callers immediately.
- Real enforced `timeout` deadlines on every request (kills hung worker and raises TimeoutError).
- Trusted expected SHA-256 digests verified on download AND before model load.
- Every HTTP redirect hop is validated against `_ALLOWED_MODEL_HOSTS` (HTTPS only).
- Enforces Jarvis offline (`allow_internet_tools`) and `lockdown` policies on model downloads.
"""
from collections import deque
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import config, secure

PINNED_NEURAL_DEPS = (
    "kokoro-onnx==0.4.7",
    "onnxruntime-gpu>=1.20,<1.23",
    "nvidia-cublas-cu12",
    "nvidia-cudnn-cu12",
    "nvidia-cuda-runtime-cu12",
    "nvidia-cufft-cu12",
    "soundfile==0.13.1",
    "numpy==2.2.3",
)

# Trusted SHA-256 hashes verified against official thewh1teagle/kokoro-onnx model-files-v1.0 release
TRUSTED_MODEL_SHA256: dict[str, str] = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}

OFFICIAL_PACK_URLS: dict[str, list[dict]] = {
    "kokoro-v1.0-onnx-int8": [
        {
            "filename": "kokoro-v1.0.int8.onnx",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.int8.onnx",
            "expected_mb": 88,
            "sha256": TRUSTED_MODEL_SHA256["kokoro-v1.0.int8.onnx"],
        },
        {
            "filename": "voices-v1.0.bin",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
            "expected_mb": 27,
            "sha256": TRUSTED_MODEL_SHA256["voices-v1.0.bin"],
        },
    ],
    "kokoro-v1.0-onnx-fp32": [
        {
            "filename": "kokoro-v1.0.onnx",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
            "expected_mb": 310,
            "sha256": TRUSTED_MODEL_SHA256["kokoro-v1.0.onnx"],
        },
        {
            "filename": "voices-v1.0.bin",
            "url": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
            "expected_mb": 27,
            "sha256": TRUSTED_MODEL_SHA256["voices-v1.0.bin"],
        },
    ],
}

_ALLOWED_MODEL_HOSTS = frozenset({
    "github.com",
    "objects.githubusercontent.com",
    "release-assets.githubusercontent.com",
})


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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def verify_file_integrity(path: Path, expected_sha256: str | None = None) -> tuple[bool, str]:
    """Verify a model file against its trusted expected SHA-256 hash."""
    expected = expected_sha256 or TRUSTED_MODEL_SHA256.get(path.name)
    if not expected:
        return True, "no_pinned_hash"
    if not path.is_file():
        return False, f"Missing file: {path.name}"
    actual = _sha256_file(path)
    if actual != expected.lower():
        secure.audit("voice_model_integrity_failed", {"file": path.name, "expected": expected[:16], "actual": actual[:16]})
        return False, f"SHA-256 mismatch for {path.name}: expected {expected[:12]}..., got {actual[:12]}..."
    return True, actual


def validate_download_url(url: str) -> str:
    parsed = urllib.parse.urlsplit(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or host not in _ALLOWED_MODEL_HOSTS or parsed.username is not None:
        secure.audit("voice_download_blocked", {"host": host or "invalid"})
        raise PermissionError(f"Blocked model download URL host '{host}'. Only verified GitHub release hosts over HTTPS are permitted.")
    return url


class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        validate_download_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def install_runtime(*, cfg: dict | None = None, on_progress=None) -> dict:
    """Provision the isolated Python 3.12 neural speech venv automatically using uv."""
    if cfg is not None:
        if cfg.get("lockdown"):
            raise PermissionError("Cannot install voice runtime while Lockdown is active.")
        if not cfg.get("allow_internet_tools"):
            raise PermissionError("Enable Internet tools before installing the optional Python 3.12 voice runtime.")
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
        on_progress({"stage": "installing_deps", "percent": 55, "detail": "Installing pinned neural speech dependencies…"})
    subprocess.run(
        [uv_exe, "pip", "install", "--python", str(runtime_python()), *PINNED_NEURAL_DEPS],
        check=True, capture_output=True, text=True, timeout=360,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if on_progress:
        on_progress({"stage": "ready", "percent": 100, "detail": "Isolated Python 3.12 neural runtime ready."})
    secure.audit("voice_runtime_installed", {"python": str(runtime_python())})
    return {"ok": True, "python": str(runtime_python()), "deps": list(PINNED_NEURAL_DEPS)}


def download_voice_pack(
    pack_id: str,
    *,
    cfg: dict | None = None,
    model_root: Path | None = None,
    on_progress=None,
    cancel_event: threading.Event | None = None,
) -> dict:
    """Download an official verified voice pack with redirect validation, offline guard, and trusted SHA-256 checks."""
    if cfg is not None:
        if cfg.get("lockdown"):
            raise PermissionError("Voice pack downloads are blocked during Lockdown.")
        if not cfg.get("allow_internet_tools"):
            raise PermissionError("Voice pack downloads require Internet tools to be enabled.")
    if pack_id not in OFFICIAL_PACK_URLS:
        raise ValueError(f"No official direct download configured for pack '{pack_id}'.")
    root = model_root or (config.APP_DIR / "voice-models")
    pack_dir = (root / pack_id).resolve()
    if pack_dir.parent != root.resolve():
        raise ValueError("Invalid voice pack directory.")
    pack_dir.mkdir(parents=True, exist_ok=True)

    opener = urllib.request.build_opener(_AllowlistRedirectHandler())
    files_spec = OFFICIAL_PACK_URLS[pack_id]
    checksums = {}
    for idx, spec in enumerate(files_spec):
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("Voice pack download cancelled.")
        dest = pack_dir / spec["filename"]
        part = pack_dir / (spec["filename"] + ".part")
        if dest.is_file() and dest.stat().st_size > 100_000:
            ok, info = verify_file_integrity(dest, spec.get("sha256"))
            if ok:
                checksums[spec["filename"]] = _sha256_file(dest)
                continue
            dest.unlink(missing_ok=True)

        url = validate_download_url(spec["url"])
        req = urllib.request.Request(url, headers={"User-Agent": "JarvisVoiceDownloader/2.0"})
        h = hashlib.sha256()
        written = 0
        try:
            with opener.open(req, timeout=60) as resp:
                validate_download_url(resp.geturl())
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
            digest = h.hexdigest()
            expected = spec.get("sha256")
            if expected and digest != expected.lower():
                part.unlink(missing_ok=True)
                secure.audit("voice_download_hash_mismatch", {"file": spec["filename"]})
                raise ValueError(f"Integrity verification failed for {spec['filename']}: SHA-256 mismatch.")
            part.replace(dest)
            checksums[spec["filename"]] = digest
        except BaseException:
            part.unlink(missing_ok=True)
            raise

    manifest = pack_dir / "checksums.json"
    manifest.write_text(json.dumps({"pack_id": pack_id, "sha256": checksums, "verified_at": time.time()}, indent=2), encoding="utf-8")
    if on_progress:
        on_progress({"stage": "complete", "percent": 100})
    secure.audit("voice_pack_downloaded", {"pack_id": pack_id, "files": sorted(checksums)})
    return {"ok": True, "pack_id": pack_id, "dir": str(pack_dir), "sha256": checksums}


class _PendingRequest:
    def __init__(self, proc: subprocess.Popen, on_chunk=None):
        self.proc = proc
        self.event = threading.Event()
        self.result: dict | None = None
        self.error: Exception | None = None
        self.on_chunk = on_chunk


class NeuralVoiceClient:
    """Thread-safe, non-blocking-cancel local stdio JSON-RPC client to jarvis/voice_worker.py."""

    def __init__(self):
        self._proc_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._proc: subprocess.Popen | None = None
        self._seq = 0
        self._pending: dict[int, _PendingRequest] = {}
        self._stderr_lines: deque[str] = deque(maxlen=100)
        self._stale_dropped = 0
        self._health_cache: tuple[float, dict] = (0.0, {})

    def _ensure_started(self) -> subprocess.Popen:
        with self._proc_lock:
            py = runtime_python()
            if not py.is_file():
                raise RuntimeError("Isolated Python 3.12 neural speech runtime is not installed.")
            if self._proc is None or self._proc.poll() is not None:
                worker_script = Path(__file__).with_name("voice_worker.py")
                proc = subprocess.Popen(
                    [str(py), str(worker_script)],
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    bufsize=1,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self._proc = proc
                threading.Thread(target=self._stdout_reader, args=(proc,), daemon=True, name="voice-stdout").start()
                threading.Thread(target=self._stderr_drainer, args=(proc,), daemon=True, name="voice-stderr").start()
            return self._proc

    def _stdout_reader(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except ValueError:
                    continue
                req_id = data.get("id")
                with self._pending_lock:
                    slot = self._pending.get(req_id)
                if slot is None:
                    self._stale_dropped += 1
                    continue
                if data.get("stream") and not data.get("done"):
                    if slot.on_chunk:
                        try:
                            slot.on_chunk(data)
                        except Exception:
                            pass
                    continue
                slot.result = data
                slot.event.set()
        finally:
            self._fail_pending_for(proc, RuntimeError("Neural speech worker exited or was cancelled."))

    def _stderr_drainer(self, proc: subprocess.Popen) -> None:
        assert proc.stderr is not None
        try:
            for line in proc.stderr:
                clean = line.strip()
                if clean:
                    self._stderr_lines.append(clean[:240])
        except Exception:
            pass

    def _fail_pending_for(self, proc: subprocess.Popen | None, exc: Exception) -> None:
        with self._pending_lock:
            to_fail = [
                (rid, slot) for rid, slot in list(self._pending.items())
                if proc is None or slot.proc is proc
            ]
            for rid, _ in to_fail:
                self._pending.pop(rid, None)
        for _, slot in to_fail:
            if slot.result is None and slot.error is None:
                slot.error = exc
            slot.event.set()

    def request(self, payload: dict, *, timeout: float = 60.0, on_chunk=None) -> dict:
        """Send a JSON-RPC request with enforced timeout and non-blocking cancellation support."""
        proc = self._ensure_started()
        with self._pending_lock:
            self._seq += 1
            req_id = self._seq
            slot = _PendingRequest(proc=proc, on_chunk=on_chunk)
            self._pending[req_id] = slot

        req = {**payload, "id": req_id}
        try:
            with self._write_lock:
                assert proc.stdin is not None
                proc.stdin.write(json.dumps(req) + "\n")
                proc.stdin.flush()
        except OSError as exc:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            self.cancel()
            raise RuntimeError(f"Neural speech worker write error: {exc}") from None

        # Wait WITHOUT holding any lock so cancel() is instantaneous!
        finished = slot.event.wait(timeout=max(0.1, float(timeout)))
        with self._pending_lock:
            self._pending.pop(req_id, None)

        if not finished:
            self.cancel()
            raise TimeoutError(f"Neural speech worker timed out after {timeout}s.")
        if slot.error is not None:
            raise slot.error
        data = slot.result or {}
        if data.get("id") != req_id:
            raise RuntimeError("Mismatched neural speech worker response ID.")
        if not data.get("ok"):
            raise RuntimeError(str(data.get("error") or "Neural speech worker error."))
        return data

    def health(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if not force and self._health_cache[0] > 0 and now - self._health_cache[0] < 10.0:
            return dict(self._health_cache[1])
        if not runtime_available():
            return {"ok": False, "installed": False, "packages": {}, "ort_providers": []}
        try:
            res = self.request({"cmd": "health"}, timeout=15.0)
            res["installed"] = True
            res["stale_dropped"] = self._stale_dropped
            self._health_cache = (now, res)
            return dict(res)
        except Exception as exc:
            return {"ok": False, "installed": True, "error": str(exc), "packages": {}, "ort_providers": []}

    def cancel(self) -> None:
        """Immediately terminate the worker process WITHOUT waiting on in-flight requests."""
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is not None:
            try:
                proc.kill()
            except Exception:
                pass
        self._fail_pending_for(proc, RuntimeError("Neural speech synthesis cancelled."))

    def shutdown(self) -> None:
        with self._proc_lock:
            proc = self._proc
            self._proc = None
        if proc is not None and proc.poll() is None:
            try:
                assert proc.stdin is not None
                with self._write_lock:
                    proc.stdin.write(json.dumps({"id": 0, "cmd": "shutdown"}) + "\n")
                    proc.stdin.flush()
                proc.wait(timeout=2.0)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        self._fail_pending_for(proc, RuntimeError("Neural speech worker shut down."))

    def recent_stderr(self) -> list[str]:
        return list(self._stderr_lines)


CLIENT = NeuralVoiceClient()
