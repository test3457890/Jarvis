# Changelog

## Unreleased

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
