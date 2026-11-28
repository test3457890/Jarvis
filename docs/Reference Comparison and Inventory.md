# Jarvis Next Generation — Reference Repository Inventory, Comparison & Licensing Audit

**Audit Date:** November 28, 2026  
**Target Branch:** `feature/jarvis-next-phase` (synchronized with `main` / `v1.4.1` @ `3f930ec`)  
**Reference Repositories Audited:**
1. **Our Repository:** `https://github.com/test3457890/Jarvis` (`v1.4.1` @ `3f930ec`, Apache 2.0)
2. **OpenJarvis:** `https://github.com/open-jarvis/OpenJarvis` (`main` @ `9c03f6c`, Apache 2.0)
3. **ankitjha67/JARVIS:** `https://github.com/ankitjha67/JARVIS` (`main` @ `5c5b34d`, README declares MIT — no standalone `LICENSE` file)

---

## 1. Licensing & Clean-Room Verification

| Repository | Standalone License File | Package / README Metadata | Copyright Notice | Reuse Decision |
|---|---|---|---|---|
| **test3457890/Jarvis** (ours) | `LICENSE` (Apache 2.0) | Apache 2.0 | Project authors | Primary codebase (Apache 2.0) |
| **open-jarvis/OpenJarvis** (`9c03f6c`) | `LICENSE` (Apache 2.0, 190 lines); no `NOTICE` file | `pyproject.toml`: `Apache-2.0`; `README.md`: Apache 2.0 | `Copyright 2025 The OpenJarvis Authors` (Hazy Research & Stanford SAIL) | **Compatible (Apache 2.0)**, but we continue **independent clean-room implementation** (zero source files copied) to preserve Jarvis's fail-closed security model and zero-dependency core. Architectural inspiration credited in `docs/Third Party Attribution.md`. |
| **ankitjha67/JARVIS** (`5c5b34d`) | **None.** No `LICENSE`, `LICENSE.md`, `COPYING`, or `NOTICE` anywhere in repo. | `README.md` has MIT badge + `## License: MIT`; `pyproject.toml` & `ui/package.json` have **no** `license` field; source files have **no** SPDX/copyright headers. | **None present.** | **Do NOT copy any source code, logos (`assets/logo.svg`/`logo.ico`), or screenshots.** Because formal MIT license text and copyright notice are absent, every inspired capability must be **implemented 100% independently** with Jarvis's own identity, branding, and security architecture. |

---

## 2. High-Level Architecture & Scale Comparison

| Dimension | Our Jarvis (`v1.4.1`) | OpenJarvis (`9c03f6c`) | ankitjha67/JARVIS (`5c5b34d`) |
|---|---|---|---|
| **Runtime & Shell** | Single Python process + loopback browser HUD (`127.0.0.1:8765`, pure stdlib HTTP/SSE) + optional Rust CLI/lib (`jarvis-core`) | Python FastAPI/Uvicorn server + React/Vite/Tauri 2 desktop + Click CLI + Textual TUI + 17 Rust crates (PyO3) | Python FastAPI/Uvicorn (`127.0.0.1:47821`) + `pywebview` (WebView2/WKWebView) + React 19/Vite/Zustand HUD + Kotlin Android companion |
| **Security Posture** | **Strongest**: Fail-closed `net.py` allowlist with public-IP pinning & TLS 1.2+, DPAPI secrets, Lockdown, prompt-injection fencing + scrub, Sentinel posture audit, Rust policy/audit verifier, Finance/Health fail-closed guards | Strong modular security: `GuardrailsEngine` (WARN/REDACT/BLOCK), Secret/PII/Injection scanners, 10 RBAC capabilities, `TaintSet` info-flow, SSRF, Ed25519 signing, Docker/Podman sandbox | T0–T3 risk tiers, taint flag on untrusted reads, stale-target file `stat()` check, path/shell denylist, keyring secrets, kill switch. **Gaps**: fast-path bypasses policy/audit; `UndoStack`/`ConfirmationGate`/`OutcomeVerifier` unreferenced in `orchestrator.py`; no container/OS sandbox. |
| **Registered Tools / Skills** | **74** `@skill` tools (all wired through `skills.run()` permissions, Lockdown, confirmation & audit) | **59** tools + 27 connectors + 30 channels + 20 TOML skills | **231** `@tool` defs across **64** modules (230 on macOS) + 22 MCP catalogue entries. **Only 16/64 modules (59 tools) have test references; 48/64 modules (172 tools) have 0 tests.** |
| **AI Providers** | Ollama (default), numeric-loopback OpenAI-compat, opt-in per-request Cloud (OpenAI, Anthropic, Gemini) | 16 engines (Ollama, vLLM, SGLang, llama.cpp, MLX, LM Studio, Exo, Nexa, Uzu, Apple FM, Lemonade, NIM, Cloud, LiteLLM, Gemma.cpp, AFM) | 8 built-in (LM Studio, Ollama, NVIDIA NIM, Anthropic, OpenAI, Gemini, OpenRouter, Groq) + custom OpenAI-compat |
| **Automated Tests** | **342 passed, 7 skipped** (Python) + **4 passed** (Rust) + **67/67** live Chrome HUD audit checks | 8,117 Python test functions + 440 Rust tests + 27 Vitest files (unverified locally) | 159 Python tests (11 files) + 15 Vitest tests |

