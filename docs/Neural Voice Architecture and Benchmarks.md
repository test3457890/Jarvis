# Jarvis 2.0 — Advanced Neural Speech & Voice Studio Architecture

**Branch:** `feature/jarvis-neural-voice` (branched from verified RC1 commit `d86ae963e5170d249bd14871b2171bfd4b179f92`)  
**Scope:** Isolated Python 3.12 CUDA-accelerated neural speech runtime, real Kokoro-82M ONNX (FP32 CUDA + CPU) / Kokoro PyTorch / Qwen3-TTS / Chatterbox adapters, genuine incremental chunked streaming playback in `Speaker._worker()`, non-blocking active cancellation & enforced timeouts, pre-load trusted SHA-256 verification & redirect-validated downloader, Voice Studio HUD, and authentic hardware benchmarks.

---

## 1. Isolated Python 3.12 Neural Runtime & Reliability Architecture

Jarvis's primary `.venv` (Python 3.15.2) remains untouched. Optional neural speech dependencies are provisioned automatically into `%APPDATA%\Jarvis\voice-runtime\venv` (Python 3.12.16) via `jarvis/voice_runtime.py` (`uv`) with pinned GPU-capable packages (`kokoro-onnx==0.4.7`, `onnxruntime-gpu==1.22.0`, NVIDIA CUDA 12 / cuDNN 9 runtime wheels, `soundfile==0.13.1`, `numpy==2.2.3`).

### Stdio Worker Reliability (`jarvis/voice_runtime.py` & `jarvis/voice_worker.py`)
- **Local stdin/stdout JSON-RPC** (zero network sockets, `HF_HUB_OFFLINE=1` default).
- **Dedicated background `_stdout_reader` and `_stderr_drainer` threads** (bounded stderr ring buffer prevents pipe deadlocks; responses are matched by request ID and stale responses are dropped).
- **Non-blocking `cancel()`**: kills the worker subprocess immediately without contending on an in-flight `request()` lock, waking waiting callers immediately and scoping failure strictly to the terminated process so replacement workers recover cleanly (`0.29 ms` measured active cancellation latency).
- **Enforced `timeout` deadlines**: every request waits on a per-request `threading.Event` with a real deadline; expired requests kill the hung worker and raise `TimeoutError`.
- **Download & Pre-Load Security**:
  - Trusted expected SHA-256 digests (`kokoro-v1.0.onnx`, `kokoro-v1.0.int8.onnx`, `voices-v1.0.bin`) are verified on download **and again before ONNX Runtime loads any model**.
  - `_AllowlistRedirectHandler` validates **every HTTP redirect destination** against verified GitHub release hosts over HTTPS only.
  - `install_runtime()` and `download_voice_pack()` enforce Jarvis's offline (`allow_internet_tools`) and `lockdown` policies.

---

## 2. Reference Repository License & Security Audit

