# Jarvis Engineering Handoff

Date: November 27, 2026
Branch: `feature/jarvis-full-integration`

## 1. Starting Git Commit
- `main`: `2bbc58499ae9f766dd4d8469c366a3d86c82c2cc` (PR #35)
- Stacked PR #41 tip (starting base of `feature/jarvis-full-integration`): `655d115599b2f8a4438b7dc17711647c1c3204bb`

## 2. Ending Git Commit
- Branch: `feature/jarvis-full-integration`
- Feature & Rust commits:
  - `c3d030f` — Add hardware advisor, multi-agent review, MCP client, connectors, worktrees, and Sentinel audit
  - `ea6609a` — Upgrade HUD controls, fix Windows PowerShell 5.1 installer and 390px layout, expand Chrome audit
  - `0d94867` — Add zero-dependency Rust jarvis-core policy and audit verifier crate
  - `fadd14d` — Update roadmap audit, tracker, architecture, security docs, Phase 2 captures, and handoff (followed by final commit recording SHAs)

## 3. Branches and Pull Requests Reviewed
- `main` (`2bbc584`)
- PR #22 (`phase-2-design-references`, `3c41158`) — design concept docs already integrated in PR #39.
- PR #36 (`feature/voice-inventory`, `d15728d`) — voice picker already integrated and refined in PR #37 and PR #41.
- PR #37 (`feature/deliberate-voice-and-workflows`, `63bf650`) — hold-to-record, compact HUD, resumable workflows.
- PR #38 (`feature/workspace-views-and-github`, `8b5847f`) — Classic/Command Center/Ambient views, GitHub issues.
- PR #39 (`feature/local-chat-provider`, `fe60a5c`) — loopback OpenAI-compatible provider, design concepts restored.
- PR #40 (`feature/approved-rss-feeds`, `0d5d8fd`) — manual RSS/Atom and NWS weather, 44-item roadmap status.
- PR #41 (`fix/voice-picker-reload`, `655d115`) — voice reload preservation, UTF-16 NUL feed rejection, packaged doc link tests.
- Reference repo reviewed: `https://github.com/open-jarvis/OpenJarvis` (`8b07c88`, Apache 2.0) — architectural inspiration only; zero third-party code copied.

## 4. Features Completed
- **Hardware detection & recommendations (`jarvis/hardware.py`, M01)**: Real CPU, RAM, disk, and NVIDIA GPU/VRAM detection with honest profile/model recommendations exposed via `python -m jarvis doctor`, `/api/hardware`, and HUD Setup.
- **Local provider SSE streaming & DPAPI Bearer auth (`jarvis/localprovider.py`, M02)**: Bounded loopback SSE streaming and optional encrypted Bearer token support.
- **Optional per-request-consented cloud AI provider (`jarvis/cloudprovider.py`, M03)**: OpenAI, Anthropic, and Gemini single-prompt adapter with DPAPI keys, fail-closed `net.py` allowlist, zero silent fallback, and mandatory `confirm cloud` approval.
- **Specialist agents & Jarvis + TUKI cooperation (`jarvis/agents.py`, A03, A05)**: 6 specialist profiles, `assistant="both"` and `/review` independent review, recursion depth limit (`MAX_DELEGATION_DEPTH = 2`), trace tracking, and Research/Cybersecurity workspace modes.
- **Voice enhancements (`jarvis/voice.py`, V04, V06, V08)**: Audio input/output device inventory (`/api/audio-devices`), British voice detection (`is_british_voice`), Jarvis/TUKI WPM speed settings, and throttled real-time `mic_level` indicator.
- **Memory, conversations, projects & local preview (`jarvis/memory.py`, R03, R04, R05)**: Named conversations (`/api/conversations`), temporary/ephemeral chat toggle (`Temp chat`), project knowledge spaces (`/api/projects`), duplicate fact detection/deduplication, redacted JSON fact import, and bounded in-memory local document/PDF preview (`/api/documents/preview`).
- **Connectors, GitHub PRs, RSS subscriptions & local MCP (`jarvis/connectors.py`, `jarvis/mcp_client.py`, `jarvis/online.py`, C01-C05, C07)**: Approved GitHub PR reads (`/prs`), saved HTTPS RSS/Atom subscriptions (`/api/feeds`), PKCE OAuth 2.0 scaffolding for Google Workspace & Microsoft 365, and pure-stdlib stdio JSON-RPC 2.0 MCP client with per-server capability approval, shell rejection, and prompt-injection fencing.
- **Coding Git status & isolated worktrees (`jarvis/coder.py`, D01, D02)**: Read-only `/git-status` and isolated sibling Git worktree create/remove.
- **Sentinel local security audit, Finance/Health boundaries & Rust foundation (`jarvis/sentinel.py`, `jarvis/domains.py`, `rust/jarvis-core/`)**: Defensive security posture auditor (`python -m jarvis security-audit`, `/api/security`, HUD Sentinel panel), fail-closed Finance/Health domain guards, and zero-dependency native Rust policy/audit verifier (`cargo test`).

## 5. Features Improved
- Extended local resumable workflows (`jarvis/workflows.py`) with `reminders`, `notes`, and `memory` steps.
- Updated `jarvis/ui.html` with live mic meter, Temp chat toggle, Sentinel & MCP panel, Hardware & Audio device inspection, Conversations switcher, duplicate cleanup, document preview, Research/Cybersecurity modes, and Jarvis+TUKI review selection while maintaining 390 px responsive layout and preserving all legacy themes and views.
- Updated `scripts/hud_control_audit.py` for native Windows + Linux execution and added Sentinel, MCP, Hardware, and Temp chat browser checks.

## 6. Bugs Discovered and Fixed
1. **Windows `install.ps1` failure under Windows PowerShell 5.1 when Python 3.12 is absent**: `& py -3.12` raised a terminating `NativeCommandError` under `$ErrorActionPreference = "Stop"`. Fixed by temporarily relaxing preference around the probe so `install.ps1` falls back cleanly to `python -m venv .venv`.
2. **Windows `setupwizard.py` & `config.py` atomic file replacement `WinError 5` race**: Concurrent HUD polling (`load_state()`) vs download progress (`save_state()`) caused `PermissionError` on Windows `os.replace()`. Fixed with `_LOCK` synchronization and bounded `PermissionError` retry loops.
3. **Windows `webui.py` HTTP 403 `WinError 10053` TCP RST**: Returning 403 on `do_POST` without draining small unauthenticated bodies caused TCP resets on Windows loopback sockets. Fixed by safely draining up to 4 KiB before sending 403.
4. **Windows installer/updater test runner incompatibility**: `tests/test_release.py` and `tests/test_upgrade_paths.py` hardcoded `pwsh` (PowerShell 7), failing on standard Windows 10/11 machines with Windows PowerShell 5.1. Fixed with `pwsh` -> `powershell` fallback.
5. **Phone-width layout overflow (7 px)**: Fixed input/select sizing and button wrapping in `jarvis/ui.html`.
6. **Voice event payload shape**: Changed `mic_level` SSE event to emit a dict (`{"level": ...}`) matching existing listener event consumers.

## 7. Security Findings and Fixes
- Verified all new `/api/*` endpoints enforce `Host`, `Origin`, and `X-Jarvis-Key` checks via automated 403 tests.
- Verified cloud providers are excluded from `net.py` allowlist unless explicitly enabled and configured, and never exposed as automatic model tools.
- Verified MCP client rejects shell/script hosts (`cmd.exe`, `powershell.exe`, `bash`, `sh`), requires exact capability approval, enforces timeouts/output bounds, and fences returned text against prompt injection.
- Verified Finance & Health domain guards fail closed and prohibit writes.
- Verified `python -m jarvis security-audit` passes all 9 local defensive checks on Windows 10.

## 8. Files Added or Modified
- Added: `jarvis/hardware.py`, `jarvis/cloudprovider.py`, `jarvis/agents.py`, `jarvis/mcp_client.py`, `jarvis/connectors.py`, `jarvis/sentinel.py`, `jarvis/domains.py`, `rust/jarvis-core/Cargo.toml`, `rust/jarvis-core/src/lib.rs`, `rust/jarvis-core/src/main.rs`, `tests/test_full_integration.py`, `docs/Development Tracker.md`, `docs/Architecture.md`, `docs/Security Model.md`, `docs/Third Party Attribution.md`, `docs/Engineering Handoff.md`
- Modified: `jarvis/config.py`, `jarvis/assistants.py`, `jarvis/net.py`, `jarvis/secure.py`, `jarvis/voice.py`, `jarvis/memory.py`, `jarvis/localprovider.py`, `jarvis/online.py`, `jarvis/coder.py`, `jarvis/workflows.py`, `jarvis/skills.py`, `jarvis/brain.py`, `jarvis/__main__.py`, `jarvis/webui.py`, `jarvis/setupwizard.py`, `jarvis/ui.html`, `install.ps1`, `scripts/hud_control_audit.py`, `scripts/package_release.py`, `tests/test_release.py`, `tests/test_upgrade_paths.py`, `.gitignore`, `AGENTS.md`, `README.md`, `CHANGELOG.md`, `docs/Capabilities.md`, `docs/Roadmap Status.md`

## 9. Test Commands and Actual Results
(Verified on Windows 10 Home 10.0.19045, Python 3.15.2, Rust 1.100.0-x86_64-pc-windows-msvc, Google Chrome)
- `.\.venv\Scripts\python.exe -m pytest -q`: **340 passed, 0 failed, 7 platform-specific skipped** (3 Windows symlink privilege skips, 1 Tesseract-not-installed skip, 3 POSIX `sleep` skips). Includes all Windows `install.ps1`, `upgrade.ps1`, v1.1.1/v1.2.1 upgrade/rollback, and native DPAPI tests.
- `$env:JARVIS_CHROME="C:\Program Files\Google\Chrome\Application\chrome.exe"; .\.venv\Scripts\python.exe -m scripts.hud_control_audit`: **65 of 65 checks passed** (including 390 px phone layout with 0 px overflow, Command Center, Ambient, Sentinel/MCP, Hardware, Temp chat, Windows App actions, Extensions, Setup Wizard, and Restart persistence).
- `cargo +1.100.0-x86_64-pc-windows-msvc test --manifest-path rust/jarvis-core/Cargo.toml`: **4 passed, 0 failed**.
- `.\.venv\Scripts\python.exe -m compileall -q jarvis scripts tests`: exit 0.
- `node --check` on extracted `jarvis/ui.html` JavaScript: exit 0.
- PowerShell AST syntax checks (`install.ps1`, `upgrade.ps1`, `scripts/check_defender.ps1`): all OK.
- `.\.venv\Scripts\python.exe -m scripts.package_release`: reproducible `dist/Jarvis1.3.0.zip` + `SHA256SUMS.txt` built and verified (all packaged documentation links resolve inside the ZIP).

## 10. Hardware Verification Results
- **Host**: Windows 10 Home (10.0.19045), Intel Core i7-10875H (8C/16T), 31.86 GB RAM, NVIDIA Quadro RTX 5000 Max-Q (16.0 GB VRAM, Driver 621.24).
- **Windows SAPI Voices Detected Live**: `Microsoft David Desktop - English (United States)`, `Microsoft Zira Desktop - English (United States)` (no British SAPI voice installed on host).
- **Windows Installer/Updater/Rollback**: Real PowerShell execution of `install.ps1`, `upgrade.ps1`, and v1.1.1/v1.2.1 upgrade + rollback paths verified on Windows 10.
- **Not verified on hardware (absent on test host)**: Ollama live inference, `faster-whisper` + `sounddevice` physical microphone capture/playback, Tesseract OCR binary, Project NOMAD server.

## 11. Connector Verification Results
- Built-in local config/status & credential removal: verified via unit and HUD tests.
- GitHub repo/issues/PRs/uploads, Brave search, RSS/Atom, NWS weather, Cloud AI providers: verified with mocked/fixture HTTP responses and strict allowlist/confirmation tests; live account tokens not present.
- Google Workspace & Microsoft 365: PKCE OAuth 2.0 URL generation, loopback redirect check, read/write scope separation, and disconnect tested; live OAuth requires user-provided client IDs.
- Local stdio MCP client: verified end-to-end against a real local Python JSON-RPC 2.0 subprocess server.

## 12. Remaining Limitations
- No Authenticode code signing or native MSI/MSIX package yet.
- Extensions and local stdio MCP servers execute as the local Windows user (declared permissions, not OS AppContainer/VM sandboxed).
- No echo-cancelled spoken barge-in while Jarvis is speaking (`V03`).
- Global OS-wide hotkey and native system tray icon remain planned (`V04`, `U01`).

## 13. Features Requiring Credentials
- Google Workspace OAuth (Drive, Calendar, Gmail) — Google Cloud Desktop OAuth Client ID.
- Microsoft 365 OAuth (Outlook, OneDrive, Teams) — Azure App Registration Client ID.
- Brave Search API key, GitHub personal access token, Canvas ICS feed URL, SMTP app password, optional Cloud AI API keys (OpenAI/Anthropic/Gemini).

## 14. Features Requiring Additional Hardware / Installed Services
- Ollama + local models (`qwen3:4b`, `qwen3:8b`, `qwen2.5-coder:7b`, `nomic-embed-text`, `gemma3:4b`) for live inference and 8 GB vs GPU benchmarks (`M04`).
- Physical microphone + speakers + `faster-whisper` / `sounddevice` + British Windows SAPI voice pack or Piper `.onnx` model (`V01`, `V02`, `V06`).
- Optional Tesseract OCR binary and Project NOMAD server.

## 15. Remaining Development Tasks
1. Install Ollama locally and run `python -m scripts.benchmark --coding` on both 8 GB profile and RTX GPU hardware; publish real results in `docs/Benchmarks.md`.
2. Run `python -m jarvis voice-check` with a real microphone/speakers and complete a manual screen-reader (NVDA/Narrator) accessibility review.
3. Implement live OAuth localhost callback receiver and Google/Microsoft API readers once the owner registers OAuth client IDs.
4. Set up Authenticode code signing and consider MSI/MSIX packaging for signed Windows releases.
5. Plan and authorize the separate future Finance/Health expansion phase on top of `jarvis/domains.py`.

## 16. GitHub Commit and Pull Request Links
- Primary repository: https://github.com/test3457890/Jarvis
- Stacked PRs reviewed: #36 through #41 (open on GitHub when cloned; `gh` CLI is not authenticated in this environment so pushing/creating a PR requires user GitHub authentication).
- Local branch ready to push: `feature/jarvis-full-integration`

## 17. Instructions for Next ChatGPT or Claude Session
1. Check out `feature/jarvis-full-integration` (or merge PRs #37–#41 into `main` first, then rebase/merge this branch).
2. Review `docs/Development Tracker.md` and `docs/Roadmap Status.md` for exact 44-item status classifications.
3. Run `.\.venv\Scripts\python.exe -m pytest -q`, `cargo test --manifest-path rust/jarvis-core/Cargo.toml`, and `python -m scripts.hud_control_audit` before making changes.
4. Preserve all existing security boundaries (`127.0.0.1` binding, `net.py` fail-closed allowlist, `skills.py` risky confirmations, Lockdown, DPAPI secrets, prompt-injection fencing) and never fabricate hardware or live account verification results.
