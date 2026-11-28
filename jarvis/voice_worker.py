"""Persistent local stdio JSON-RPC neural speech worker (runs in isolated Python 3.12 venv).

Features:
- Automatic NVIDIA CUDA 12 DLL path loading from pip-installed nvidia/* wheels on Windows.
- Explicit compute device routing (`gpu` -> CUDAExecutionProvider, `cpu` -> CPUExecutionProvider)
  reporting the ACTUAL active ONNX Runtime execution provider (`sess.get_providers()[0]`).
- Pre-load SHA-256 model integrity verification against trusted expected digests.
- Genuine incremental chunked streaming (`cmd="synthesize_stream"`) emitting chunk 0 WAV
  immediately while synthesizing subsequent chunks.
"""
import hashlib
import importlib.util
import json
import os
import re
import sys
import time
import wave
from pathlib import Path

# Register pip-installed NVIDIA CUDA 12 / cuDNN DLLs on Windows before importing onnxruntime
if os.name == "nt":
    _nvidia_root = Path(sys.prefix) / "Lib" / "site-packages" / "nvidia"
    if _nvidia_root.is_dir():
        for _bin_dir in _nvidia_root.glob("*/bin"):
            try:
                os.add_dll_directory(str(_bin_dir))
                os.environ["PATH"] = str(_bin_dir) + os.pathsep + os.environ.get("PATH", "")
            except OSError:
                pass

_CACHE: dict[tuple, tuple[object, str]] = {}
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")

TRUSTED_SHA256 = {
    "kokoro-v1.0.int8.onnx": "6e742170d309016e5891a994e1ce1559c702a2ccd0075e67ef7157974f6406cb",
    "kokoro-v1.0.onnx": "7d5df8ecf7d4b1878015a32686053fd0eebe2bc377234608764cc0ef3636a6c5",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return round(wf.getnframes() / float(wf.getframerate() or 1), 3)


def _verify_sha256(path: Path) -> None:
    expected = TRUSTED_SHA256.get(path.name)
    if not expected:
        return
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    actual = h.hexdigest()
    if actual != expected:
        raise ValueError(f"Model integrity check failed for {path.name}: expected {expected[:12]}..., got {actual[:12]}...")


def _health() -> dict:
    pkgs = {
        name: importlib.util.find_spec(name) is not None
        for name in ("kokoro_onnx", "onnxruntime", "kokoro", "qwen_tts", "chatterbox", "soundfile", "torch")
    }
    ort_providers = []
    if pkgs["onnxruntime"]:
        try:
            import onnxruntime as ort
            ort_providers = list(ort.get_available_providers())
        except Exception:
            pass
    cuda_ok = "CUDAExecutionProvider" in ort_providers
    if not cuda_ok and pkgs["torch"]:
        try:
            import torch
            cuda_ok = bool(torch.cuda.is_available())
        except Exception:
            pass
    return {
        "ok": True,
        "python": sys.version.split()[0],
        "packages": pkgs,
        "ort_providers": ort_providers,
        "cuda_available": cuda_ok,
        "loaded_models": [f"{k[0]}:{k[2]}({v[1]})" for k, v in _CACHE.items()],
    }


def _find_kokoro_onnx_files(model_dir: Path, *, prefer_fp32: bool = False) -> tuple[Path, Path]:
    order = (
        (("kokoro-v1.0-onnx-fp32", "kokoro-v1.0.onnx"), ("kokoro-v1.0-onnx-int8", "kokoro-v1.0.int8.onnx"))
        if prefer_fp32
        else (("kokoro-v1.0-onnx-int8", "kokoro-v1.0.int8.onnx"), ("kokoro-v1.0-onnx-fp32", "kokoro-v1.0.onnx"))
    )
    for pack, fname in order:
        m = model_dir / pack / fname
        v = model_dir / pack / "voices-v1.0.bin"
        if m.is_file() and v.is_file():
            return m, v
    raise FileNotFoundError(f"Kokoro ONNX model files not found in {model_dir}.")


def _get_kokoro_session(model_dir: Path, device: str, *, prefer_fp32: bool | None = None) -> tuple[object, str, str]:
    import onnxruntime as ort
    from kokoro_onnx import Kokoro

    avail = set(ort.get_available_providers())
    dev_key = "cpu" if device == "cpu" else "gpu"
    use_cuda = dev_key != "cpu" and "CUDAExecutionProvider" in avail
    # Empirical benchmark on Windows i7-10875H + Quadro RTX 5000:
    # FP32 (kokoro-v1.0.onnx) is 14.9x faster on CUDA GPU (RTF 0.153 vs 2.262) and
    # 3.1x faster on CPU (RTF 0.626 vs 1.941) than int8. Prefer FP32 whenever installed,
    # falling back seamlessly to int8 if only the 92 MB int8 pack is installed.
    want_fp32 = True if prefer_fp32 is None else bool(prefer_fp32)
    model_path, voices_path = _find_kokoro_onnx_files(model_dir, prefer_fp32=want_fp32)
    cache_key = ("kokoro_onnx", str(model_path), dev_key)
    if cache_key in _CACHE:
        return _CACHE[cache_key]

    # Verify trusted SHA-256 BEFORE loading any model file into ONNX Runtime
    _verify_sha256(model_path)
    _verify_sha256(voices_path)

    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if use_cuda else ["CPUExecutionProvider"]
    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess = ort.InferenceSession(str(model_path), sess_options=sess_opts, providers=providers)
    actual_provider = (sess.get_providers() or ["CPUExecutionProvider"])[0]
    kokoro = Kokoro.from_session(sess, str(voices_path))
    entry = (kokoro, actual_provider, model_path.name)
    _CACHE[cache_key] = entry
    return entry


def _synth_kokoro_onnx(text: str, voice: str, speed: float, device: str, model_dir: Path, out_path: Path, *, prefer_fp32: bool | None = None) -> dict:
    import soundfile as sf

    started = time.perf_counter()
    kokoro, actual_provider, model_file = _get_kokoro_session(model_dir, device, prefer_fp32=prefer_fp32)
    lang = "en-gb" if str(voice or "").startswith(("bm_", "bf_")) else "en-us"
    t_synth = time.perf_counter()
    samples, sample_rate = kokoro.create(text, voice=voice or "bm_george", speed=max(0.5, min(2.0, float(speed))), lang=lang)
    ttfa_s = round(time.perf_counter() - t_synth, 3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), samples, sample_rate)
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True,
        "engine": "kokoro_onnx",
        "model_file": model_file,
        "voice": voice or "bm_george",
        "lang": lang,
        "actual_provider": actual_provider,
        "sample_rate": int(sample_rate),
        "wav_path": str(out_path),
        "bytes": out_path.stat().st_size,
        "ttfa_seconds": ttfa_s,
        "total_seconds": total_s,
        "audio_seconds": audio_s,
        "rtf": round(total_s / audio_s, 3) if audio_s > 0 else None,
    }


