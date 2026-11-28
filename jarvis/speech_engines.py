"""Unified Local Neural Speech & Voice Studio Engine (Jarvis 2.0).

Supports interchangeable local TTS engines with hardware-aware selection, graceful fallback,
independent Jarvis and TUKI voice identities, pronunciation dictionary, verified optional
model storage (outside the source repo), and authentic latency/RTF measurement.

License & Security Boundaries:
- kokoro_onnx (MIT / Apache-2.0 weights): ONNX Runtime inference (no unsafe pickle).
- kokoro (Apache-2.0): Optional PyTorch Kokoro-82M pipeline.
- qwen3_tts (Apache-2.0): Optional expressive voice-design synthesis (original prompts only;
  never clones copyrighted film recordings or unauthorized actors).
- chatterbox (MIT): Optional expressive PyTorch synthesis.
- piper (GPL-3.0): Invoked STRICTLY as an external optional CLI subprocess (never imported).
- windows_sapi: Built-in Windows SAPI5 system voices (Compatibility fallback).
- 100% local-only operation: speech text is never transmitted to external providers.
"""
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import wave
from pathlib import Path

from . import config, hardware, secure, voice_runtime


def _has_pkg(name: str) -> bool:
    if name in sys.modules:
        return True
    try:
        return importlib.util.find_spec(name) is not None
    except (ValueError, ImportError):
        return False

# ------------------------------------------------------------------ Engine Registry
ENGINES = {
    "kokoro_onnx": {
        "label": "Kokoro ONNX (Neural · CPU/GPU)",
        "repo": "https://github.com/thewh1teagle/kokoro-onnx",
        "code_license": "MIT",
        "model_license": "Apache-2.0",
        "format": "ONNX (safe, no pickle)",
        "supports_gpu": True,
        "supports_streaming": True,
        "supports_pitch": False,
        "python_note": "Requires onnxruntime (Python 3.11-3.13 wheels; cp315 wheel pending upstream).",
        "voices": {
            "jarvis": [
                {"id": "bm_george", "label": "George (British Male · Refined, Calm)"},
                {"id": "bm_daniel", "label": "Daniel (British Male · Measured, Crisp)"},
                {"id": "bm_fable", "label": "Fable (British Male · Expressive, Warm)"},
                {"id": "bm_lewis", "label": "Lewis (British Male · Deep, Formal)"},
            ],
            "tuki": [
                {"id": "bf_emma", "label": "Emma (British Female · Clear, Analytical)"},
                {"id": "bf_isabella", "label": "Isabella (British Female · Warm, Articulated)"},
                {"id": "af_bella", "label": "Bella (American Female · Crisp, Technical)"},
                {"id": "af_heart", "label": "Heart (American Female · Natural)"},
            ],
        },
    },
    "kokoro": {
        "label": "Kokoro PyTorch (Neural · GPU/CPU)",
        "repo": "https://github.com/hexgrad/kokoro",
        "code_license": "Apache-2.0",
        "model_license": "Apache-2.0",
        "format": "Safetensors / PyTorch",
        "supports_gpu": True,
        "supports_streaming": True,
        "supports_pitch": False,
        "python_note": "Optional PyTorch runtime (CUDA recommended for lowest latency).",
        "voices": {
            "jarvis": [
                {"id": "bm_george", "label": "George (British Male)"},
                {"id": "bm_daniel", "label": "Daniel (British Male)"},
                {"id": "bm_fable", "label": "Fable (British Male)"},
                {"id": "bm_lewis", "label": "Lewis (British Male)"},
            ],
            "tuki": [
                {"id": "bf_emma", "label": "Emma (British Female)"},
                {"id": "bf_isabella", "label": "Isabella (British Female)"},
            ],
        },
    },
    "qwen3_tts": {
        "label": "Qwen3-TTS (Expressive Voice Design · GPU)",
        "repo": "https://github.com/QwenLM/Qwen3-TTS",
        "code_license": "Apache-2.0",
        "model_license": "Apache-2.0",
        "format": "Safetensors / Transformers",
        "supports_gpu": True,
        "supports_streaming": True,
        "supports_pitch": False,
        "python_note": "Recommended on >=8 GB VRAM NVIDIA GPU with PyTorch CUDA.",
        "voices": {
            "jarvis": [
                {"id": "jarvis_british_butler", "label": "Original Jarvis Design (Refined British, Calm, Subtle Dry Wit)"},
            ],
            "tuki": [
                {"id": "tuki_technical_analyst", "label": "Original TUKI Design (Crisp, Analytical, Measured)"},
            ],
        },
    },
    "chatterbox": {
        "label": "Chatterbox (Optional Expressive TTS · GPU)",
        "repo": "https://github.com/resemble-ai/chatterbox",
        "code_license": "MIT",
        "model_license": "MIT",
        "format": "Safetensors / PyTorch",
        "supports_gpu": True,
        "supports_streaming": False,
        "supports_pitch": False,
        "python_note": "Optional PyTorch runtime; requires compatible torch build.",
        "voices": {
            "jarvis": [{"id": "default_calm", "label": "Calm Assistant (Original)"}],
            "tuki": [{"id": "default_crisp", "label": "Crisp Analyst (Original)"}],
        },
    },
    "piper": {
        "label": "Piper Neural CLI (External Subprocess · CPU)",
        "repo": "https://github.com/OHF-Voice/piper1-gpl",
        "code_license": "GPL-3.0 (external CLI subprocess only)",
        "model_license": "MIT / CC-BY (varies by voice pack)",
        "format": "ONNX via external piper executable",
        "supports_gpu": False,
        "supports_streaming": True,
        "supports_pitch": False,
        "python_note": "Invoked strictly out-of-process to preserve Apache-2.0 / GPL-3.0 boundary.",
        "voices": {
            "jarvis": [
                {"id": "en_GB-alan-medium", "label": "Alan (en_GB · Medium)"},
                {"id": "en_GB-northern_english_male-medium", "label": "Northern English Male (en_GB)"},
            ],
            "tuki": [
                {"id": "en_GB-jenny_dioco-medium", "label": "Jenny (en_GB · Medium)"},
                {"id": "en_US-amy-medium", "label": "Amy (en_US · Medium)"},
            ],
        },
    },
    "windows_sapi": {
        "label": "Windows System Voices (SAPI5 · Built-In)",
        "repo": "Built-in Windows SAPI5 (pyttsx3 MIT wrapper)",
        "code_license": "MIT (pyttsx3)",
        "model_license": "OS built-in",
        "format": "Windows SAPI5 COM",
        "supports_gpu": False,
        "supports_streaming": False,
        "supports_pitch": False,
        "python_note": "Always available on Windows 10/11 with zero model downloads.",
        "voices": {
            "jarvis": [{"id": "auto_british", "label": "Automatic (Prefer Installed British SAPI Voice)"}],
            "tuki": [{"id": "auto_distinct", "label": "Automatic (Distinct Installed SAPI Voice)"}],
        },
    },
}

