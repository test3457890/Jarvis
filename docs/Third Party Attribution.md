# Third-Party Attribution and Dependency Ledger

Jarvis is licensed under the [Apache License 2.0](../LICENSE).

## Reference Projects Reviewed (Architectural Inspiration Only)

No third-party source code or binary assets were copied from external repositories during this integration pass. All newly implemented modules (`hardware.py`, `cloudprovider.py`, `agents.py`, `mcp_client.py`, `sentinel.py`, `connectors.py`, `domains.py`, `rust/jarvis-core`) were authored independently to fit Jarvis's security boundaries and architecture.

| Reference Project | Repository | License | Concepts Reviewed | Code Copied |
|---|---|---|---|---|
| OpenJarvis | https://github.com/open-jarvis/OpenJarvis | Apache 2.0 | Modular specialist agents, bounded delegation/traces, local-first hardware awareness, MCP server integration, connector architecture, Rust core crate structure | None (independent implementation) |
| Project NOMAD | https://github.com/Crosstalk-Solutions/project-nomad | Separate optional server | Optional Kiwix offline library & local service port status | None (external service integration) |
| isair/Jarvis | https://github.com/isair/jarvis | Reference only | Room context, activity timeline, dictation flow | None |
| PersonalJarvis | https://github.com/PersonalJarvis/PersonalJarvis | Reference only | Isolated coding worktrees, routines, permission scopes | None |
| OpenDex | https://github.com/wassgha/opendex | MIT (reference only) | Compact layout, interchangeable voice & model providers | None |
| llama.cpp server | https://github.com/ggml-org/llama.cpp | MIT (protocol spec) | OpenAI-compatible `/v1/models` and `/v1/chat/completions` JSON/SSE wire protocol | None (protocol compatibility only) |
| Model Context Protocol | https://modelcontextprotocol.io/ | MIT (open spec) | Stdio JSON-RPC 2.0 `initialize`, `tools/list`, `tools/call` wire protocol | None (protocol compatibility only) |

## Runtime and Development Dependencies

| Package | Role in Jarvis | Notes |
|---|---|---|
| Python Standard Library | HTTP server, SQLite/FTS5, XML/HTML parsing, subprocess, DPAPI ctypes | Built-in |
| `faster-whisper` | Optional local speech-to-text | Local model cache (`HF_HUB_OFFLINE=1` at runtime) |
| `sounddevice`, `numpy` | Optional local microphone capture & audio level metering | Local audio only |
| `pyttsx3` | Local Windows SAPI text-to-speech | Optional Piper CLI supported separately |
| `psutil` | Local CPU, RAM, disk, and battery metrics | Optional graceful fallback |
| `Pillow` | Image validation, EXIF normalization, bounded resizing | Required for local vision/image tools |
| `pypdf`, `python-docx` | Local PDF and Word text extraction | Bounded file/page/size limits |
| `pytest`, `playwright` | Automated unit, integration, Windows installer, and browser HUD tests | Development/CI only |
| Rust standard library (`std`) | `rust/jarvis-core` native policy and audit verifier | Zero external Cargo crates |
