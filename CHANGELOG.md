# Changelog

## 2.0.0-rc1 (Release Candidate — Pre-Release)

- **Live System Vitals & Dedicated Workspaces**: Real-time CPU, RAM, NVIDIA GPU/VRAM/temperature, disk, battery, network throughput, SVG sparklines, top 8 processes (`jarvis/telemetry.py`), and dedicated Console, Vitals, Audit, Repair, Runs, Professional, and Settings workspaces preserving all 6 legacy themes and 3 legacy views.
- **9+ AI Providers, Capabilities & Controlled Local Failover**: Ollama, LM Studio, local OpenAI-compatible, OpenAI, Anthropic, Google Gemini, NVIDIA NIM, OpenRouter, Groq, and Custom HTTPS OpenAI-compatible (`jarvis/providers.py`, `jarvis/cloudprovider.py`) with `privacy_mode`, model capability metadata, USD cost estimation, local-only failover (zero silent cloud fallback), and policy-enforced audited Fast-Path (`jarvis/fastpath.py`).
- **T0–T3 Risk Tiers, Dry-Run, Stale-Target Guard, Undo Journal & Rust Core**: Explicit T0–T3 risk classification, `dry_run()` inspector, file `stat()` stale-target blocking, unified Undo Journal, secret redaction (`jarvis/secure.py`), and expanded Rust `jarvis-core` sensitive-path & shell risk verifier (`5/5` tests).
- **Background Tasks, Monitors & Macros**: SQLite checkpointed background tasks with startup crash recovery, bounded parallel T0 execution, wired outcome verification (`jarvis/bgtasks.py`), telemetry Condition Monitors (`jarvis/monitors.py`), policy-enforced Macros (`jarvis/macros.py`), and reviewable memory extraction (`jarvis/memextract.py`).
- **Desktop Automation, Route-Guarded Playwright & Native Shell**: Win32 window controls & hotkey policy (`jarvis/desktop.py`), redacted Clipboard History (`jarvis/clipboard.py`), route-guarded Playwright Chromium session blocking subresource/redirect SSRF (`jarvis/browser_auto.py`), Windows System Tray (`jarvis/tray.py`), global hotkeys & Emergency Kill Switch (`jarvis/hotkeys.py`), and `--native`/`--floating`/`--tray`/`--hotkeys` CLI support (`jarvis/native_shell.py`).
- **Real Voice Pipeline Integration**: `EchoGuard` acoustic self-echo suppression + spoken barge-in (`"Jarvis stop"`) and `stream_sentences()` chunker wired directly into `App` (`jarvis/__main__.py`, `jarvis/voice_profile.py`), plus strictly non-authentication voice enrollment and injection-screened standing instructions.
- **External Connectors, Professional/Finance & Geospatial 3D Globe**: OAuth 2.0 PKCE exchange/refresh and official API operations (`jarvis/service_adapters.py`), pure-stdlib hardened `.xlsx`/CSV variance comparator, doc diff, UAT & case tracker, fail-closed local finance analytics (`jarvis/pro_workspace.py`), and interactive offline 3D orthographic globe + SAR grid planner (`jarvis/geospatial.py`).
- **Opt-In Mobile Companion & Android APK CI**: Hardened pairing (disabled by default, 120s single-use code, 5/300s rate limit, SHA-256 hashed tokens with TTL, revocation, T0 read-only allowlist), Kotlin + Jetpack Compose Android app (`mobile/android/`, AndroidX enabled, loopback-only cleartext policy, `EncryptedSharedPreferences`), and pinned-SHA GitHub Actions APK CI workflow (verified passing).

## 1.4.1

- Enforced `ssl.TLSVersion.TLSv1_2` minimum in `jarvis/net.py` (`PinnedHTTPS.connect`).

## 1.4.0

