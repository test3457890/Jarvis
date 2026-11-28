# Jarvis Next Generation — Master Development Tracker

**Updated:** November 28, 2026  
**Active Branch:** `feature/jarvis-next-phase` (synchronized with `main` / `v1.4.1` security patch @ `3f930ec`)  
**Stable Release Preserved:** `v1.4.1` (remains stable until Next-Gen phases are independently verified and merged via manageable PRs)  
**Reference Inventory:** See [Reference Comparison and Inventory](Reference%20Comparison%20and%20Inventory.md) and [Third Party Attribution](Third%20Party%20Attribution.md).

---

## 1. Phased Implementation Roadmap (Manageable PRs)

| Phase | Scope | Key Modules | Target Status |
|---|---|---|---|
| **Phase 0 (Prep)** | Sync `main` (`v1.4.1`) & `feature/jarvis-next-phase`, baseline tests (342 Py + 4 Rust), full inventory of `ankitjha67/JARVIS` (64 modules / 231 tools / 8 providers / 84+24 ideas) & `OpenJarvis`, license audit, Master Tracker | `docs/Reference Comparison and Inventory.md`, `docs/Third Party Attribution.md`, `docs/Development Tracker.md` | **Completed** |
| **Phase 1 (Foundation)** | Real-time System Vitals (`psutil` + `nvidia-smi` + ring buffer + top processes), 8+ AI Provider Registry (Ollama, LM Studio, OpenAI, Anthropic, Gemini, NVIDIA NIM, OpenRouter, Groq, Custom OpenAI-compat) with health/discovery, privacy mode (`local`/`hybrid`/`cloud`), complexity tiering, USD cost estimation, **policy-enforced audited Fast-Path**, T0–T3 tool risk tiers, `dry_run()` preview, stale-target file fingerprint guard, unified Undo Journal, secret redaction, and authenticated `/api/vitals`, `/api/providers`, `/api/tools/history`, `/api/tools/dry-run`, `/api/undo` routes | `jarvis/telemetry.py`, `jarvis/providers.py`, `jarvis/fastpath.py`, `jarvis/undo.py`, `jarvis/cloudprovider.py`, `jarvis/net.py`, `jarvis/skills.py`, `jarvis/secure.py`, `jarvis/config.py`, `jarvis/brain.py`, `jarvis/__main__.py`, `jarvis/webui.py`, `tests/test_nextgen_phase1.py` | **Completed (Backend & APIs Verified)** |
| **Phase 2 (Agents, Tasks & Memory)** | Persistent Background Task Engine with SQLite checkpoints, crash recovery & cancellation; condition monitoring sentinels; workflow/macro recording & playback; parallel task execution & wired outcome verification; reviewable memory extraction & semantic recall improvements | `jarvis/bgtasks.py`, `jarvis/monitors.py`, `jarvis/workflows.py`, `jarvis/agents.py`, `jarvis/memory.py` | Planned |
| **Phase 3 (Computer Automation & Sandboxing)** | Window management, accessibility-based UI inspection/controls, approved Playwright browser automation, clipboard history/pinning, screenshot organizer, document conversion, project scaffolding, OS-level extension/MCP sandboxing hardening & emergency kill switch | `jarvis/desktop.py`, `jarvis/clipboard.py`, `jarvis/browser_auto.py`, `jarvis/sentinel.py`, `rust/jarvis-core/` | Planned |
| **Phase 4 (Native Desktop & UX)** | Optional native desktop window (`pywebview`/WebView2), system tray, OS-wide global hotkeys (`Ctrl+Alt+J`, kill switch), compact floating assistant, optional start-at-login, animated assistant core with reduced-motion respect, Console/Audit/Repair/Runs/Settings workspaces | `jarvis/native_shell.py`, `jarvis/tray.py`, `jarvis/hotkeys.py`, `jarvis/ui.html` | Planned |
| **Phase 5 (Voice & Conversation)** | Streaming neural TTS, echo-cancelled barge-in, custom wake words, owner voice enrollment (non-auth), multilingual support, dictation into chosen app, standing instructions & response style controls | `jarvis/voice.py`, `jarvis/speech_engines.py` | Planned |
| **Phase 6 (Connectors & Services)** | Live PKCE OAuth callback receiver (Google Workspace, Microsoft 365), Teams/Discord/Slack/Telegram adapters, Home Assistant, Music, Flights, expanded MCP catalogue with strict capability approval | `jarvis/connectors.py`, `jarvis/mcp_client.py`, `jarvis/net.py` | Planned |
| **Phase 7 (Professional & Finance Workspace)** | Dedicated professional workspace: CSV/XLSX reconciliation & variance reports, document revision diff, requirements/UAT evidence tracker, case management, exportable reports, private local financial tracking & budgeting under `domains.py` | `jarvis/pro_workspace.py`, `jarvis/domains.py`, `jarvis/ui.html` | Planned |
| **Phase 8 (Mobile & Geospatial)** | Opt-in authenticated Android companion & iOS spec (disabled by default, never exposed to public internet), secure pairing, push/remote approvals; local-first 3D globe & public flight/satellite/maritime/weather/earthquake/wildfire/SAR workspace | `jarvis/companion.py`, `jarvis/geospatial.py`, `mobile/android/` | Planned |