# Original non-infringing expressive voice design prompts (never clones copyrighted actors)
ORIGINAL_VOICE_DESIGNS = {
    "jarvis": (
        "An original refined British male personal assistant: calm, controlled, articulate RP pronunciation, "
        "natural conversational pauses, confident yet understated tone, subtle dry humour, minimal robotic cadence."
    ),
    "tuki": (
        "An original crisp, clear analytical assistant voice: distinct from Jarvis, measured cadence, "
        "precise technical articulation, calm and objective tone for mathematics, research, and code review."
    ),
}

# ------------------------------------------------------------------ 4 Performance Profiles
VOICE_PERFORMANCE_PROFILES = {
    "cinematic": {
        "label": "Cinematic (Expressive Neural Quality)",
        "description": "Prioritizes expressive, high-quality neural speech (Qwen3-TTS / Kokoro GPU) with fallback.",
        "engine_order": ["qwen3_tts", "kokoro_onnx", "kokoro", "chatterbox", "piper", "windows_sapi"],
        "device": "gpu",
        "sample_rate": 24000,
    },
    "balanced": {
        "label": "Balanced (Natural Speech & Low Latency)",
        "description": "Prioritizes fast natural neural speech (Kokoro ONNX / Piper) with low time-to-first-audio.",
        "engine_order": ["kokoro_onnx", "piper", "kokoro", "windows_sapi"],
        "device": "auto",
        "sample_rate": 24000,
    },
    "performance": {
        "label": "Performance (Low Resource Footprint)",
        "description": "Minimizes RAM/CPU/VRAM usage on 8 GB or battery-powered computers.",
        "engine_order": ["piper", "kokoro_onnx", "windows_sapi"],
        "device": "cpu",
        "sample_rate": 22050,
    },
    "compatibility": {
        "label": "Compatibility (System Speech Only)",
        "description": "Uses built-in Windows SAPI5 voices directly with zero neural model downloads.",
        "engine_order": ["windows_sapi"],
        "device": "cpu",
        "sample_rate": 22050,
    },
}

