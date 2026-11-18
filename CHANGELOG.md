# Changelog

All notable changes to Jarvis. Each release adds a section here before it is tagged.

## 1.2.0 (unreleased)

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
