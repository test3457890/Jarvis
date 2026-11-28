# Third-Party Attribution and Dependency Ledger

Jarvis is licensed under the [Apache License 2.0](../LICENSE).

## Reference Projects Reviewed (Architectural Inspiration Only)

No third-party source code, branding, logos, or binary assets were copied from external repositories. All newly implemented modules (`hardware.py`, `telemetry.py`, `providers.py`, `fastpath.py`, `undo.py`, `cloudprovider.py`, `agents.py`, `mcp_client.py`, `sentinel.py`, `connectors.py`, `domains.py`, `rust/jarvis-core`) were authored independently to fit Jarvis's security boundaries and architecture.

| Reference Project | Repository | Audited Commit | License Verification | Concepts Reviewed | Code / Assets Copied |
|---|---|---|---|---|---|
| OpenJarvis | https://github.com/open-jarvis/OpenJarvis | `9c03f6c` | **Apache 2.0** (`LICENSE` present; `Copyright 2025 The OpenJarvis Authors`; no `NOTICE` file) | Modular specialist agents, bounded delegation/traces, local-first hardware & energy/cost telemetry, complexity routing, taint/RBAC security models, MCP/A2A architecture, Rust core crate structure | None (independent implementation) |
| ankitjha67/JARVIS | https://github.com/ankitjha67/JARVIS | `5c5b34d` | **Unverified MIT** (`README.md` declares MIT badge/text, but **no standalone `LICENSE` file, no package license field, and no copyright notice exist**) | Multi-provider routing & discovery, T0–T3 risk tiers, stale-target file checks, system vitals & top processes, Console/Audit/Repair/Runs/Settings HUD views, professional UAT/regulatory/intake workflows, Android companion pairing | **None (strict clean-room policy; no code, logos, or screenshots reused)** |
| Project NOMAD | https://github.com/Crosstalk-Solutions/project-nomad | Separate optional server | Separate installation | Optional Kiwix offline library & local service port status | None (external service integration) |
| isair/Jarvis | https://github.com/isair/jarvis | Reference only | Reference only | Room context, activity timeline, dictation flow | None |
| PersonalJarvis | https://github.com/PersonalJarvis/PersonalJarvis | Reference only | Reference only | Isolated coding worktrees, routines, permission scopes | None |
| OpenDex | https://github.com/wassgha/opendex | Reference only | MIT (reference only) | Compact layout, interchangeable voice & model providers | None |
| llama.cpp server | https://github.com/ggml-org/llama.cpp | Protocol spec | MIT (protocol spec) | OpenAI-compatible `/v1/models` and `/v1/chat/completions` JSON/SSE wire protocol | None (protocol compatibility only) |
| Model Context Protocol | https://modelcontextprotocol.io/ | Protocol spec | MIT (open spec) | Stdio JSON-RPC 2.0 `initialize`, `tools/list`, `tools/call` wire protocol | None (protocol compatibility only) |
| Kokoro / Kokoro-ONNX | https://github.com/hexgrad/kokoro · https://github.com/thewh1teagle/kokoro-onnx | Reference & optional engine | Apache-2.0 / MIT | Optional local ONNX neural TTS & British/TUKI voice IDs | None (optional runtime adapter only) |
| Qwen3-TTS | https://github.com/QwenLM/Qwen3-TTS | Reference & optional engine | Apache-2.0 | Optional expressive VoiceDesign local GPU synthesis | None (optional runtime adapter only) |
| Chatterbox | https://github.com/resemble-ai/chatterbox | Reference & optional engine | MIT | Optional expressive local TTS | None (optional runtime adapter only) |
| Piper (`piper1-gpl`) | https://github.com/OHF-Voice/piper1-gpl | Optional external CLI | **GPL-3.0** | Invoked strictly out-of-process via subprocess (never imported/linked) | None (external subprocess boundary) |
| faster-whisper | https://github.com/SYSTRAN/faster-whisper | Optional runtime dep | MIT | Local CTranslate2 speech-to-text (`HF_HUB_OFFLINE=1`) | None (optional package) |

## Runtime and Development Dependencies

| Package | Role in Jarvis | Notes |
|---|---|---|
| Python Standard Library | HTTP server, SQLite/FTS5, XML/HTML parsing, subprocess, DPAPI ctypes | Built-in |
| `faster-whisper` | Optional local speech-to-text | Local model cache (`HF_HUB_OFFLINE=1` at runtime) |
| `sounddevice`, `numpy` | Optional local microphone capture & audio level metering | Local audio only |
| `pyttsx3` | Local Windows SAPI text-to-speech | Optional Piper CLI supported separately |
| `psutil` | Local CPU, RAM, disk, battery, network, and process telemetry | Optional graceful fallback |
| `Pillow` | Image validation, EXIF normalization, bounded resizing | Required for local vision/image tools |
| `pypdf`, `python-docx` | Local PDF and Word text extraction | Bounded file/page/size limits |
| `pytest`, `playwright` | Automated unit, integration, Windows installer, and browser HUD tests | Development/CI only |
| Rust standard library (`std`) | `rust/jarvis-core` native policy and audit verifier | Zero external Cargo crates |