---

## 2. Capability & Verification Matrix

| Feature / Area | Status | Responsible Files | Automated Tests | Security Requirements | Hardware / Credential Verification |
|---|---|---|---|---|---|
| **Baseline Core (v1.4.1)** | Implemented & verified | `jarvis/*.py`, `rust/jarvis-core/` | **342 passed, 7 skipped** (`pytest`) + **4 passed** (`cargo test`) + **67/67** Chrome HUD audit | Loopback-only, TLS 1.2+ pinned HTTPS, DPAPI, Lockdown, Sentinel, injection fencing | Verified on Windows 10 (i7-10875H, 31.86 GB RAM, Quadro RTX 5000 16 GB) |
| **Real-Time System Vitals & Processes** | Implemented & verified on Windows 10 | `jarvis/telemetry.py`, `jarvis/webui.py`, `jarvis/__main__.py` | `tests/test_nextgen_phase1.py` | Read-only local telemetry; no external transmission; bounded ring buffer | Live Windows 10 verified: 31.86 GB RAM, Quadro RTX 5000 16.0 GB VRAM @ 63.5°C, 718.8 GB free disk, 8 top processes |
| **8+ AI Provider Registry, Health, Complexity & Cost** | Implemented & verified (local/fixtures) | `jarvis/providers.py`, `jarvis/cloudprovider.py`, `jarvis/net.py` | `tests/test_nextgen_phase1.py`, `tests/test_full_integration.py` | Fail-closed `net.py` allowlist; DPAPI keys; zero silent cloud fallback; `privacy_mode="local"` hard block | Local discovery + fixture tests pass; live cloud API keys require user credentials |
| **Policy-Enforced Fast-Path** | Implemented & verified | `jarvis/fastpath.py`, `jarvis/brain.py`, `jarvis/skills.py` | `tests/test_nextgen_phase1.py` | Every fast-path command executes via `skills.run()` with Lockdown, permission checks, confirmation & audit | Verified locally without LLM (`what is 12 * 14` -> `168`) |
| **T0–T3 Risk Tiers, Dry-Run, Stale-Target & Undo Journal** | Implemented & verified | `jarvis/skills.py`, `jarvis/undo.py`, `jarvis/secure.py` | `tests/test_nextgen_phase1.py` | T2/T3 never bypass confirmation; file `stat()` verified before & after approval; undo journal redacted | Verified locally |
| **Background Task Engine, Monitors & Macros** | Phase 2 (planned) | `jarvis/bgtasks.py`, `jarvis/monitors.py` | Planned | Checkpoints persisted in SQLite; cancellable; no autonomous T2/T3 execution | Local verification |
| **Desktop Automation, Playwright & Sandboxing** | Phase 3 (planned) | `jarvis/desktop.py`, `jarvis/browser_auto.py` | Planned | Explicit approval for UI/browser writes; allowlisted URLs; least-privilege process isolation | Windows/Linux/macOS verification |
| **Native Desktop Shell, Tray, Hotkeys & Floating Mode** | Phase 4 (planned) | `jarvis/native_shell.py`, `jarvis/tray.py`, `jarvis/hotkeys.py` | Planned | Global kill switch (`Ctrl+Alt+Backspace`); hide-on-close; preserves browser HUD & accessibility | Windows/macOS desktop verification |
| **Voice Pipeline (Barge-In, Enrollment, Multilingual)** | Phase 5 (planned) | `jarvis/voice.py` | Planned | Voiceprint is **never** authentication for sensitive actions; no raw audio persisted | Real mic/speaker verification |
| **Connectors (Google, M365, Teams, Discord, Slack, HA, etc.)** | Phase 6 (planned) | `jarvis/connectors.py` | Planned | Official OAuth/APIs only; read/write scope separation; DPAPI tokens; never assume ChatGPT sub = API | User OAuth credentials required |
| **Professional & Finance Workspace** | Phase 7 (planned) | `jarvis/pro_workspace.py`, `jarvis/domains.py` | Planned | Private local storage, encryption where appropriate, explicit domain consent, no unauthorized brokerage writes | Local CSV/XLSX/doc verification |
| **Mobile Companion & Geospatial 3D Globe** | Phase 8 (planned) | `jarvis/companion.py`, `jarvis/geospatial.py` | Planned | Remote access **disabled by default**; never expose to public internet; public geospatial feeds only | Android device + network tests |

---

## 3. Known Limitations & Release Readiness

- **Stable Release:** `v1.4.1` (`3f930ec`) remains the verified stable release.
- **Not Yet Verified on Hardware:** Ollama live inference, physical microphone/speaker `voice-check`, Tesseract OCR binary, Project NOMAD server, Authenticode code signing.
- **Credentials Required for Live Tests:** OpenAI, Anthropic, Gemini, NVIDIA NIM, OpenRouter, Groq, Brave Search, GitHub PAT, Google/Microsoft OAuth Client IDs, Telegram/Discord/Slack/Home Assistant tokens.
- **Release Readiness Gate:** Every phase requires passing Python `pytest`, Rust `cargo test`, `scripts/hud_control_audit.py` (when UI changes), `compileall`, JS syntax check, and updated tracker evidence before PR merge.
