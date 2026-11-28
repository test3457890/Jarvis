# Jarvis Next Generation — Master Development Tracker

**Updated:** November 28, 2026  
**Active Branch:** `feature/jarvis-next-phase` (synchronized with `main` / `v1.4.1` security patch @ `3f930ec`)  
**Stable Release Preserved:** `v1.4.1` (remains stable until Next-Gen PRs are independently reviewed and merged)  
**Reference Inventory:** See [Reference Comparison and Inventory](Reference%20Comparison%20and%20Inventory.md), [Third Party Attribution](Third%20Party%20Attribution.md), and [Mobile Companion Architecture](Mobile%20Companion%20Architecture.md).

---

## 1. Phased Implementation Roadmap (Manageable PR Slices)

| Phase | Scope | Key Modules & Tests | Status |
|---|---|---|---|
| **Phase 0 (Prep)** | Sync `main` (`v1.4.1`) & `feature/jarvis-next-phase`, baseline tests (342 Py + 4 Rust), full AST/code inventory of `ankitjha67/JARVIS` (64 modules / 231 tools / 8 providers / 84+24 ideas) & `OpenJarvis`, license audit, Master Tracker | `docs/Reference Comparison and Inventory.md`, `docs/Third Party Attribution.md`, `docs/Development Tracker.md` | **Completed** |
| **Phase 1 (Foundation & HUD)** | Live System Vitals (`psutil` + `nvidia-smi` + SVG sparklines + top processes), 9+ AI Provider Registry (Ollama, LM Studio, Local OpenAI-compat, OpenAI, Anthropic, Gemini, NVIDIA NIM, OpenRouter, Groq, Custom HTTPS OpenAI-compat) with `privacy_mode` (`local`/`hybrid`/`cloud`), complexity tiering, USD cost estimation, **policy-enforced audited Fast-Path**, T0–T3 risk tiers, `dry_run()` inspector, stale-target `stat()` guard, Undo Journal, secret redaction, and HUD Vitals/Providers/Audit panels | `jarvis/telemetry.py`, `jarvis/providers.py`, `jarvis/fastpath.py`, `jarvis/undo.py`, `jarvis/cloudprovider.py`, `jarvis/skills.py`, `jarvis/secure.py`, `jarvis/ui.html`, `tests/test_nextgen_phase1.py` | **Completed & Verified** |
| **Phase 2 (Agents, Tasks & Memory)** | Persistent Background Task Engine with SQLite checkpoints, crash recovery (`recovered`), cancellation, parallel T0 execution & wired outcome verification; telemetry Condition Monitors; Workflow/Macro recorder & policy-enforced playback; Reviewable Memory Extraction & Daily Summary; HUD Runs/Monitors panel | `jarvis/bgtasks.py`, `jarvis/monitors.py`, `jarvis/macros.py`, `jarvis/memextract.py`, `jarvis/ui.html`, `tests/test_nextgen_phase2.py` | **Completed & Verified** |
| **Phase 3 (Computer Automation & Rust Policy)** | Redacted Clipboard History with pinning & search; Windows desktop window enumeration & confirmed focus; Screenshot organizer & tagging; Safe project scaffolding inside `code_dir`; Fail-closed Playwright public-HTTPS inspector; Rust `jarvis-core` sensitive-path & shell command risk verifier | `jarvis/clipboard.py`, `jarvis/desktop.py`, `jarvis/browser_auto.py`, `rust/jarvis-core/src/lib.rs`, `tests/test_nextgen_phase3.py` | **Completed & Verified** |
| **Phase 4 (Native Shell & Hotkeys)** | Windows global hotkeys (`Ctrl+Alt+J` summon, `Ctrl+Alt+Backspace` Emergency Kill Switch); Optional `pywebview` native desktop & compact floating window launcher (loopback-only); Opt-in HKCU start-at-login | `jarvis/hotkeys.py`, `jarvis/native_shell.py`, `tests/test_nextgen_phase4.py` | **Completed & Verified** |
| **Phase 5 (Voice & Standing Instructions)** | Non-authentication voice enrollment (numeric features only, never raw audio, `can_authorize_sensitive_action() == False`), custom wake word validation, response styles (`concise`/`balanced`/`detailed`/`executive`), multilingual preference & injection-screened standing instructions | `jarvis/voice_profile.py`, `jarvis/brain.py`, `jarvis/config.py`, `tests/test_nextgen_phase5.py` | **Completed & Verified** |
| **Phase 6 (Connectors & MCP Catalogue)** | Official API connector registry (Google Workspace, M365, Teams, Discord, Slack, GitHub, Telegram, Home Assistant, Music, Weather, Flights) with honest credential/offline/Lockdown status; fail-closed Telegram & Home Assistant guards; 10-entry curated MCP reference catalogue (never auto-enabled) | `jarvis/service_adapters.py`, `tests/test_nextgen_phase6.py` | **Completed & Verified** |
| **Phase 7 (Professional & Finance Workspace)** | CSV spreadsheet reconciliation & Markdown variance reports; Document revision unified diff; Requirements & UAT evidence tracker; Redacted Case management; Private local financial/budget summary strictly gated by `domains.check_domain_access("finance")` | `jarvis/pro_workspace.py`, `jarvis/ui.html`, `tests/test_nextgen_phase7.py` | **Completed & Verified** |
| **Phase 8 (Mobile Companion & Geospatial)** | Opt-in mobile companion pairing (`remote_companion_enabled=False` default, 120s single-use code, SHA-256 hashed tokens, instant revocation, Lockdown block); Android & iOS companion architecture spec; Offline geodesy & SAR parallel-track search-grid generator + fail-closed USGS/NASA/OpenSky/CelesTrak public feeds + HUD SVG plot | `jarvis/companion.py`, `jarvis/geospatial.py`, `docs/Mobile Companion Architecture.md`, `jarvis/ui.html`, `tests/test_nextgen_phase8.py` | **Completed & Verified** |