---

## 3. Feature-by-Feature Comparison Matrix (10 Domains)

Status legend: **Shipped** = implemented & tested in Jarvis v1.4.1; **Partial** = slice exists, expansion planned; **Missing** = not yet in Jarvis.

| Domain | Capability | Jarvis v1.4.1 | OpenJarvis | ankitjha67/JARVIS | Next-Gen Plan |
|---|---|---|---|---|---|
| **2. Native UX** | Native desktop window, system tray, global hotkeys, start-at-login | Missing (browser HUD + Start Menu shortcut) | Tauri 2 desktop | `pywebview` + Win32 tray/hotkeys (`Ctrl+Alt+J`, kill switch) | Phase 4: Optional `pywebview`/tray launcher + global hotkeys, preserving browser HUD & all legacy views/themes |
| **2. Native UX** | Real-time system vitals (CPU, GPU, VRAM, RAM, battery, disk, net, top processes) | Partial (`hardware.py` static snapshot only) | `telemetry/` (NVML/AMD/Apple/RAPL energy, FLOPs, ITL) | `telemetry.py` (`psutil` + `pynvml`, 3s cache, top 8 processes) | **Phase 1**: Real-time `jarvis/telemetry.py` + `/api/vitals` + live sparkline HUD panel |
| **2. Native UX** | Workspaces (Console, Audit, Repair, Runs, Settings), interactive approval cards, compact floating view | Partial (Classic/Command/Ambient + Compact browser + approval banner) | Dashboard + TUI | Console/Audit/Repair/Runs/Settings (floating orb unbuilt) | **Phase 1** (HUD workspace tabs, tool history, dry-run) + Phase 4 (floating compact widget) |
| **3. AI Providers** | 8+ providers (Ollama, LM Studio, OpenAI, Anthropic, Gemini, NVIDIA NIM, OpenRouter, Groq, Custom OpenAI-compat) | Partial (Ollama, loopback OpenAI-compat, OpenAI/Anthropic/Gemini) | 16 local & cloud engines | 8 built-in + custom OpenAI-compat | **Phase 1**: Unified provider registry (`jarvis/providers.py`) + expanded `cloudprovider.py` + fail-closed `net.py` |
| **3. AI Providers** | Runtime model discovery, health monitoring, failover, privacy modes (`local`/`hybrid`/`cloud`), complexity routing, cost tracking, fast-path | Partial (Ollama inventory, no silent cloud fallback, streaming) | `MultiEngine`, `complexity.py`, `estimate_cost()`, `HeuristicRouter` | Live benchmark selector, failover, `privacy_mode`, token counts (no USD cost), buggy fast-path | **Phase 1**: Provider health/discovery, complexity classifier, USD cost estimator, **policy-enforced audited Fast-Path** |
| **3. AI Providers** | Cooperative reasoning, specialist agents, parallel execution, independent verification | Shipped (Jarvis+TUKI `/review`, 6 profiles, recursion guard) | 22 agents (incl. hybrid research) | `agent_tools.py` (untested), `OutcomeVerifier` (unwired) | Phase 2: Parallel task execution + wired outcome verification |
| **4. Computer Automation** | Unified permission-controlled tool registry (T0–T3), dry-run previews, stale-target checks, undo journal | Partial (74 skills, risky=ask, Lockdown, file/code undo) | 59 tools + RBAC capabilities | 231 tools (T0–T3, stale-target `stat()`, unwired `UndoStack`) | **Phase 1**: T0–T3 risk tiers, `dry_run()` preview, stale-target guard, unified Undo Journal + Phase 3 desktop/Playwright/clipboard/screenshot tools |
| **5. Voice** | British Jarvis + separate TUKI voice, wake words, local Whisper, streaming TTS, follow-ups, dictation, voice enrollment, multilingual | Partial (SAPI/Piper, British detection, Whisper, follow-up, hold-to-record) | 3 STT + 4 TTS engines | `openwakeword`, 9 STT, 7 TTS, voiceprint enrollment | Phase 5: Streaming sentence TTS, echo-safe barge-in, voice enrollment (non-auth), multilingual & standing instructions |
| **6. Agents & Memory** | Background task engine, checkpoints, crash recovery, scheduled reminders/routines, condition monitoring, macro recording, semantic memory, reviewable extraction | Partial (resumable workflows, daily doc watches, SQLite memory + expiry + projects) | `TaskScheduler`, DAG `workflow/`, auto-extracted fact store with trust tiers | `bg_task_*`, `sentinel_*`, `workflow_record_*`, `routine_*` (all untested) | Phase 2: Background Task Engine with SQLite checkpoints/recovery/cancel, condition monitors, macro recorder, reviewable memory extraction |
| **7. Connectors** | Google Workspace, M365, Teams, Discord, Slack, GitHub, Email/Cal, Telegram, Home Assistant, Music, Weather, Flights, MCP | Partial (GitHub, RSS, NWS, Canvas, SMTP, OAuth PKCE scaffolding, local stdio MCP) | 27 connectors + 30 channels + MCP + A2A | 22 MCP catalogue, Telegram, HA, Music, Weather, Flights (untested) | Phase 6: OAuth callback completion, Telegram/Discord/Slack/HA/Music/Flights adapters via official APIs + allowlist |
| **8. Finance, Research & Pro** | Financial tracking, budgeting, portfolio, CSV/XLSX comparison, variance reports, doc revision diff, requirements/UAT tracking, case management, exportable reports | Partial (`domains.py` fail-closed guards, `/research-docs`, `/research-all`) | `fx_macro_data`, `deep_research` | `intake_tools`, `regulatory_compare`, `uat_trace`, `case_tools` (partial) | Phase 7: Dedicated Professional Workspace (CSV/XLSX variance, doc revision diff, UAT & case tracker, private local finance analytics under `domains.py`) |
| **9. Mobile & Geospatial** | Android companion, iOS architecture, secure pairing, push, approved remote commands, 3D globe, public flight/satellite/maritime/weather/earthquake/wildfire/SAR | Partial (390px phone HUD, loopback-only) | WebChat/Telegram/Mobile channels | Kotlin Android app (pairs `/api/pair`, WS `/ws`), `gods_eye_tools` (clones external CesiumJS) | Phase 8: Authenticated opt-in companion pairing (disabled by default, never public internet) + local-first Geospatial workspace using public feeds |
| **10. Security** | Sentinel, Rust core, T0–T3 permissions, dry-run, untrusted fencing, prompt-injection defense, DPAPI, allowlist, sandboxing, undo journals, kill switch, redaction, audit | Shipped (Sentinel, Rust `jarvis-core`, DPAPI, allowlist, Lockdown, fencing) | Guardrails, TaintSet, RBAC, Docker/Podman, Ed25519 | T0–T3, taint, stale-target, kill switch, redact filter | **Phase 1** (T0–T3, stale-target, Undo Journal, expanded redaction, Rust CLI/CI hooks) + Phase 3 (extension/MCP process isolation & kill switch hotkey) |

