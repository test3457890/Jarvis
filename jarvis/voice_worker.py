"""Persistent local stdio JSON-RPC neural speech worker.

Designed to run inside Jarvis's isolated Python 3.12 neural speech runtime
(`%APPDATA%\\Jarvis\\voice-runtime\\venv`) so Jarvis's primary environment remains
untouched and zero network ports are opened.

Protocol (one JSON object per line on stdin -> one JSON object per line on stdout):
  {"id": 1, "cmd": "health"}
  {"id": 2, "cmd": "synthesize", "engine": "kokoro_onnx", "voice": "bm_george",
   "text": "...", "speed": 1.0, "device": "auto", "model_dir": "...", "out_path": "..."}
  {"id": 3, "cmd": "shutdown"}
"""
import importlib.util
import json
import os
import sys
import time
import wave
from pathlib import Path


_CACHE: dict[tuple, object] = {}


def _wav_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return round(wf.getnframes() / float(wf.getframerate() or 1), 3)


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
    cuda_ok = False
    if pkgs["torch"]:
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
        "loaded_models": [f"{k[0]}:{k[1]}" for k in _CACHE],
    }


def _find_kokoro_onnx_files(model_dir: Path) -> tuple[Path, Path]:
    for pack, fname in (
        ("kokoro-v1.0-onnx-int8", "kokoro-v1.0.int8.onnx"),
        ("kokoro-v1.0-onnx-fp32", "kokoro-v1.0.onnx"),
    ):
        m = model_dir / pack / fname
        v = model_dir / pack / "voices-v1.0.bin"
        if m.is_file() and v.is_file():
            return m, v
    raise FileNotFoundError(f"Kokoro ONNX model files not found in {model_dir}.")


def _synth_kokoro_onnx(text: str, voice: str, speed: float, model_dir: Path, out_path: Path) -> dict:
    import soundfile as sf
    from kokoro_onnx import Kokoro

    model_path, voices_path = _find_kokoro_onnx_files(model_dir)
    cache_key = ("kokoro_onnx", str(model_path))
    started = time.perf_counter()
    if cache_key not in _CACHE:
        _CACHE[cache_key] = Kokoro(str(model_path), str(voices_path))
    kokoro = _CACHE[cache_key]
    lang = "en-gb" if str(voice or "").startswith(("bm_", "bf_")) else "en-us"
    t_first = time.perf_counter()
    samples, sample_rate = kokoro.create(text, voice=voice or "bm_george", speed=max(0.5, min(2.0, float(speed))), lang=lang)
    ttfa_s = round(time.perf_counter() - t_first, 3)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), samples, sample_rate)
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True,
        "engine": "kokoro_onnx",
        "voice": voice or "bm_george",
        "lang": lang,
        "sample_rate": int(sample_rate),
        "wav_path": str(out_path),
        "bytes": out_path.stat().st_size,
        "ttfa_seconds": ttfa_s,
        "total_seconds": total_s,
        "audio_seconds": audio_s,
        "rtf": round(total_s / audio_s, 3) if audio_s > 0 else None,
    }


def _synth_kokoro_pytorch(text: str, voice: str, speed: float, out_path: Path) -> dict:
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    lang_code = "b" if str(voice or "").startswith(("bm_", "bf_")) else "a"
    cache_key = ("kokoro", lang_code)
    started = time.perf_counter()
    if cache_key not in _CACHE:
        _CACHE[cache_key] = KPipeline(lang_code=lang_code)
    pipe = _CACHE[cache_key]
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
        "ok": True, "engine": "kokoro", "voice": voice or "bm_george", "sample_rate": 24000,
        "wav_path": str(out_path), "bytes": out_path.stat().st_size,
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
        _CACHE[cache_key] = Qwen3TTSModel.from_pretrained(str(local_dir), device_map=dev)
    model = _CACHE[cache_key]
    wavs, sr = model.generate_voice_design(text=text, language="English", instruct=instruct or "Calm British assistant.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), wavs[0], int(sr))
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True, "engine": "qwen3_tts", "voice": voice or "jarvis_british_butler", "sample_rate": int(sr),
        "wav_path": str(out_path), "bytes": out_path.stat().st_size,
        "ttfa_seconds": total_s, "total_seconds": total_s, "audio_seconds": audio_s,
        "rtf": round(total_s / audio_s, 3) if audio_s > 0 else None,
    }


def _synth_chatterbox(text: str, voice: str, device: str, out_path: Path) -> dict:
    import soundfile as sf
    import torch
    from chatterbox.tts import ChatterboxTTS

    dev = "cuda" if (device != "cpu" and torch.cuda.is_available()) else "cpu"
    cache_key = ("chatterbox", dev)
    started = time.perf_counter()
    if cache_key not in _CACHE:
        _CACHE[cache_key] = ChatterboxTTS.from_pretrained(device=dev)
    model = _CACHE[cache_key]
    wav = model.generate(text)
    audio = wav.squeeze().detach().cpu().numpy()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out_path), audio, int(model.sr))
    total_s = round(time.perf_counter() - started, 3)
    audio_s = _wav_duration(out_path)
    return {
        "ok": True, "engine": "chatterbox", "voice": voice or "default_calm", "sample_rate": int(model.sr),
        "wav_path": str(out_path), "bytes": out_path.stat().st_size,
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
            return _synth_kokoro_onnx(text, voice, speed, model_dir, out_path)
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