# ------------------------------------------------------------------ Optional Verified Voice Packs
VOICE_PACKS = [
    {
        "id": "kokoro-v1.0-onnx-int8",
        "engine": "kokoro_onnx",
        "label": "Kokoro-82M ONNX (Quantized int8 · British George/Daniel/Fable/Lewis + TUKI Emma)",
        "estimated_mb": 92,
        "license": "Apache-2.0",
        "source_url": "https://github.com/thewh1teagle/kokoro-onnx/releases",
        "files": ["kokoro-v1.0.int8.onnx", "voices-v1.0.bin"],
    },
    {
        "id": "kokoro-v1.0-onnx-fp32",
        "engine": "kokoro_onnx",
        "label": "Kokoro-82M ONNX (Full FP32 · Highest ONNX Quality)",
        "estimated_mb": 325,
        "license": "Apache-2.0",
        "source_url": "https://github.com/thewh1teagle/kokoro-onnx/releases",
        "files": ["kokoro-v1.0.onnx", "voices-v1.0.bin"],
    },
    {
        "id": "piper-en-gb-alan-medium",
        "engine": "piper",
        "label": "Piper British Male (en_GB-alan-medium · External CLI)",
        "estimated_mb": 63,
        "license": "MIT",
        "source_url": "https://huggingface.co/rhasspy/piper-voices",
        "files": ["en_GB-alan-medium.onnx", "en_GB-alan-medium.onnx.json"],
    },
    {
        "id": "qwen3-tts-voice-design",
        "engine": "qwen3_tts",
        "label": "Qwen3-TTS 1.7B VoiceDesign (Expressive GPU Synthesis)",
        "estimated_mb": 3400,
        "license": "Apache-2.0",
        "source_url": "https://github.com/QwenLM/Qwen3-TTS",
        "files": ["model.safetensors", "config.json"],
    },
]

# ------------------------------------------------------------------ Pronunciation Dictionary
DEFAULT_PRONUNCIATIONS = {
    "TUKI": "Too-key",
    "J.A.R.V.I.S.": "Jarvis",
    "SQLite": "Sequel-light",
    "ONNX": "On-ix",
    "VRAM": "V-RAM",
    "JSONL": "J-SON lines",
    "OAuth": "Oh-Auth",
    "DPAPI": "D-P-A-P-I",
}


def apply_pronunciation(text: str, custom_map: dict | None = None) -> str:
    """Apply default + user-configured pronunciation substitutions deterministically."""
    merged = dict(DEFAULT_PRONUNCIATIONS)
    if isinstance(custom_map, dict):
        for k, v in custom_map.items():
            ks, vs = str(k or "").strip()[:60], str(v or "").strip()[:80]
            if ks and vs:
                merged[ks] = vs
    out = str(text or "")
    # Replace longest keys first to avoid partial collisions
    for term in sorted(merged, key=len, reverse=True):
        pattern = re.compile(r"(?<!\w)" + re.escape(term) + r"(?!\w)")
        out = pattern.sub(merged[term], out)
    return out


# ------------------------------------------------------------------ Model Storage & Integrity
def model_storage_dir() -> Path:
    """Store optional voice models strictly outside the source repository."""
    d = config.APP_DIR / "voice-models"
    d.mkdir(parents=True, exist_ok=True)
    return d


def verify_file_sha256(path: str | Path, expected_hex: str) -> bool:
    """Verify downloaded model file integrity against a trusted SHA-256 hex digest."""
    expected = str(expected_hex or "").strip().lower()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("Expected a 64-character lowercase SHA-256 hex digest.")
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest() == expected


def storage_summary() -> dict:
    root = model_storage_dir()
    packs = []
    total_bytes = 0
    for pack in VOICE_PACKS:
        pdir = root / pack["id"]
        installed_files = []
        pack_bytes = 0
        if pdir.is_dir():
            for fname in pack["files"]:
                fp = pdir / fname
                if fp.is_file():
                    installed_files.append(fname)
                    pack_bytes += fp.stat().st_size
        total_bytes += pack_bytes
        packs.append({
            **pack,
            "installed": len(installed_files) == len(pack["files"]),
            "installed_files": installed_files,
            "disk_mb": round(pack_bytes / (1024 * 1024), 2),
        })
    return {
        "storage_dir": str(root),
        "total_mb": round(total_bytes / (1024 * 1024), 2),
        "packs": packs,
    }