---

## 4. Complete Inventory of `ankitjha67/JARVIS` (`5c5b34d`)

### 4.1 Advertised vs Verified Counts
- **Tool Modules:** 64 modules imported in `src/jarvis/tools/__init__.py` (verified via AST).
- **Tools:** 231 `@tool` definitions on Windows (230 on macOS; `night_light_toggle` is `win32`-only).
- **MCP Catalogue:** 22 pre-configured server entries in `mcp_catalogue_tools.py`.
- **Model Providers:** 8 built-in (`lmstudio`, `ollama`, `nvidia`, `anthropic`, `openai`, `gemini`, `openrouter`, `groq`) + custom OpenAI-compatible.
- **Roadmap Ideas (`FEATURE_IDEAS.md`):** 84 historical backlog ideas across 12 categories + 24 roadmap extension items (#85–108).

### 4.2 Tool Module Maturity Classification (All 64 Modules)

#### A. Implemented & Test-Referenced (16 modules, 59 tools)
`browser.py` (8), `clipboard_tools.py` (2), `comms.py` (5), `computer.py` (4), `desktop.py` (10), `extra.py` (4), `files.py` (5), `intake_tools.py` (1), `media.py` (2), `privacy_tools.py` (4), `quick_settings_tools.py` (6), `regulatory_tools.py` (1), `search_tools.py` (2), `shell.py` (1), `system.py` (3), `uat_tools.py` (1).

#### B. Implemented in Code, Unverified — Requires External APIs / Services / Hardware (15 modules, 46 tools, 0 tests)
`buffer_tools.py` (4), `chrome_tools.py` (7), `credential_tools.py` (3), `flight_tools.py` (2), `gods_eye_tools.py` (4), `homeassistant_tools.py` (4), `imagegen_tools.py` (2), `mcp_catalogue_tools.py` (3), `music_tools.py` (3), `revenucat_tools.py` (4), `telegram_tools.py` (2), `vision_tools.py` (3), `voice_call_tools.py` (3), `weather_tools.py` (1), `youtube_tools.py` (3).

#### C. Implemented in Code, Unverified — Local-Only with 0 Test Coverage (33 modules, 126 tools, 0 tests)
`action_history_tools.py` (3), `agent_tools.py` (7), `ambient_tools.py` (3), `background_task_tools.py` (4), `case_tools.py` (3), `clipboard_manager_tools.py` (5), `codereview_tools.py` (4), `conversation_tools.py` (2), `dev_tools.py` (5), `digest_tools.py` (2), `dryrun_tools.py` (2), `file_processor_tools.py` (2), `file_tools.py` (5), `fitness_tools.py` (4), `focus_tools.py` (4), `incident_tools.py` (4), `memory_tools.py` (4), `note_tools.py` (6), `persona_tools.py` (3), `preset_tools.py` (2), `project_tools.py` (2), `research_tools.py` (2), `routine_tools.py` (5), `scheduler_tools.py` (3), `scratchpad_tools.py` (5), `screenshot_tools.py` (4), `security_tools.py` (4), `sentinel_tools.py` (4), `settings_tools.py` (4), `skill_tools.py` (2), `timer_tools.py` (7), `verification_tools.py` (2), `workflow_tools.py` (6).

#### D. Experimental / Partial / Disconnected Bugs Found in Code Review
1. `UndoStack`, `ConfirmationGate`, `ModelLadder`, and `OutcomeVerifier` are instantiated in `gateway.py` with **0 call sites** in `orchestrator.py`.
2. `fast_path.py` references 3 non-existent tools (`system_lock`, `system_sleep`, `app_launch`) and **bypasses policy and audit**.
3. `Orchestrator.run_headless()` calls `tool.args_type` / `tool.fn` instead of `tool.args_model` / `tool.handler` (`AttributeError`).
4. macOS desktop UX is documented as **untried** on real hardware (`docs/MACOS.md`).
5. USD cost tracking and floating mini-orb (#83) are **not implemented**.

### 4.3 Inventory of the 84 Backlog Ideas (+ 24 Roadmap Extensions) in `FEATURE_IDEAS.md`
- **Memory (1–8):** Semantic recall, auto-extraction, conversation search, episodic memory, project spaces, forgetting/expiry, preference learning, daily summaries.
- **Proactive & Scheduled (9–17):** Morning briefings, condition sentinels, recurring routines, idle triggers, deadline nudges, digest previews, battery/disk alerts, calendar prep, focus-mode automation.
- **Vision (18–25):** Screen capture, OCR, screen search, region selection, multi-monitor capture, screenshot tagging/organization, visual error reading, UI tree inspection.
- **Voice (26–37):** Custom wake word, owner voiceprint enrollment, multi-STT fallback, neural TTS, streaming speech, interruption/barge-in, dictation, multilingual/Hinglish, voice presets, whisper local GPU, ambient listening, push-to-talk.
- **Communication (38–44):** Email triage, Telegram bot, Discord/Slack/Teams, WhatsApp, voice calls (Twilio), contact lookup, message templates.
- **Productivity (45–54):** Timers/stopwatches, notes/daily journal, scratchpad, focus/Pomodoro sessions, clipboard history/pinning, quick settings (brightness/Wi-Fi/BT/Night Light), fitness reminders, presets, calendar sync, task tracking.
- **File Knowledge (55–61):** Indexed search, content grep, file extraction/conversion (PDF/DOCX/XLSX), web clipping, daily notes, duplicate finder, archive tools.
- **Skills, Agents & MCP (62–69):** Custom skill creation, multi-agent planning/handoff, background tasks, workflow recording/replay, MCP catalogue installer, Docker code sandbox (#68, unbuilt), dry-run inspector, tool verification.
- **Dev Tools (70–74):** Git status/diff/log/blame, code review stats, error explanation, project scaffolding/analysis, workspace launcher.
- **Smart Home & Phone (75–78):** Home Assistant control, music playback/lyrics, Android companion, remote notifications.
- **Security & Privacy (79–82):** Network/DNS/port/startup privacy audit, password breach/reuse check, emergency lock/kill, incident capture.
- **HUD & Self-Maintenance (83–84):** Compact floating mini-orb (#83, unbuilt), self-diagnostics/repair view (#84).
- **Extensions (#85–108):** Run Center (#85), save-as-workflow, safe resume, stale-target previews, Test Lab, privacy/cost budgets, change inbox, project rooms, sourced memory, workflow health, evidence packs, Android approvals, Explorer actions, Hinglish pack, shift handover, regulatory desk, Excel reconciliation, UAT tracker, doc intake, pre-market brief, report refresh, local AI ops dashboard, personal case files.

---

## 5. Complete Inventory of `OpenJarvis` (`9c03f6c`)

- **Scale:** 691 Python files across 32 subpackages (`src/openjarvis/`), 125 Rust files across 17 crates (`rust/`), 112 TS/JS files (`frontend/` + Tauri 2), 8,117 Python tests + 440 Rust tests + 27 Vitest files.
- **5 Core Primitives:** Intelligence (`model_catalog.py`), Engine (`InferenceEngine` ABC + 16 registered engines + `MultiEngine`), Agents (22 agents: 13 core + 9 hybrid research), Memory/Storage (8 retrieval backends: SQLite FTS5, BM25, dense, FAISS, ColBERT, hybrid RRF, KG, connector store + JSONL fact store with trust tiers), Learning/Traces (SQLite `TraceStore`, routing policies, DSPy/GEPA/ACE, SFT/GRPO, `spec_search`).
- **Telemetry & Efficiency:** NVIDIA (`pynvml`), AMD (`amdsmi`), Apple Silicon (`IOReport`), Intel RAPL energy monitors; FLOPs/MFU, inter-token latency (ITL), prefill/decode phase metrics, USD cost/savings calculator (`PRICING` table).
- **Security & Sandboxing:** `GuardrailsEngine` (WARN/REDACT/BLOCK), Secret/PII/Injection scanners, 10 RBAC capabilities, `TaintSet` exfiltration policy, SSRF guard, Ed25519 manifest signing, Docker/Podman `ContainerRunner` with `MountAllowlist`, partial `WasmRunner`.
- **Protocols & Ecosystem:** 59 tools, 30 channels (WhatsApp Baileys blocked; Signal send-only), 27 connectors, MCP client/server, A2A protocol, DAG workflows, cron `TaskScheduler`.

---

## 6. Command Center Update: 6-Category Classification & Additional References

### 6.1 Additional Reference Audits
- **`bilawalsidhu/gods-eye-view` (MIT License):** Real-time 3D spatial console using CesiumJS + Model Context Protocol (`src/tools/mcp/`). Public feeds work without keys; high-res 3D photorealistic tiles require an optional Cesium ion / Google Maps token. Integrated as an optional vetted entry in `jarvis/connectors.py` (`gods-eye-view-mcp`), while Jarvis provides a native, zero-tracking, offline-capable 3D Globe workspace (`jarvis/geospatial.py` + `frontend/src/components/Globe3D.tsx`) that explicitly tags every layer as `live`, `delayed`, `estimated`, `simulated`, or `user_annotation`.
- **Sentinel Defensive Security References (`jarvis/sentinel_ops.py`):**
  - `wazuh/wazuh` (GPL-2.0): SIEM / Endpoint HIDS — optional local alert adapter.
  - `OISF/suricata` (GPL-2.0): Network IDS — read-only EVE JSON alert parser (`parse_ids_eve_alerts`).
  - `zeek/zeek` (BSD-3-Clause): Passive NSM — optional local log integration.
  - `VirusTotal/yara` (BSD-3-Clause): Defensive pattern matcher — optional local CLI adapter.
  - `Velocidex/velociraptor` (AGPL-3.0): DFIR telemetry — optional external integration.
  - `aquasecurity/trivy` (Apache-2.0): Container & dependency CVE scanner — optional local CLI adapter.

### 6.2 6-Category Classification of Reference Capabilities (vs `feature/jarvis-command-center`)
- **Fully Implemented (Core Local & Command Center):** 19-workspace React/TS/Zustand Command Center HUD + Legacy HUD toggle, CUDA FP32 Kokoro-82M neural TTS (`RTF 0.124`, `<1s` streaming TTFA, `0.29 ms` active cancellation), Windows UIA accessibility-tree inspection & safe approved control, 3D Globe with SAR grid / orbital tracks / annotations / voice nav, Smart Home & Authorized Camera registry (DPAPI), Sentinel FIM / secret scanner / EVE JSON alerts / firewall dry-run preview / evidence pack, Rust `jarvis-core` container & path policy verifier, hardened Docker command builder, cooperative Jarvis+TUKI multi-agent plans with bounded recursion & visual automations, pure-Python `.docx`/`.pptx` generator + citations + knowledge graph, searchable 16-item MCP/Connector catalogue, live vitals & process radar, undo journal, Android companion APK.
- **Partially Implemented:** Live browser session form-fill & download manager (Playwright allowlist enforced; complex site workflows opt-in), Qwen3-TTS / Chatterbox / Kokoro PyTorch / Piper CLI (real adapters implemented; multi-GB optional weights/CLI not bundled by default), Docker live container management (CLI + hardened sandbox builder implemented; requires running Docker daemon on host).
- **Requires External Credentials:** Google Workspace OAuth, Microsoft 365 OAuth, GitHub API, Canvas LMS, Brave Search, cloud AI providers (OpenAI/Anthropic/Gemini/Groq/OpenRouter/NIM), Cesium ion 3D terrain tiles, Home Assistant / Frigate tokens, Telegram/Discord/Slack bots.
- **Requires Hardware:** User-approved SDR receivers, physical ONVIF/RTSP cameras, local GPU >=8 GB VRAM for Qwen3-TTS, local microphone for wake-word STT, physical Android device / emulator for `adb` companion testing.
- **Missing / Deferred:** Native iOS SwiftUI companion binary (architecture & Xcode requirements documented in `docs/Mobile Companion Architecture.md`; requires macOS/Xcode build host), concurrent Ollama + TTS VRAM benchmark on this workstation (Ollama is not installed on this host).
- **Not Appropriate (Explicitly Prohibited):** Password/auth form automation, UAC/security prompt bypass, covert surveillance / tracking private individuals, unauthenticated third-party camera discovery, facial identification / biometric tracking, retaliatory DDoS / offensive security automation, privileged containers or mounting `docker.sock`, automatic installation of arbitrary code from GitHub.