| Repository | Code License | Model License | Serialization / Security | Integration Approach |
|---|---|---|---|---|
| [thewh1teagle/kokoro-onnx](https://github.com/thewh1teagle/kokoro-onnx) | **MIT** | Apache-2.0 (Kokoro-82M) | **ONNX Runtime (safe, zero pickle)** | **Live & Verified** (`kokoro_onnx`) via Python 3.12 CUDA/CPU stdio worker; 4 British Jarvis voices + 4 TUKI voices |
| [hexgrad/kokoro](https://github.com/hexgrad/kokoro) | **Apache-2.0** | Apache-2.0 | Safetensors / PyTorch | Implemented adapter (`kokoro`) in `voice_worker.py` (optional PyTorch) |
| [QwenLM/Qwen3-TTS](https://github.com/QwenLM/Qwen3-TTS) | **Apache-2.0** | Apache-2.0 | Safetensors / Transformers | Implemented adapter (`qwen3_tts`) in `voice_worker.py` (optional >=8 GB VRAM GPU + local weights; original non-infringing prompts only) |
| [resemble-ai/chatterbox](https://github.com/resemble-ai/chatterbox) | **MIT** | MIT | Safetensors / PyTorch | Implemented adapter (`chatterbox`) in `voice_worker.py` (optional PyTorch) |
| [OHF-Voice/piper1-gpl](https://github.com/OHF-Voice/piper1-gpl) | **GPL-3.0** | MIT / CC-BY | ONNX via external CLI | **Strict GPL-3.0 boundary**: external CLI subprocess only (never imported) |
| [SYSTRAN/faster-whisper](https://github.com/SYSTRAN/faster-whisper) | **MIT** | MIT / Apache-2.0 | CTranslate2 (safe) | Local STT (`HF_HUB_OFFLINE=1`) |

---

## 3. Authentic Windows 10 Hardware & Precision Benchmarks

Measured live via `python -m scripts.benchmark_voice` on Windows 10 (**Intel Core i7-10875H**, **31.86 GB RAM**, **NVIDIA Quadro RTX 5000 16.0 GB VRAM**, driver `621.24`; isolated worker: Python `3.12.16`, `onnxruntime-gpu==1.22.0`, `kokoro-onnx==0.4.7`). Raw JSON: [voice-benchmark-windows.json](measurements/voice-benchmark-windows.json).

### A. CPU vs GPU & FP32 vs int8 Matrix (`bm_george`, ~8.8s audio)

| Config | Requested Device | Actual ONNX Provider (`sess.get_providers()[0]`) | Model File | Cold Time | Warm Time | Audio Duration | Warm RTF |
|---|---|---|---|---:|---:|---:|---:|
| **GPU FP32** | `gpu` | **`CUDAExecutionProvider`** | `kokoro-v1.0.onnx` | `1.193s` | **`1.091s`** | `8.811s` | **`0.124`** (8.1× RT) |
| GPU int8 | `gpu` | `CUDAExecutionProvider` | `kokoro-v1.0.int8.onnx` | `17.959s` | `13.735s` | `8.747s` | `1.570` |
| **CPU FP32** | `cpu` | **`CPUExecutionProvider`** | `kokoro-v1.0.onnx` | `6.842s` | **`5.203s`** | `8.811s` | **`0.591`** (1.7× RT) |
| CPU int8 | `cpu` | `CPUExecutionProvider` | `kokoro-v1.0.int8.onnx` | `20.305s` | `16.195s` | `8.875s` | `1.825` |

> **Engineering Finding:** On `CUDAExecutionProvider`, `kokoro-v1.0.int8.onnx` inserts 550 CPU↔GPU `Memcpy` nodes for `QuantizeLinear`/`DequantizeLinear` ops, making it **12.6× slower** than FP32 on GPU (`13.735s` vs `1.091s`) and **3.1× slower** than FP32 on CPU (`16.195s` vs `5.203s`). `voice_worker.py` therefore automatically prefers `kokoro-v1.0.onnx` (FP32) whenever installed, falling back seamlessly to `kokoro-v1.0.int8.onnx` if only the smaller 92 MB pack is present. DirectML (`onnxruntime-directml`) was tested and rejected due to a `ConvTranspose` runtime exception on Kokoro; native CUDA 12 via `onnxruntime-gpu==1.22.0` is used instead.

### B. Incremental Chunked Streaming (`synthesize_stream`, `CUDAExecutionProvider` FP32)

| Metric | Measured Result (`19.883s` total audio, 4 sentences) |
|---|---|
| **Time-to-First-Audio (TTFA, Chunk 0)** | **`0.971s`** (`< 1.0s`; chunk 0 arrived at `0.993s` client-side) |
| Chunk 1 Arrival | `2.062s` (`7.808s` audio) |
| Chunk 2 Arrival | `2.694s` (`1.515s` audio) |
| Chunk 3 Arrival | `3.827s` (`9.173s` audio) |
| Total Synthesis Time / RTF | `3.805s` / **`0.191`** |
| **Active Cancellation Latency (mid-inference)** | **`0.29 ms`** |
| **EchoGuard Spoken Barge-In Detection** | **`0.0038 ms`** |

### C. Real Kokoro-82M ONNX FP32 CUDA Neural Samples (8 Voices, 24 kHz PCM WAV)

| Assistant | Kokoro Voice | Provider | Cold Time | Warm Time | Audio Duration | RTF | Authentic Neural WAV Sample |
|---|---|---|---:|---:|---:|---:|---|
| **Jarvis** | `bm_george` (British Male · Refined) | `CUDAExecutionProvider` | `7.500s` | **`1.147s`** | `8.917s` | **`0.129`** | `docs/measurements/voice-samples/kokoro_jarvis_george.wav` (428 KB) |
| **Jarvis** | `bm_daniel` (British Male · Crisp) | `CUDAExecutionProvider` | — | **`1.009s`** | `7.616s` | **`0.132`** | `docs/measurements/voice-samples/kokoro_jarvis_daniel.wav` (366 KB) |
| **Jarvis** | `bm_fable` (British Male · Warm) | `CUDAExecutionProvider` | — | **`1.207s`** | `7.872s` | **`0.153`** | `docs/measurements/voice-samples/kokoro_jarvis_fable.wav` (378 KB) |
| **Jarvis** | `bm_lewis` (British Male · Formal) | `CUDAExecutionProvider` | — | **`1.141s`** | `8.704s` | **`0.131`** | `docs/measurements/voice-samples/kokoro_jarvis_lewis.wav` (418 KB) |
| **TUKI** | `bf_emma` (British Female · Analytical) | `CUDAExecutionProvider` | — | **`1.134s`** | `8.576s` | **`0.132`** | `docs/measurements/voice-samples/kokoro_tuki_emma.wav` (412 KB) |
| **TUKI** | `bf_isabella` (British Female · Warm) | `CUDAExecutionProvider` | — | **`1.172s`** | `8.853s` | **`0.132`** | `docs/measurements/voice-samples/kokoro_tuki_isabella.wav` (425 KB) |
| **TUKI** | `af_bella` (Technical Crisp) | `CUDAExecutionProvider` | — | **`1.301s`** | `9.877s` | **`0.132`** | `docs/measurements/voice-samples/kokoro_tuki_bella.wav` (474 KB) |
| **TUKI** | `af_heart` (Natural) | `CUDAExecutionProvider` | — | **`1.169s`** | `9.579s` | **`0.122`** | `docs/measurements/voice-samples/kokoro_tuki_heart.wav` (460 KB) |

### D. Windows SAPI5 Compatibility Baseline (Clearly Separated — Never Substituted for Neural)

| Assistant | Engine | Voice Used | Cold Time | Warm Time | Audio Duration | RTF | Baseline WAV Sample |
|---|---|---|---:|---:|---:|---:|---|
| **Jarvis** | `windows_sapi` | `Microsoft David Desktop` (185 WPM) | `0.369s` | `0.124s` | `8.973s` | `0.014` | `docs/measurements/voice-samples/jarvis_sapi_baseline.wav` (396 KB) |
| **TUKI** | `windows_sapi` | `Microsoft Zira Desktop` (200 WPM) | `0.219s` | `0.142s` | `8.063s` | `0.018` | `docs/measurements/voice-samples/tuki_sapi_baseline.wav` (356 KB) |

### E. Optional Engine & Host Notes
- **Kokoro PyTorch, Qwen3-TTS, Chatterbox, Piper:** Real inference adapters exist in `jarvis/voice_worker.py` (and external CLI subprocess for GPL-3.0 Piper in `jarvis/speech_engines.py`), but their multi-GB optional PyTorch/HuggingFace weights are not installed by default on this host and remain explicitly marked optional in Voice Studio.
- **Concurrent Local LLM (Ollama) Note:** Ollama is not installed on this workstation; concurrent Ollama + neural TTS VRAM contention was therefore not measured on this host (idle Quadro RTX 5000 VRAM after Kokoro FP32 CUDA runs is `0.03 GB / 16.0 GB`, leaving `15.74 GB` free).