def delete_voice_pack(pack_id: str) -> dict:
    valid_ids = {p["id"] for p in VOICE_PACKS}
    if pack_id not in valid_ids:
        raise ValueError(f"Unknown voice pack '{pack_id}'.")
    target = (model_storage_dir() / pack_id).resolve()
    if target.parent != model_storage_dir().resolve():
        raise ValueError("Invalid voice pack path.")
    if target.is_dir():
        shutil.rmtree(target)
        secure.audit("voice_pack_deleted", {"pack_id": pack_id})
    return storage_summary()


# ------------------------------------------------------------------ Availability & Selection
def engine_availability(cfg: dict | None = None) -> dict[str, dict]:
    cfg = cfg or {}
    root = model_storage_dir()
    rt_health = voice_runtime.CLIENT.health()
    rt_pkgs = rt_health.get("packages") or {}

    kokoro_onnx_pkg = (
        (_has_pkg("kokoro_onnx") and _has_pkg("onnxruntime"))
        or (bool(rt_pkgs.get("kokoro_onnx")) and bool(rt_pkgs.get("onnxruntime")))
    )
    kokoro_onnx_model = any(
        (root / pid / f).is_file() and (root / pid / "voices-v1.0.bin").is_file()
        for pid, f in (("kokoro-v1.0-onnx-int8", "kokoro-v1.0.int8.onnx"), ("kokoro-v1.0-onnx-fp32", "kokoro-v1.0.onnx"))
    )
    kokoro_pt_pkg = _has_pkg("kokoro") or bool(rt_pkgs.get("kokoro"))
    qwen_pkg = _has_pkg("qwen_tts") or bool(rt_pkgs.get("qwen_tts"))
    qwen_model = (root / "qwen3-tts-voice-design" / "config.json").is_file()
    chatterbox_pkg = _has_pkg("chatterbox") or bool(rt_pkgs.get("chatterbox"))
    piper_exe = shutil.which(str(cfg.get("piper_exe") or "piper")) is not None
    piper_model = bool(cfg.get("piper_model") and Path(cfg["piper_model"]).is_file())
    sapi_ok = os.name == "nt" and _has_pkg("pyttsx3")

    return {
        "kokoro_onnx": {
            "package_installed": kokoro_onnx_pkg,
            "model_installed": kokoro_onnx_model,
            "ready": kokoro_onnx_pkg and kokoro_onnx_model,
            "reason": "Ready (Python 3.12 neural runtime + Kokoro ONNX pack)" if (kokoro_onnx_pkg and kokoro_onnx_model) else (
                "Download Kokoro ONNX voice pack in Voice Studio." if kokoro_onnx_pkg
                else "Install isolated Python 3.12 neural runtime and Kokoro ONNX pack in Voice Studio."
            ),
        },
        "kokoro": {
            "package_installed": kokoro_pt_pkg,
            "model_installed": False,
            "ready": False,
            "reason": "Optional PyTorch kokoro package & local weights required.",
        },
        "qwen3_tts": {
            "package_installed": qwen_pkg,
            "model_installed": qwen_model,
            "ready": qwen_pkg and qwen_model,
            "reason": "Ready (Qwen3-TTS VoiceDesign)" if (qwen_pkg and qwen_model) else "Optional qwen-tts + local GPU weights not installed.",
        },
        "chatterbox": {
            "package_installed": chatterbox_pkg,
            "model_installed": False,
            "ready": False,
            "reason": "Optional chatterbox-tts package & local weights required.",
        },
        "piper": {
            "package_installed": piper_exe,
            "model_installed": piper_model,
            "ready": piper_exe and piper_model,
            "reason": "Ready" if (piper_exe and piper_model) else "Optional external Piper CLI executable or .onnx voice not configured.",
        },
        "windows_sapi": {
            "package_installed": sapi_ok,
            "model_installed": sapi_ok,
            "ready": sapi_ok,
            "reason": "Ready (Windows SAPI5)" if sapi_ok else "Windows SAPI5 unavailable on this OS.",
        },
    }


