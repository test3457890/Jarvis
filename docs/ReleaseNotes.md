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
