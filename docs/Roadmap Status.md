# Jarvis 44-Item Roadmap Audit Status: November 27, 2026

This audits all 44 IDs from [Master Development Plan](Master%20Development%20Plan.md) after reconciling PR #36 through PR #41 (`655d115`) and completing the `feature/jarvis-full-integration` pass.

Status classifications used:
- **Implemented and verified**: Code present and verified against real local execution / Windows 10 host / Chrome HUD audit / Rust tests.
- **Implemented but requires real-world verification**: Code and automated fixture/unit tests pass, but physical audio hardware, live Ollama models, or live external accounts remain unverified.
- **Partially implemented**: Meaningful real slice implemented and tested, with clearly scoped remaining work.
- **Not implemented**: Not yet built.
- **Blocked by external requirements**: Cannot be completed without external credentials, signing certificates, or hardware.

| ID | Capability | Status | Actual scope and remaining work |
|---|---|---|---|
| V01 | Real microphone, transcription, TTS diagnostic | Implemented but requires real-world verification | `voice-check` diagnostic and audio device inventory (`voice.audio_devices()`); physical microphone capture and audible speaker check on user hardware remain. |
| V02 | Follow-ups without repeating wake word | Implemented but requires real-world verification | Follow-up window and Setup controls; real room conversation flow remains to test on hardware. |
| V03 | Interrupt speech by voice | Not implemented | Reliable spoken barge-in while audio plays requires acoustic echo cancellation and hardware testing; Stop/Escape hotkey remains the reliable interrupt path. |
| V04 | Push to talk and system tray hotkey | Partially implemented | Focused-HUD Hold-to-record + `Ctrl+Shift+Space` + live mic-level meter implemented; OS-wide global hotkey and native tray remain. |
| V05 | Dictation into chosen application | Partially implemented | Editable local transcript preview, clipboard copy, and safe Use-in-message implemented; direct injection into external Windows apps remains. |
| V06 | Voice engine and British voice picker | Implemented but requires real-world verification | Installed voice inventory, British voice detection (`is_british_voice`), separate Jarvis/TUKI named voices, and WPM speech speed controls verified on Windows 10 (`David`, `Zira` detected); installing a UK Windows/Piper voice and testing audible quality remain. |
| V07 | Spoken daily digest | Partially implemented | Configurable briefing time, replay, mute, and saved RSS subscription opt-in flag implemented; live connected-feed digest synthesis and speaker playback remain. |
| V08 | Privacy and room context controls | Implemented but requires real-world verification | Temporary context limits, manual-only mode, pause clearing, and temporary/ephemeral chat toggle implemented; real microphone stream verification remains. |
| V09 | Responsive conversational latency | Partially implemented | Ollama streaming, optional loopback SSE streaming, and response/first-token timing metrics implemented; live target-hardware latency tuning remains. |
| C01 | Account connection center | Partially implemented | Unified built-in status, OAuth PKCE status, cloud provider status, read/write scope badges, and local disconnect/revocation implemented; live browser OAuth callback token exchange remains. |
| C02 | Google calendar, email, tasks, Drive | Blocked by external requirements | PKCE OAuth 2.0 scaffolding (`connectors.py`) with read-only vs write scope separation implemented; live Google Cloud OAuth client ID and account sign-in required for API testing. |
| C03 | Outlook and Microsoft 365 | Blocked by external requirements | Mail-app drafting + PKCE OAuth 2.0 scaffolding (`connectors.py`) with read-only vs write scope separation implemented; Azure App client ID and account sign-in required for live API testing. |
| C04 | GitHub repository read and issues | Implemented but requires real-world verification | Approved repo/README read (`/repo`), open issues (`/issues`), issue/comments (`/issue`), explicit drafted issue creation (`/new-issue`), open pull requests (`/prs`), and file upload (`/upload`) implemented and fixture-tested; real GitHub token scopes and Git push/PR creation remain. |
| C05 | Weather, RSS and news | Implemented but requires real-world verification | Approved manual RSS/Atom reads (`/feed`), saved HTTPS feed subscriptions (`/api/feeds`), and NWS US coordinate forecasts (`/weather`) implemented with fixture/security tests; live publisher/NWS verification and automated polling remain. |
| C06 | Discord, Teams or Slack | Not implemented | Messaging platform adapters deferred pending explicit authorization and threat review. |
| C07 | MCP client with server permission screen | Implemented and verified | Pure-stdlib local stdio JSON-RPC 2.0 MCP client (`mcp_client.py`) with disabled-by-default registration, exact capability approval, shell rejection, timeout/size limits, injection fencing, HUD panel, and real local subprocess tests. Remote HTTP/SSE MCP remains future work. |
| C08 | Optional smart-home and music adapters | Not implemented | Deferred to Gate 5 optional expansions. |
| C09 | Mobile access | Partially implemented | Phone-width (390 px) responsive loopback HUD verified in Chrome; authenticated LAN/VPN companion service intentionally not exposed automatically. |
| A01 | User-defined recurring checks | Partially implemented | Daily local-document checks with pause/resume/delete and change-only notifications verified; recurring external checks remain planned. |
| A02 | Reusable workflows | Implemented and verified | Resumable deterministic local workflows supporting 8 read-only step kinds (`documents`, `schedule`, `tasks`, `behind`, `calculate`, `reminders`, `notes`, `memory`) with checkpoints, Stop/resume, JSON export, and deletion. Effectful/external steps remain planned. |
| A03 | Specialist agents | Implemented but requires real-world verification | Jarvis/TUKI routing + 6 specialist profiles (`jarvis`, `tuki`, `researcher`, `coder`, `planner`, `reviewer`) with memory scopes and step budgets (`agents.py`) + Research and Cybersecurity modes; real model quality remains to verify. |
| A04 | Long-running tasks and progress | Partially implemented | Persisted file-job journals and checkpointed resumable workflows verified; long-running multi-turn autonomous agent jobs remain planned. |
| A05 | Agent handoff and delegation | Implemented but requires real-world verification | Bounded Jarvis + TUKI cooperative independent review (`assistant="both"` and `/review`) with recursion depth guard (`MAX_DELEGATION_DEPTH = 2`), trace recording, cancellation, and preserved human confirmations; live model quality remains to verify. |
| R01 | Indexed knowledge base | Implemented and verified | Opt-in SQLite FTS5 local document index with incremental refresh, deletion cleanup, and removal when disabled; tested on Windows 10. |
| R02 | Research across files and web pages | Implemented but requires real-world verification | `/research-docs`, `/research-all`, `/check`, `/read`, and dedicated Research mode prompting (verified facts vs assumptions, contradiction flags); real model citation quality remains to verify. |
| R03 | Project knowledge spaces | Implemented and verified | SQLite `projects` table, `/api/projects`, project-scoped conversations and remembered facts implemented and tested. |
| R04 | Memory provenance and expiry | Implemented and verified | Fact origin/date, editing, forgetting, expiry, duplicate detection/deduplication, redacted JSON import/export, temporary chat mode, and transactional backup/restore verified on Windows 10. |
| R05 | Image, screen and PDF understanding | Implemented but requires real-world verification | Local vision image lookup, user-chosen screen still capture, optional Tesseract OCR, and in-memory bounded local document/PDF preview (`/api/documents/preview`); real vision model & Tesseract Windows testing remain. |
| D01 | Open a selected Git repository for coding | Implemented and verified | Explicit local Git repository grant, `.git` isolation, read-only `/git-status`, scoped diffs/apply/undo, and approved test/build runs verified against real local Git repos on Windows 10. |
| D02 | Isolated coding worktrees | Implemented and verified | `coder.create_worktree` and `coder.remove_worktree` verified against real local Git repositories on Windows 10 with sibling-folder isolation and dirty-worktree protection. |
| D03 | Test failure investigation | Implemented but requires real-world verification | Read-only `/investigate-tests` failure extraction and `/fix-tests` repair preview implemented and tested; real-project model repair accuracy remains to verify. |
| D04 | Multi-agent coding panes | Not implemented | Deferred until live single-workspace coding model benchmarks are established. |
| M01 | Model selection and memory budget UI | Implemented and verified | Real hardware detection (`hardware.py` — verified on i7-10875H / 31.86 GB RAM / Quadro RTX 5000 16 GB), honest profile recommendations, and Ollama role inventory/selection; live Ollama timings remain. |
| M02 | More local model providers | Implemented but requires real-world verification | Loopback OpenAI-compatible provider with completed replies, strict tool validation, optional SSE streaming, and DPAPI Bearer auth verified over real loopback HTTP fixtures; live llama.cpp/LM Studio verification remains. |
| M03 | Optional cloud model fallback | Implemented but requires real-world verification | Opt-in per-request-consented cloud adapter (`cloudprovider.py` for OpenAI, Anthropic, Gemini) with DPAPI keys, fail-closed allowlist, zero silent fallback, and explicit `confirm cloud` approval; real API key verification remains. |
| M04 | Performance and quality evaluations | Partially implemented | Benchmark harness (`scripts/benchmark.py`) and hardware inspector exist; live Ollama model benchmarks on 8 GB and GPU hardware remain blocked until Ollama is installed. |
| S01 | Curated skill gallery | Partially implemented | Approved extension manifest discovery, permission approval, out-of-process runner, and test runner verified; remote signed skill gallery remains planned. |
| S02 | Permissions that enforce scope | Partially implemented | Sentinel defensive posture audit (`sentinel.py`), fail-closed `net.py`, Lockdown, Finance/Health domain guards (`domains.py`), and Rust policy verifier (`rust/jarvis-core`) verified; OS AppContainer/VM sandboxing for extensions remains planned. |
| S03 | Desktop/browser actions | Partially implemented | Approved non-shell app launch and user-chosen browser screen still verified; broader desktop/browser automation remains deferred. |
| S04 | Activity and audit timeline | Implemented and verified | Redacted local activity timeline, undo hints, Sentinel blocked-event summaries, agent traces, and Rust `jarvis-core audit` log verifier tested on Windows 10. |
| S05 | Installer signing and native package | Blocked by external requirements | Windows `install.ps1` (fixed for Windows PowerShell 5.1 & Python 3.15), `upgrade.ps1` rollback, v1.1.1/v1.2.1 upgrade paths, and reproducible source ZIP verified on Windows 10; Authenticode code signing and signed MSI/MSIX require a signing certificate. |
| U01 | Compact floating voice view | Partially implemented | Saved Compact browser view and glance-private Ambient Intelligence view verified in Chrome; native OS tray/always-on-top widget remains. |
| U02 | Accessibility and onboarding | Partially implemented | Setup wizard, 6 contrast-checked themes, focus outlines, skip link, reduced motion, and 390 px responsive layout verified in Chrome; manual NVDA/Narrator screen-reader pass remains. |
| U03 | Task artifacts and export | Implemented and verified | Workflow JSON export/deletion, memory JSON export/import, code diffs, and local image exports verified. |

## Broader Phase 2 & Phase 13 Notes

- **Rust Foundation**: Zero-dependency `rust/jarvis-core` crate added, compiled, and unit-tested (`cargo test`: 4/4 passed) on Windows 10.
- **Sentinel & NOMAD**: Defensive local Sentinel posture audit added (`python -m jarvis security-audit`, `/api/security`, HUD panel); existing NOMAD integration preserved.
- **Finance & Health (Phase 13)**: Foundational fail-closed permission boundaries added (`jarvis/domains.py`); no real banking or medical accounts connected.

See [Development Tracker](Development%20Tracker.md), [Architecture](Architecture.md), [Security Model](Security%20Model.md), [Capabilities](Capabilities.md), and [Engineering Handoff](Engineering%20Handoff.md).