def recommend_voice_profile(hw: dict | None = None) -> dict:
    """Recommend a Voice Studio performance profile based on real detected hardware."""
    info = hw if hw is not None else hardware.summary()
    ram = (info.get("memory") or {}).get("total_gb") or 0.0
    gpus = info.get("gpus") or []
    vram = max((g.get("vram_total_gb") or 0.0 for g in gpus), default=0.0)
    if vram >= 8.0 and ram >= 16.0:
        return {
            "profile": "cinematic",
            "device": "gpu",
            "reason": f"Detected {vram:.1f} GB GPU VRAM and {ram:.1f} GB RAM; capable of Cinematic neural speech.",
        }
    if ram >= 12.0:
        return {
            "profile": "balanced",
            "device": "cpu",
            "reason": f"Detected {ram:.1f} GB RAM without >=8 GB dedicated GPU; Balanced ONNX/Piper recommended.",
        }
    return {
        "profile": "performance",
        "device": "cpu",
        "reason": "Low-memory system detected; Performance or Compatibility profile keeps memory usage minimal.",
    }


def resolve_engine(cfg: dict, assistant: str = "jarvis") -> dict:
    """Resolve the active TTS engine for Jarvis or TUKI with graceful fallback."""
    who = "tuki" if assistant == "tuki" else "jarvis"
    profile_key = str(cfg.get("voice_performance_profile") or "balanced").strip().lower()
    if profile_key not in VOICE_PERFORMANCE_PROFILES:
        profile_key = "balanced"
    profile = VOICE_PERFORMANCE_PROFILES[profile_key]
    override_key = "tuki_speech_engine" if who == "tuki" else "jarvis_speech_engine"
    preferred = str(cfg.get(override_key) or "auto").strip().lower()
    legacy_choice = str(cfg.get("tuki_voice_choice" if who == "tuki" else "voice_choice") or "auto").strip().lower()
    explicit_sapi = str(cfg.get("tuki_sapi_voice_contains" if who == "tuki" else "sapi_voice_contains") or "").strip()
    if preferred == "auto" and (legacy_choice == "windows" or explicit_sapi):
        preferred = "windows_sapi"
    elif preferred == "auto" and legacy_choice == "piper":
        preferred = "piper"
    avail = engine_availability(cfg)

    chain = [preferred] + [e for e in profile["engine_order"] if e != preferred] if preferred in ENGINES else list(profile["engine_order"])
    if "windows_sapi" not in chain:
        chain.append("windows_sapi")

    for idx, eng in enumerate(chain):
        if avail.get(eng, {}).get("ready"):
            return {
                "assistant": who,
                "profile": profile_key,
                "requested": preferred,
                "selected": eng,
                "fallback_used": (preferred in ENGINES and eng != preferred) or (preferred == "auto" and idx > 0),
                "fallback_reason": "" if eng == preferred else (avail.get(preferred, {}).get("reason", "") if preferred in ENGINES else ""),
                "device": str(cfg.get("voice_compute_device") or profile["device"]),
            }
    return {
        "assistant": who,
        "profile": profile_key,
        "requested": preferred,
        "selected": "none",
        "fallback_used": True,
        "fallback_reason": "No local TTS engine is available on this host.",
        "device": "cpu",
    }


# ------------------------------------------------------------------ Synthesis & Benchmarking
def _wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate() or 1
        return round(frames / float(rate), 3)


def _synthesize_sapi(cfg: dict, spoken: str, who: str, dest: Path) -> tuple[str, float]:
    import pyttsx3
    from . import voice as voice_mod
    started = time.perf_counter()
    engine = pyttsx3.init()
    voices = engine.getProperty("voices")
    picked, _ = voice_mod.assistant_voice(voices, cfg, who)
    voice_used = ""
    if picked is not None:
        engine.setProperty("voice", picked.id)
        voice_used = picked.name
    rate = int(cfg.get("tuki_speech_rate" if who == "tuki" else "speech_rate", 200 if who == "tuki" else 185))
    engine.setProperty("rate", max(100, min(320, rate)))
    engine.save_to_file(spoken, str(dest))
    engine.runAndWait()
    engine.stop()
    return voice_used, round(time.perf_counter() - started, 3)