- **Hardware detection & recommendations (`M01`)**: Inspect real CPU, RAM, disk, and NVIDIA GPU/VRAM (`jarvis/hardware.py`, `/api/hardware`, `python -m jarvis doctor`, and HUD Setup panel) with honest profile recommendations.
- **Local provider SSE streaming & Bearer auth (`M02`)**: Optional loopback SSE text streaming and DPAPI-stored Bearer token support in `jarvis/localprovider.py` and the HUD provider form.
- **Optional per-request cloud AI provider (`M03`)**: Opt-in single-prompt cloud adapter (`jarvis/cloudprovider.py` for OpenAI, Anthropic, Gemini) with DPAPI API keys, fail-closed allowlist, zero silent fallback, and mandatory `confirm cloud` approval.
- **TUKI & Multi-Agent collaboration (`A03`, `A05`)**: Specialist profiles (`jarvis/agents.py`), Jarvis + TUKI cooperative independent review (`assistant="both"` and `/review`), recursion depth guard (`MAX_DELEGATION_DEPTH = 2`), and dedicated Research and Cybersecurity workspace modes.
- **Voice assistant enhancements (`V04`, `V06`, `V08`)**: Audio input/output device inventory (`/api/audio-devices`) and microphone selector, British voice detection, Jarvis/TUKI WPM speech speed controls, and real-time `mic_level` activity meter.
- **Persistent memory & project knowledge spaces (`R03`, `R04`)**: Named conversations (`/api/conversations`) with history search, temporary/ephemeral chat toggle (`Temp chat`), project knowledge spaces (`/api/projects`) with active-project recall scoping, duplicate fact detection/deduplication, and redacted JSON fact import.
- **Connectors, GitHub PRs, RSS subscriptions & MCP (`C01`-`C05`, `C07`)**: Approved GitHub pull request reads (`/prs`), saved HTTPS RSS/Atom subscriptions (`/api/feeds` + HUD management), PKCE OAuth 2.0 scaffolding with read-only vs write scope separation for Google Workspace and Microsoft 365 (`jarvis/connectors.py`), and a pure-stdlib local stdio JSON-RPC 2.0 MCP client with per-server capability approval, HUD registration/discovery, and injection fencing (`jarvis/mcp_client.py`).
- **Coding Git status, isolated worktrees & local document preview (`D01`, `D02`, `R05`)**: Read-only `/git-status`, confirmed isolated sibling Git worktree create/remove (`/worktree`, `/worktree-remove`, `coder.py`), workflow run search filter, and bounded in-memory local document/PDF preview (`/api/documents/preview`).
- **Sentinel security audit, XML hardening, Finance/Health boundaries & Rust foundation (`S02`, `S04`, `S05`)**: Defensive local Sentinel posture audit (`jarvis/sentinel.py`, `python -m jarvis security-audit`, HUD Sentinel panel), NUL/DTD/ENTITY XML hardening in `jarvis/nomad.py`, fail-closed Finance/Health domain guards (`jarvis/domains.py`), and zero-dependency native Rust policy/audit crate (`rust/jarvis-core`).
- **Windows 10/11 compatibility fixes**: Fixed `install.ps1` Python 3.12 probe under Windows PowerShell 5.1 `$ErrorActionPreference = "Stop"`, atomic file-replace concurrency retries in `setupwizard.py` and `config.py`, HTTP 403 socket drain in `webui.py`, and `pwsh` -> `powershell.exe` test fallback.

- Reject NUL-containing misdecoded XML before feed parsing so alternate byte encodings cannot bypass the DTD/entity scan.

- Include the screenshot-gallery README and linked benchmark JSON in source packages, with a packaged-documentation link check.

- Preserve saved named voices while the HUD loads its installed-voice inventory. Explicit TUKI choices now take priority even if the owner chooses the same voice as Jarvis; Automatic still prefers a different voice.

- Approved manual RSS/Atom reads with bounded XML parsing, publisher links and reported dates.
- Approved NWS coordinate/forecast reads with destination confinement and validation of actual response fields.
- Keep provider settings within the phone-width layout; the regression found by the browser audit is fixed.

- Optional loopback-only chat-completions adapter with explicit configuration, bounded complete responses, validated tool IDs and existing approvals; no cloud fallback.
- Restore the three original concept images separately from actual application captures and retain legacy screenshots.

- Select Classic, Command Center and Ambient workspace views independently of mode and theme, using shared state and existing permissions.
- List/read GitHub issues and preview a manually drafted issue before publication. Destination changes invalidate approvals; ambiguous creation responses are not retried.

- Local hold-to-record with a focused-page shortcut, manual input mode, editable transcript preview, capture limits and cancellation.
- Saved compact HUD view, skip link and reduced-motion handling.
- Confirmed local workflows with fixed read tools, persisted step checkpoints, Stop/resume, JSON export and result deletion.
- Tests cover cancellation races, workflow recovery, permission enforcement, stale previews and HTTP session boundaries. Windows microphone, screen-reader and real-model verification remain outstanding.

All notable changes to Jarvis. Each release adds a section here before it is tagged.

## 1.3.0

### Voice, screen and integrations
- Fixed: elements marked hidden could still show when a layout style set `display:flex`.
- Voice: "Jarvis, stop" (or "never mind", "cancel") cancels a reply being prepared; more of
  Whisper's silence hallucinations are ignored. Jarvis still does not listen while speaking, so
  spoken interruption of playing speech is not offered.
- Screen panel: choose a window or screen in the browser's picker; Jarvis keeps one still, stops
  sharing, shows it, and sends it to the local vision model only when you select Ask. Not saved.
