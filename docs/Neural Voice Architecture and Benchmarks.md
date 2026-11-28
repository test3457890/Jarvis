# Jarvis 2.0 — Advanced Neural Speech & Voice Studio Architecture

**Branch:** `feature/jarvis-neural-voice` (branched from verified RC1 commit `d86ae963e5170d249bd14871b2171bfd4b179f92`)  
**Scope:** Unified local multi-engine TTS architecture, Voice Studio workspace, independent Jarvis & TUKI voice identities, 4 hardware-aware performance profiles, pronunciation dictionary, verified optional model packs, and authentic Windows 10 benchmarks.

---

## 1. Reference Repository License & Compatibility Audit

All six reference repositories were audited directly via GitHub API and Python 3.15.2 wheel inspection on Windows 10:

| Repository | Code License | Model License | Serialization / Security | Windows / Python Compatibility | Integration Approach |
|---|---|---|---|---|---|
| [hexgrad/kokoro](https://github.com/hexgrad/kokoro) | **Apache-2.0** | Apache-2.0 (Kokoro-82M) | Safetensors / PyTorch | Python 3.11–3.13 (optional PyTorch) | Optional adapter (`kokoro`) |
| [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | **MIT** | Apache-2.0 (Kokoro-82M) | **ONNX Runtime (safe, zero pickle)** | Python 3.11–3.13 (`onnxruntime` cp315 wheel pending upstream) | Primary neural adapter (`kokoro_onnx`) with British Jarvis (`bm_george`, `bm_daniel`, `bm_fable`, `bm_lewis`) & TUKI (`bf_emma`, `bf_isabella`, `af_bella`, `af_heart`) |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | **Apache-2.0** | Apache-2.0 | Safetensors / Transformers | Recommended >=8 GB NVIDIA VRAM (PyTorch CUDA) | Optional Cinematic VoiceDesign adapter (`qwen3_tts`) using original non-infringing assistant prompts (never clones copyrighted film recordings) |
| [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) | **MIT** | MIT | Safetensors / PyTorch | Optional PyTorch GPU/CPU | Optional expressive adapter (`chatterbox`) |
| [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) | **GPL-3.0** | MIT / CC-BY (per voice) | ONNX via external CLI | Windows/Linux/macOS binary | **Strict GPL-3.0 boundary**: invoked ONLY as an optional external CLI subprocess (`piper`), never imported/linked into Apache-2.0 Jarvis |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | **MIT** | MIT / Apache-2.0 | CTranslate2 (safe) | Python 3.11–3.13 (CTranslate2 cp315 wheel pending) | Existing local STT engine (`jarvis/voice.py`, `HF_HUB_OFFLINE=1`) |

---

## 2. Unified Speech Architecture & Performance Profiles

Implemented in `jarvis/speech_engines.py`, wired into `jarvis/voice.py` (`Speaker.say()` applies pronunciation dictionary), `jarvis/__main__.py` (`voice_studio_operation`, `EchoGuard`, `stream_sentences()`), `jarvis/webui.py` (`/api/voice-studio`), and `jarvis/ui.html` (dedicated **Voice Studio** workspace tab):

- **4 Selectable Performance Profiles:**
  - `cinematic`: `qwen3_tts` -> `kokoro_onnx` -> `kokoro` -> `chatterbox` -> `piper` -> `windows_sapi` (GPU preferred, 24 kHz)
  - `balanced`: `kokoro_onnx` -> `piper` -> `kokoro` -> `windows_sapi` (low latency)
  - `performance`: `piper` -> `kokoro_onnx` -> `windows_sapi` (CPU / low RAM)
  - `compatibility`: `windows_sapi` directly (zero downloads)
- **Independent Jarvis & TUKI Identities:** Separate engine, voice, WPM rate, pitch multiplier, and pronunciation dictionary settings.
- **Model Storage & Integrity:** Optional packs are stored strictly outside the source repo in `%APPDATA%\Jarvis\voice-models\`, display estimated download sizes (MB) before download, and support `verify_file_sha256()`.
- **Security Guarantees:** 100% local-only operation (zero cloud speech transmission), no actor/film cloning, `can_authorize_sensitive_action() == False` (voice is never authentication), and Lockdown blocks Voice Studio mutations.

---

## 3. Authentic Windows 10 Benchmarks & WAV Samples

Measured live via `python -m scripts.benchmark_voice` on Windows 10 (Python 3.15.2, 31.86 GB RAM, NVIDIA Quadro RTX 5000 16.0 GB VRAM). Raw JSON saved in [voice-benchmark-windows.json](measurements/voice-benchmark-windows.json).

| Assistant | Active Engine (Fallback) | Voice Used | Cold Time | Warm Time | Audio Duration | Cold RTF | Warm RTF | Authentic WAV Sample |
|---|---|---|---:|---:|---:|---:|---:|---|
| **Jarvis** | `windows_sapi` (graceful fallback) | `Microsoft David Desktop` (185 WPM) | `0.648s` | `0.132s` | `8.973s` | `0.072` | `0.015` | `docs/measurements/voice-samples/jarvis_sample.wav` (395 KB) |
| **TUKI** | `windows_sapi` (graceful fallback) | `Microsoft Zira Desktop` (200 WPM) | `0.238s` | `0.180s` | `8.063s` | `0.030` | `0.022` | `docs/measurements/voice-samples/tuki_sample.wav` (355 KB) |

- **EchoGuard Spoken Barge-In Detection Latency:** `0.0052 ms` average per check.
- **Neural Engines (`kokoro_onnx`, `kokoro`, `qwen3_tts`, `chatterbox`, `piper`):** Not benchmarked on this host because Python 3.15.2 does not yet have prebuilt `onnxruntime`/`torch` wheels and optional model packs are not downloaded by default. Use a Python 3.12 or 3.13 virtual environment (`pip install kokoro-onnx onnxruntime` + Kokoro ONNX pack) to run live Kokoro / Qwen3-TTS GPU benchmarks without changing Jarvis code.