def synthesize_to_wav(
    cfg: dict,
    text: str,
    *,
    assistant: str = "jarvis",
    out_path: str | Path | None = None,
    voice_override: str | None = None,
    engine_override: str | None = None,
    allow_fallback: bool = True,
) -> dict:
    """Synthesize speech locally to a WAV file via the unified engine resolver and return authentic metrics."""
    who = "tuki" if assistant == "tuki" else "jarvis"
    spoken = apply_pronunciation(str(text or "").strip(), cfg.get("voice_pronunciations"))
    if not spoken:
        raise ValueError("Provide text to synthesize.")
    resolved = resolve_engine(cfg, who)
    eng = engine_override or resolved["selected"]
    if eng == "none":
        raise RuntimeError(resolved["fallback_reason"])

    dest = Path(out_path) if out_path else Path(tempfile.mkstemp(prefix=f"jarvis_{who}_", suffix=".wav")[1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    fallback_used = bool(resolved["fallback_used"])
    fallback_reason = str(resolved.get("fallback_reason") or "")

    if eng in ("kokoro_onnx", "kokoro", "qwen3_tts", "chatterbox"):
        voice_id = voice_override or str(
            cfg.get("tuki_neural_voice" if who == "tuki" else "jarvis_neural_voice")
            or ("bf_emma" if who == "tuki" else "bm_george")
        )
        rate_wpm = int(cfg.get("tuki_speech_rate" if who == "tuki" else "speech_rate", 200 if who == "tuki" else 185))
        speed = round(max(0.6, min(1.8, rate_wpm / 185.0)), 2)
        try:
            res = voice_runtime.CLIENT.request({
                "cmd": "synthesize",
                "engine": eng,
                "voice": voice_id,
                "text": spoken,
                "speed": speed,
                "device": resolved["device"],
                "instruct": ORIGINAL_VOICE_DESIGNS[who],
                "model_dir": str(model_storage_dir()),
                "out_path": str(dest),
            }, timeout=90.0)
            return {
                "ok": True,
                "assistant": who,
                "engine": res["engine"],
                "model_file": res.get("model_file", ""),
                "actual_provider": res.get("actual_provider", ""),
                "voice": res["voice"],
                "fallback_used": fallback_used,
                "fallback_reason": fallback_reason,
                "spoken_text": spoken,
                "wav_path": str(dest),
                "bytes": res["bytes"],
                "ttfa_seconds": res.get("ttfa_seconds"),
                "total_seconds": res["total_seconds"],
                "audio_seconds": res["audio_seconds"],
                "rtf": res["rtf"],
            }
        except Exception as exc:
            if not allow_fallback or os.name != "nt":
                raise
            fallback_used = True
            fallback_reason = f"{eng} failed ({exc}); fell back to windows_sapi."
            secure.audit("voice_engine_fallback", {"from": eng, "to": "windows_sapi", "reason": str(exc)[:160]})
            eng = "windows_sapi"

    if eng == "windows_sapi":
        voice_used, total_s = _synthesize_sapi(cfg, spoken, who, dest)
    elif eng == "piper":
        started = time.perf_counter()
        model = str(cfg.get("tuki_piper_model" if who == "tuki" else "piper_model") or "")
        exe = str(cfg.get("piper_exe") or "piper")
        subprocess.run(
            [exe, "--model", model, "--output_file", str(dest)],
            input=spoken, text=True, check=True, timeout=30,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        voice_used = Path(model).stem
        total_s = round(time.perf_counter() - started, 3)
    else:
        raise RuntimeError(f"Unsupported speech engine '{eng}'.")

    duration_s = _wav_duration_seconds(dest) if dest.is_file() and dest.stat().st_size > 44 else 0.0
    if duration_s <= 0:
        raise RuntimeError(f"{eng} produced no audio frames.")
    rtf = round(total_s / duration_s, 3) if duration_s > 0 else None
    return {
        "ok": True,
        "assistant": who,
        "engine": eng,
        "actual_provider": "WindowsSAPI5" if eng == "windows_sapi" else "ExternalPiperCLI",
        "voice": voice_used,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "spoken_text": spoken,
        "wav_path": str(dest),
        "bytes": dest.stat().st_size if dest.is_file() else 0,
        "ttfa_seconds": total_s,
        "total_seconds": total_s,
        "audio_seconds": duration_s,
        "rtf": rtf,
    }


def synthesize_stream(
    cfg: dict,
    text: str,
    *,
    assistant: str = "jarvis",
    out_dir: str | Path | None = None,
    voice_override: str | None = None,
    on_chunk=None,
    timeout: float = 90.0,
) -> dict:
    """Incrementally synthesize Kokoro ONNX sentence-by-sentence, invoking on_chunk as each WAV is ready."""
    who = "tuki" if assistant == "tuki" else "jarvis"
    spoken = apply_pronunciation(str(text or "").strip(), cfg.get("voice_pronunciations"))
    if not spoken:
        raise ValueError("Provide text to synthesize.")
    resolved = resolve_engine(cfg, who)
    voice_id = voice_override or str(
        cfg.get("tuki_neural_voice" if who == "tuki" else "jarvis_neural_voice")
        or ("bf_emma" if who == "tuki" else "bm_george")
    )
    rate_wpm = int(cfg.get("tuki_speech_rate" if who == "tuki" else "speech_rate", 200 if who == "tuki" else 185))
    speed = round(max(0.6, min(1.8, rate_wpm / 185.0)), 2)
    target_dir = Path(out_dir) if out_dir else Path(tempfile.mkdtemp(prefix=f"jarvis_stream_{who}_"))
    target_dir.mkdir(parents=True, exist_ok=True)
    res = voice_runtime.CLIENT.request({
        "cmd": "synthesize_stream",
        "voice": voice_id,
        "text": spoken,
        "speed": speed,
        "device": resolved["device"],
        "model_dir": str(model_storage_dir()),
        "out_dir": str(target_dir),
    }, timeout=timeout, on_chunk=on_chunk)
    return {
        "ok": True,
        "assistant": who,
        "engine": res.get("engine", "kokoro_onnx"),
        "model_file": res.get("model_file", ""),
        "actual_provider": res.get("actual_provider", ""),
        "voice": res.get("voice", voice_id),
        "spoken_text": spoken,
        "chunks": res.get("chunks", 0),
        "wav_paths": res.get("wav_paths", []),
        "ttfa_seconds": res.get("ttfa_seconds"),
        "total_seconds": res.get("total_seconds"),
        "audio_seconds": res.get("audio_seconds"),
        "rtf": res.get("rtf"),
    }


def studio_state(cfg: dict) -> dict:
    """Return full Voice Studio state for the HUD."""
    from . import voice as voice_mod
    hw = hardware.summary()
    avail = engine_availability(cfg)
    return {
        "profile": cfg.get("voice_performance_profile", "balanced"),
        "profiles": VOICE_PERFORMANCE_PROFILES,
        "recommended_profile": recommend_voice_profile(hw),
        "compute_device": cfg.get("voice_compute_device", "auto"),
        "jarvis": {
            "engine": cfg.get("jarvis_speech_engine", "auto"),
            "resolved": resolve_engine(cfg, "jarvis"),
            "voice": cfg.get("jarvis_neural_voice", "bm_george"),
            "sapi_voice": cfg.get("sapi_voice_contains", ""),
            "rate": int(cfg.get("speech_rate", 185)),
            "pitch": float(cfg.get("jarvis_voice_pitch", 1.0)),
            "design_prompt": ORIGINAL_VOICE_DESIGNS["jarvis"],
        },
        "tuki": {
            "engine": cfg.get("tuki_speech_engine", "auto"),
            "resolved": resolve_engine(cfg, "tuki"),
            "voice": cfg.get("tuki_neural_voice", "bf_emma"),
            "sapi_voice": cfg.get("tuki_sapi_voice_contains", ""),
            "rate": int(cfg.get("tuki_speech_rate", 200)),
            "pitch": float(cfg.get("tuki_voice_pitch", 1.05)),
            "design_prompt": ORIGINAL_VOICE_DESIGNS["tuki"],
        },
        "engines": {
            eid: {
                "label": spec["label"],
                "repo": spec["repo"],
                "code_license": spec["code_license"],
                "model_license": spec["model_license"],
                "format": spec["format"],
                "supports_gpu": spec["supports_gpu"],
                "supports_streaming": spec["supports_streaming"],
                "python_note": spec["python_note"],
                "voices": spec["voices"],
                **avail[eid],
            }
            for eid, spec in ENGINES.items()
        },
        "pronunciations": {**DEFAULT_PRONUNCIATIONS, **(cfg.get("voice_pronunciations") or {})},
        "storage": storage_summary(),
        "runtime": voice_runtime.CLIENT.health(),
        "installed_sapi_voices": voice_mod.installed_voice_names(),
        "audio_devices": voice_mod.audio_devices(),
    }
