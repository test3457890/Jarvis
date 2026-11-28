Jarvis 2.0.0-rc1 (Release Candidate on `feature/jarvis-next-phase` — `v1.4.1` remains the published stable release until PR review and final CI pass).

Highlights:
- **Live System Vitals & Dedicated Workspaces**: Real-time CPU, RAM, NVIDIA GPU/VRAM/temperature, disk, battery, network throughput, SVG sparklines, top 8 processes (`jarvis/telemetry.py`), and dedicated Console, Vitals, Audit, Repair, Runs, Professional, and Settings workspaces preserving all 6 legacy themes and 3 views.
- **9+ AI Providers, Capabilities & Local Failover**: Ollama, LM Studio, local OpenAI-compatible, OpenAI, Anthropic, Google Gemini, NVIDIA NIM, OpenRouter, Groq, and Custom HTTPS OpenAI-compatible (`jarvis/providers.py`, `jarvis/cloudprovider.py`) with `privacy_mode`, capability awareness, USD cost estimation, controlled local failover (zero silent cloud fallback), and policy-enforced audited Fast-Path (`jarvis/fastpath.py`).
- **T0–T3 Security, Dry-Run, Stale-Target Guard, Undo Journal & Rust Core**: Explicit T0–T3 risk tiers, `dry_run()` inspector, file `stat()` stale-target blocking, unified Undo Journal, secret redaction (`jarvis/secure.py`), and expanded Rust `jarvis-core` sensitive-path & shell risk verification (`5/5` tests).
- **Background Tasks, Monitors & Macros**: SQLite checkpointed background tasks with startup crash recovery, bounded parallel T0 execution, wired outcome verification (`jarvis/bgtasks.py`), telemetry Condition Monitors (`jarvis/monitors.py`), policy-enforced Macros (`jarvis/macros.py`), and reviewable memory extraction (`jarvis/memextract.py`).
- **Desktop, Route-Guarded Playwright & Native Shell**: Win32 window controls & safe hotkey policy (`jarvis/desktop.py`), redacted Clipboard History (`jarvis/clipboard.py`), route-guarded Playwright Chromium session blocking subresource/redirect SSRF (`jarvis/browser_auto.py`), Windows System Tray (`jarvis/tray.py`), global hotkeys & Emergency Kill Switch (`jarvis/hotkeys.py`), and optional `pywebview` `--native` / `--floating` desktop shell (`jarvis/native_shell.py`).
- **Voice Pipeline Integration**: `EchoGuard` acoustic self-echo suppression + spoken barge-in (`"Jarvis stop"`) and `stream_sentences()` chunker wired directly into `App` (`jarvis/__main__.py`, `jarvis/voice_profile.py`), plus strictly non-authentication voice enrollment and injection-screened standing instructions.
- **External Connectors, Professional/Finance & Geospatial 3D Globe**: OAuth 2.0 PKCE exchange/refresh and official API operations (`jarvis/service_adapters.py`), pure-stdlib hardened `.xlsx`/CSV variance comparator, doc diff, UAT & case tracker, fail-closed local finance analytics (`jarvis/pro_workspace.py`), and interactive offline 3D orthographic globe + SAR grid planner (`jarvis/geospatial.py`).
- **Opt-In Mobile Companion**: Hardened pairing (disabled by default, 120s single-use code, 5/300s rate limit, SHA-256 hashed tokens with TTL, revocation, T0 read-only allowlist) paired with the Kotlin + Jetpack Compose Android app (`mobile/android/`, AndroidX enabled, cleartext restricted to loopback dev, `EncryptedSharedPreferences`) and pinned-SHA GitHub Actions APK CI workflow.

See `docs/Feature Completion Audit.md`, `docs/Development Tracker.md`, and `docs/Reference Comparison and Inventory.md` for full honest verification status.

---

Jarvis 1.4.1 is a security patch release following PR #43.

Security Fix:
- Enforced `ssl.TLSVersion.TLSv1_2` minimum in `jarvis/net.py` (`PinnedHTTPS.connect`), resolving CodeQL alert `py/insecure-protocol`.

Verify `Jarvis1.4.1.zip` with `SHA256SUMS.txt` (do not overwrite the published `v1.4.0` release archive).

---

Jarvis 1.4.0 consolidates the Phase 2 workspace and provider expansion (PRs #36-#41) with OpenJarvis-inspired local intelligence, security, and Windows reliability upgrades.

Highlights:
- Three selectable workspace views (Classic Jarvis, Command Center, Ambient Intelligence) alongside all six legacy themes, plus dedicated Research and Cybersecurity modes and Jarvis + TUKI cooperative independent review (`/review`, `assistant="both"`).
- Hardware-aware model recommendations (`jarvis/hardware.py`, `python -m jarvis doctor`, Setup panel), loopback OpenAI-compatible SSE streaming and optional DPAPI Bearer auth, and an opt-in per-request-consented cloud AI adapter (`jarvis/cloudprovider.py`, disabled by default, zero silent fallback).
- Named conversations with history search, Temporary chat mode (`Temp chat`), project knowledge spaces (`R03`), duplicate fact cleanup, redacted JSON memory import, and in-memory bounded local document/PDF preview.
- Approved RSS/Atom feed reads and saved subscriptions, NWS US coordinate weather forecasts, GitHub issues and open pull request reads (`/prs`), confirmed isolated Git coding worktrees (`/worktree`), PKCE OAuth 2.0 scaffolding for Google Workspace and Microsoft 365, and a pure-stdlib local stdio JSON-RPC 2.0 MCP client with explicit per-server capability approval and prompt-injection fencing.
- Defensive local Sentinel security posture audit (`python -m jarvis security-audit`, HUD Sentinel panel), XML DTD/entity hardening for NOMAD Kiwix feeds, fail-closed Finance/Health domain boundaries, and a zero-dependency native Rust foundation crate (`rust/jarvis-core`).
- Windows 10/11 fixes for `install.ps1` under Windows PowerShell 5.1, atomic file-replace concurrency retries, clean HTTP 403 socket draining, and 390 px mobile layout.

The release is not code-signed. Verify `Jarvis1.4.0.zip` with `SHA256SUMS.txt` (do not overwrite the published `v1.3.0` release archive). Close Jarvis before running `upgrade.ps1`. The updater replaces shipped program files only and preserves your settings, encrypted secrets, and local database. Run `install.ps1` afterwards to refresh packages.

Verified on Windows 10 (Python 3.15.2, Rust 1.100.0, Google Chrome) with automated unit, integration, Windows installer/updater/rollback, Rust, and live browser HUD control audits. Live Ollama model inference, physical microphone/speaker audio, Tesseract OCR, and live external OAuth/cloud accounts still require user installation or credentials. See `CHANGELOG.md`, `docs/Capabilities.md`, `docs/Roadmap Status.md`, and `docs/Engineering Handoff.md`.