- Approved app actions: programs you add by full path (shells and script hosts refused), optional
  file from a selected folder, exact command preview, Confirm, Stop app actions, quick-failure reports.
- Optional local OCR with Tesseract for scanned PDFs and images, with a session cache. Off by default.
- Extensions: manifest with permissions, typed inputs and outputs, and tests; disabled until the
  user approves the exact permissions; each call in a separate process. Example in `docs/examples`.
  Declared `network_hosts` are shown for review but are not an enforced allowlist. An extension's
  tests run only after it is enabled.
- Measured document search; no persistent index needed at the current limits.

### Coding and performance
- Coding picks up to three related files as read-only context (imports, importers, tests, files named
  in the request) and lists them in the preview. `auto_context: false` turns it off.
- Coding context is sized to the performance profile: 12,000 characters on Standard, 4,096 on the
  8 GB profile (2,048-token model context). Project scans stop at 5,000 entries.
- Paths through links or junctions in the coding workspace are refused.
- New `/build` (and Build project button): `compileall` for Python, `npm run build` for Node, only
  after confirmation. Test and build timeouts are reported as no result.
- `/fix-tests` adds files named in the failure output as context.
- The last applied edit is saved, so `/undo` works after a restart and still refuses changed files.
- `scripts/benchmark.py` measures time to first sentence and peak memory, and `--coding` runs a
  three-task coding suite that asks before running generated code. No real results recorded yet.

### Control inventory and reliability
- Fixed: the HUD's approval-banner function was named `confirm`, which replaced the browser's
  `window.confirm`. Every "Are you sure?" prompt (delete a remembered fact, restore a backup, clear
  conversation history, download above the storage budget) went ahead without asking. Present since
  1.1.x. The prompts now appear, and declining keeps the data.
- New `scripts/hud_control_audit.py` drives every HUD control in Chromium and checks its real result
  (saved settings, files on disk, memory, pending approvals). It runs in CI and writes a report.
- Windows CI upgrades v1.1.1 and v1.2.1 installs with their own updaters, checks settings and data
  are untouched, then rolls back.
- Added a capability matrix (`docs/Capabilities.md`).

## 1.2.1
- Coding mode retries one patch with the model when its SEARCH text does not match or its edit format is invalid. Neither attempt writes files before preview and Apply.
- Requests selecting more than six editable files now report the limit instead of silently ignoring files.
- Added a coding guide with tested behavior and current limits. Release ZIPs now contain the screenshots referenced by the README.

## 1.2.0

### Windows installation and first launch
- `Jarvis.bat` is no longer shipped or required. `install.ps1` creates Start menu and folder shortcuts
  that start `.venv\Scripts\python.exe -m jarvis` directly. PowerShell fallback:
  `& .\.venv\Scripts\python.exe -m jarvis`.
- New first-run setup wizard in the HUD: prerequisites, Standard or 8 GB low-memory profile,
  model sizes, free disk space, a storage budget with a warning before downloads exceed it,
  voice, document folders, file-task folders, coding workspace and optional online tools.
- Model downloads resume after a failure. Choices are merged into existing settings.
- An unreadable `config.json` is kept as a copy instead of being overwritten.
- Read-only Defender diagnostic (`scripts\check_defender.ps1`) and signing notes in
  `docs/WindowsDefender.md`. The release is not code-signed.
- Windows CI runs the installer, checks the shortcut and settings, and starts the HUD.

### File tasks
- Browse, find, create folders, rename, copy, move, organise by type and delete inside folders
  you select. The Jarvis Code workspace stays separate.
- Exact step-by-step preview and confirmation, link and traversal protection, no overwrites,
  a step journal with resume, undo with change detection, and recoverable deletion into
  `.Jarvis Recycle`.

### Coding and TUKI
- Focused SEARCH/REPLACE patches, multi-file previews, project context, syntax checks without
  running code, all-or-nothing apply with rollback, multi-file undo.
- `/test` runs the detected project tests only after confirmation. `/fix-tests` sends the
  failure output back to the coding model.
- TUKI has its own voice settings and a Try TUKI voice preview, with a fallback when only one
  Windows voice is installed.
- Broader technical routing. TUKI answers state a confidence line and what was checked.

### Interface and documentation
- New High contrast, Midnight and Paper themes, with automated contrast checks.
- `AGENTS.md` contributor guide and this changelog. README updated for the shortcut and new panels.

## 1.1.1
- Release download names match the checksum manifest.
- Chat input is kept while Jarvis is busy. Browser actions are previewed.
- Claims can be compared against several approved source pages.

## 1.1.0
- Guided setup panel, low-memory profile, document search with references, remembered-fact
  controls, local backup and restore, streamed replies, Stop and Escape, approved source-page
  reading and workspace copy/move tasks with resume and undo.