def _synth_kokoro_stream(req_id, text: str, voice: str, speed: float, device: str, model_dir: Path, out_dir: Path, *, prefer_fp32: bool | None = None) -> dict:
    """Incrementally synthesize sentence-by-sentence, emitting each chunk WAV immediately."""
    import soundfile as sf

    started = time.perf_counter()
    kokoro, actual_provider, model_file = _get_kokoro_session(model_dir, device, prefer_fp32=prefer_fp32)
    lang = "en-gb" if str(voice or "").startswith(("bm_", "bf_")) else "en-us"
    sentences = [s.strip() for s in _SENTENCE_SPLIT.split(text.strip()) if s.strip()]
    if not sentences:
        sentences = [text.strip()]
    out_dir.mkdir(parents=True, exist_ok=True)

    ttfa_s = None
    total_audio = 0.0
    chunk_paths = []
    for idx, sent in enumerate(sentences):
        samples, sr = kokoro.create(sent, voice=voice or "bm_george", speed=max(0.5, min(2.0, float(speed))), lang=lang)
        cpath = out_dir / f"stream_{req_id}_{idx}.wav"
        sf.write(str(cpath), samples, sr)
        cdur = _wav_duration(cpath)
        total_audio += cdur
        if ttfa_s is None:
            ttfa_s = round(time.perf_counter() - started, 3)
        chunk_paths.append(str(cpath))
        sys.stdout.write(json.dumps({
            "id": req_id,
            "ok": True,
            "stream": True,
            "done": False,
            "chunk": idx,
            "wav_path": str(cpath),
            "audio_seconds": cdur,
            "actual_provider": actual_provider,
            "model_file": model_file,
        }) + "\n")
        sys.stdout.flush()

    total_s = round(time.perf_counter() - started, 3)
    return {
        "ok": True,
        "stream": True,
        "done": True,
        "engine": "kokoro_onnx",
        "model_file": model_file,
        "voice": voice or "bm_george",
        "actual_provider": actual_provider,
        "chunks": len(chunk_paths),
        "wav_paths": chunk_paths,
        "ttfa_seconds": ttfa_s,
        "total_seconds": total_s,
        "audio_seconds": round(total_audio, 3),
        "rtf": round(total_s / total_audio, 3) if total_audio > 0 else None,
    }


def _synth_kokoro_pytorch(text: str, voice: str, speed: float, out_path: Path) -> dict:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    lang_code = "b" if str(voice or "").startswith(("bm_", "bf_")) else "a"
    cache_key = ("kokoro", lang_code, "auto")
    started = time.perf_counter()
    if cache_key not in _CACHE:
        _CACHE[cache_key] = (KPipeline(lang_code=lang_code), "PyTorch")
    pipe, actual_provider = _CACHE[cache_key]
    chunks = []
    ttfa_s = None
    for _, _, audio in pipe(text, voice=voice or "bm_george", speed=max(0.5, min(2.0, float(speed)))):
        if ttfa_s is None:
            ttfa_s = round(time.perf_counter() - started, 3)
        chunks.append(audio)
    if not chunks:
        raise RuntimeError("Kokoro PyTorch produced no audio chunks.")
    combined = np.concatenate(chunks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), combined, 24000)
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True, "engine": "kokoro", "voice": voice or "bm_george", "actual_provider": actual_provider,
        "sample_rate": 24000, "wav_path": str(out_path), "bytes": out_path.stat().st_size,
        "ttfa_seconds": ttfa_s, "total_seconds": total_s, "audio_seconds": audio_s,
        "rtf": round(total_s / audio_s, 3) if audio_s > 0 else None,
    }


