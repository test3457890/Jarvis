# Jarvis 2.0 — Advanced Neural Speech & Voice Studio Architecture

**Branch:** `feature/jarvis-neural-voice` (branched from verified RC1 commit `d86ae963e5170d249bd14871b2171bfd4b179f92`)  
**Scope:** Isolated Python 3.12 neural speech runtime, real Kokoro-82M ONNX / Kokoro PyTorch / Qwen3-TTS / Chatterbox inference adapters, unified `Speaker._worker()` live integration, verified official model pack downloader, Voice Studio HUD, and authentic 8-voice neural benchmarks.

---

## 1. Isolated Python 3.12 Neural Runtime Architecture (Phase A)

Jarvis's primary `.venv` (Python 3.15.2) remains untouched. Optional neural speech dependencies are provisioned automatically into `%APPDATA%\Jarvis\voice-runtime\venv` (Python 3.12.16) via `jarvis/voice_runtime.py` (`uv`) with pinned packages (`kokoro-onnx==0.4.7`, `onnxruntime==1.20.1`, `soundfile==0.13.1`, `numpy==2.2.3`).

Jarvis communicates with `jarvis/voice_worker.py` strictly over **local stdin/stdout JSON lines** (zero network sockets, persistent resident models across requests, instant subprocess kill on barge-in cancellation).

---

## 2. Reference Repository License & Security Audit

| Repository | Code License | Model License | Serialization / Security | Integration Approach |
|---|---|---|---|---|
| [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | **MIT** | Apache-2.0 (Kokoro-82M) | **ONNX Runtime (safe, zero pickle)** | **Live & Verified** (`kokoro_onnx`) via Python 3.12 stdio worker; 4 British Jarvis voices + 4 TUKI voices |
| [hexgrad/kokoro](https://github.com/hexgrad/kokoro) | **Apache-2.0** | Apache-2.0 | Safetensors / PyTorch | Implemented adapter (`kokoro`) in `voice_worker.py` (optional PyTorch) |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | **Apache-2.0** | Apache-2.0 | Safetensors / Transformers | Implemented adapter (`qwen3_tts`) in `voice_worker.py` (optional >=8 GB VRAM GPU + local weights; original non-infringing prompts only) |
| [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) | **MIT** | MIT | Safetensors / PyTorch | Implemented adapter (`chatterbox`) in `voice_worker.py` (optional PyTorch) |
| [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) | **GPL-3.0** | MIT / CC-BY | ONNX via external CLI | **Strict GPL-3.0 boundary**: external CLI subprocess only (never imported) |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | **MIT** | MIT / Apache-2.0 | CTranslate2 (safe) | Local STT (`HF_HUB_OFFLINE=1`) |

---

## 3. Authentic Windows 10 Neural Benchmarks & 8 WAV Comparison Samples

Measured live via `python -m scripts.benchmark_voice` on Windows 10 (host: 31.86 GB RAM, NVIDIA Quadro RTX 5000 16.0 GB VRAM; isolated worker: Python 3.12.16, `kokoro-onnx==0.4.7`, `onnxruntime==1.20.1` `CPUExecutionProvider`). Raw JSON: [voice-benchmark-windows.json](measurements/voice-benchmark-windows.json).

### A. Real Kokoro-82M ONNX Neural Synthesis (24 kHz PCM WAV)

| Assistant | Kokoro Voice | Cold Time | Warm Time | TTFA | Audio Duration | RTF | Authentic Neural WAV Sample |
|---|---|---:|---:|---:|---:|---:|---|
| **Jarvis** | `bm_george` (British Male · Refined) | `16.892s` | `15.303s` | `15.298s` | `9.024s` | `1.696` | `docs/measurements/voice-samples/kokoro_jarvis_george.wav` (433 KB) |
| **Jarvis** | `bm_daniel` (British Male · Crisp) | — | `13.299s` | `13.292s` | `7.509s` | `1.771` | `docs/measurements/voice-samples/kokoro_jarvis_daniel.wav` (360 KB) |
| **Jarvis** | `bm_fable` (British Male · Warm) | — | `13.262s` | `13.257s` | `7.915s` | `1.676` | `docs/measurements/voice-samples/kokoro_jarvis_fable.wav` (380 KB) |
| **Jarvis** | `bm_lewis` (British Male · Formal) | — | `18.481s` | `18.474s` | `8.597s` | `2.150` | `docs/measurements/voice-samples/kokoro_jarvis_lewis.wav` (413 KB) |
| **TUKI** | `bf_emma` (British Female · Analytical) | — | `15.540s` | `15.535s` | `8.533s` | `1.821` | `docs/measurements/voice-samples/kokoro_tuki_emma.wav` (410 KB) |
| **TUKI** | `bf_isabella` (British Female · Warm) | — | `15.953s` | `15.948s` | `8.789s` | `1.815` | `docs/measurements/voice-samples/kokoro_tuki_isabella.wav` (422 KB) |
| **TUKI** | `af_bella` (Technical Crisp) | — | `17.139s` | `17.133s` | `9.941s` | `1.724` | `docs/measurements/voice-samples/kokoro_tuki_bella.wav` (477 KB) |
| **TUKI** | `af_heart` (Natural) | — | `15.238s` | `15.233s` | `9.536s` | `1.598` | `docs/measurements/voice-samples/kokoro_tuki_heart.wav` (458 KB) |

### B. Windows SAPI5 Compatibility Baseline (Clearly Separated — Never Substituted for Neural)

| Assistant | Engine | Voice Used | Cold Time | Warm Time | Audio Duration | RTF | Baseline WAV Sample |
|---|---|---|---:|---:|---:|---:|---|
| **Jarvis** | `windows_sapi` | `Microsoft David Desktop` (185 WPM) | `0.328s` | `0.126s` | `8.973s` | `0.014` | `docs/measurements/voice-samples/jarvis_sapi_baseline.wav` (395 KB) |
| **TUKI** | `windows_sapi` | `Microsoft Zira Desktop` (200 WPM) | `0.148s` | `0.153s` | `8.063s` | `0.019` | `docs/measurements/voice-samples/tuki_sapi_baseline.wav` (355 KB) |

- **EchoGuard Spoken Barge-In Detection Latency:** `0.0039 ms`.
- **Hardware Notes:** Kokoro ONNX ran on `CPUExecutionProvider` (`RTF 1.60–2.15` for ~8–10s sentences); installing `onnxruntime-gpu` (CUDA) in the isolated Python 3.12 runtime accelerates synthesis significantly on the Quadro RTX 5000. Qwen3-TTS (`3.4 GB` weights) and Chatterbox adapters are implemented in `voice_worker.py` and remain optional downloads (not pre-downloaded in CI/repo). Ollama concurrent benchmarking requires installing Ollama on the host.