---

## 2. Authentic Hardware & Verification Evidence (Windows 10)
- **Host:** Windows 10 Home (10.0.19045), Intel Core i7-10875H (8C/16T), 31.86 GB RAM, NVIDIA Quadro RTX 5000 (16.0 GB VRAM, Driver 621.24).
- **Live System Vitals Verified:** `31.86 GB` RAM (`54.8%` used), `Quadro RTX 5000` `16.0 GB` VRAM @ `63.5°C`, `718.8 GB` free disk, `8` real top processes.
- **Authentic HUD Screenshots Captured:**
  - `docs/screenshots/nextgen-phase1-vitals.png`
  - `docs/screenshots/nextgen-phase8-pro-geo.png`
- **Automated Verification Suites:**
  - Python `pytest -q`: full regression + Phases 1–8 (`tests/test_nextgen_phase1.py` through `tests/test_nextgen_phase8.py`).
  - Rust `cargo test --manifest-path rust/jarvis-core/Cargo.toml`: **5 passed, 0 failed**.
  - Live Chrome HUD Control Audit (`scripts/hud_control_audit.py`): **72/72 checks** (including 390 px phone layout with 0 px overflow).
  - `compileall` and `node --check` on extracted `jarvis/ui.html` JavaScript: exit 0.

---

## 3. Features Requiring External Credentials, Hardware, or Future Owner Action
- **Live Cloud AI Providers:** User-owned API keys for OpenAI, Anthropic, Gemini, NVIDIA NIM, OpenRouter, Groq, or Custom HTTPS endpoints (DPAPI Vault).
- **Live External Connectors:** Google Cloud & Azure OAuth Client IDs, Discord/Slack/Telegram Bot tokens, GitHub PAT, Home Assistant URL + token, Brave Search API key.
- **Physical Audio / Local Inference Hardware:** Ollama + local models for live 8 GB & RTX GPU benchmarks; physical microphone/speaker `voice-check` + optional British SAPI/Piper voice pack; optional `pywebview` install for native desktop window mode; Authenticode code-signing certificate for signed Windows releases.
- **GitHub Push / PR Creation:** Local commits are cleanly staged on `feature/jarvis-next-phase`; `gh` CLI is not authenticated in this environment so pushing and opening PRs requires GitHub authentication.