def _synth_qwen3_tts(text: str, voice: str, instruct: str, device: str, model_dir: Path, out_path: Path) -> dict:
    import soundfile as sf
    import torch
    from qwen_tts import Qwen3TTSModel

    local_dir = model_dir / "qwen3-tts-voice-design"
    if not (local_dir / "config.json").is_file():
        raise FileNotFoundError(f"Qwen3-TTS local weights not found in {local_dir}.")
    dev = "cuda:0" if (device != "cpu" and torch.cuda.is_available()) else "cpu"
    cache_key = ("qwen3_tts", str(local_dir), dev)
    started = time.perf_counter()
    if cache_key not in _CACHE:
        _CACHE[cache_key] = (Qwen3TTSModel.from_pretrained(str(local_dir), device_map=dev), dev)
    model, actual_provider = _CACHE[cache_key]
    wavs, sr = model.generate_voice_design(text=text, language="English", instruct=instruct or "Calm British assistant.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), wavs[0], int(sr))
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True, "engine": "qwen3_tts", "voice": voice or "jarvis_british_butler", "actual_provider": actual_provider,
        "sample_rate": int(sr), "wav_path": str(out_path), "bytes": out_path.stat().st_size,
        "ttfa_seconds": total_s, "total_seconds": total_s, "audio_seconds": audio_s,
        "rtf": round(total_s / audio_s, 3) if audio_s > 0 else None,
    }


def _synth_chatterbox(text: str, voice: str, device: str, out_path: Path) -> dict:
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS

    dev = "cuda" if (device != "cpu" and torch.cuda.is_available()) else "cpu"
    cache_key = ("chatterbox", "default", dev)
    started = time.perf_counter()
    if cache_key not in _CACHE:
        _CACHE[cache_key] = (ChatterboxTTS.from_pretrained(device=dev), dev)
    model, actual_provider = _CACHE[cache_key]
    wav = model.generate(text)
    audio = wav.squeeze().detach().cpu().numpy()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio, int(model.sr))
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True, "engine": "chatterbox", "voice": voice or "default_calm", "actual_provider": actual_provider,
        "sample_rate": int(model.sr), "wav_path": str(out_path), "bytes": out_path.stat().st_size,
        "ttfa_seconds": total_s, "total_seconds": total_s, "audio_seconds": audio_s,
        "rtf": round(total_s / audio_s, 3) if audio_s > 0 else None,
    }


def handle(req: dict) -> dict:
    cmd = str(req.get("cmd") or "").strip().lower()
    if cmd == "health":
        return _health()
    if cmd == "shutdown":
        _CACHE.clear()
        return {"ok": True, "shutdown": True}
    if cmd == "synthesize_stream":
        return _synth_kokoro_stream(
            req.get("id"),
            str(req.get("text") or ""),
            str(req.get("voice") or "bm_george"),
            float(req.get("speed") or 1.0),
            str(req.get("device") or "auto").strip().lower(),
            Path(str(req.get("model_dir") or "")),
            Path(str(req.get("out_dir") or "")),
            prefer_fp32=req.get("prefer_fp32"),
        )
    if cmd == "synthesize":
        eng = str(req.get("engine") or "").strip().lower()
        text = str(req.get("text") or "").strip()
        voice = str(req.get("voice") or "").strip()
        speed = float(req.get("speed") or 1.0)
        device = str(req.get("device") or "auto").strip().lower()
        model_dir = Path(str(req.get("model_dir") or ""))
        out_path = Path(str(req.get("out_path") or ""))
        if not text:
            raise ValueError("Empty synthesis text.")
        if eng == "kokoro_onnx":
            return _synth_kokoro_onnx(text, voice, speed, device, model_dir, out_path, prefer_fp32=req.get("prefer_fp32"))
        if eng == "kokoro":
            return _synth_kokoro_pytorch(text, voice, speed, out_path)
        if eng == "qwen3_tts":
            return _synth_qwen3_tts(text, voice, str(req.get("instruct") or ""), device, model_dir, out_path)
        if eng == "chatterbox":
            return _synth_chatterbox(text, voice, device, out_path)
        raise ValueError(f"Unsupported neural worker engine '{eng}'.")
    raise ValueError(f"Unknown worker command '{cmd}'.")


def main() -> int:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        req_id = None
        try:
            req = json.loads(line)
            req_id = req.get("id")
            res = handle(req)
            res["id"] = req_id
            sys.stdout.write(json.dumps(res) + "\n")
            sys.stdout.flush()
            if res.get("shutdown"):
                break
        except Exception as exc:
            sys.stdout.write(json.dumps({"id": req_id, "ok": False, "error": f"{type(exc).__name__}: {exc}"}) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
