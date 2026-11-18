# Capability matrix

Status words: **Working** has automated tests on Linux and Windows CI. **Optional** works after the
user installs or configures something. **Untested on hardware** passes automated tests with stubbed
models or audio but has not been verified with real models, a microphone or speakers on a Windows PC.
**Not implemented** does not exist yet.

| Area | Feature | Status | Evidence |
|---|---|---|---|
| Install | `install.ps1`, Start menu shortcut, no batch launcher | Working | Windows CI install job |
| Install | First-run setup wizard, storage budget, resumable downloads | Working (stubbed downloads) | `tests/test_setup_wizard.py`, HUD audit |
| Install | Real Ollama and speech model downloads through the wizard | Untested on hardware | Needs Ollama on a Windows PC |
| Upgrade | Upgrade from 1.1.1 and 1.2.1 with their own updater, rollback | Working | `tests/test_upgrade_paths.py` (Windows CI) |
| Upgrade | Code-signed releases | Not implemented | `docs/WindowsDefender.md` |
| HUD | Every visible control | Working | `docs/ControlReport.md` (47 checks) |
| HUD | Six themes with contrast checks, phone-width layout | Working | `tests/test_themes.py`, HUD audit |
| Chat | Jarvis and TUKI routing, streaming, Stop and Escape | Working (stubbed model) | HUD audit, unit tests |
| Chat | Answer quality and speed with real models | Untested on hardware | `docs/Benchmarks.md` |
| Voice | Spoken replies, separate TUKI voice | Untested on hardware | Voice selection unit tests only |
| Voice | Wake word and microphone input | Untested on hardware | |
| Voice | Spoken interruption while Jarvis is speaking | Not implemented | |
| Coding | Focused multi-file patches, preview, apply, undo, approved tests | Working (stubbed model) | `tests/test_coding_patches.py`, HUD audit |
| Coding | Patch success rate with real coding models | Untested on hardware | |
| Files | Selected-folder file tasks with journal, resume, undo | Working | `tests/test_folder_tasks.py`, HUD audit |
| Files | Windows Recycle Bin integration | Not implemented | Uses `.Jarvis Recycle` instead |
| Documents | Search in PDF, Word, text, Markdown | Working | `tests/test_documents_and_memory.py` |
| Documents | OCR for scanned PDFs, persistent index | Not implemented | |
| Planner | Tasks, weekly plan, Canvas feed | Working | `tests/test_week_planner.py` |
| Memory | Facts, history, backup and restore | Working | unit tests, HUD audit |
| Online | Brave search, source pages, GitHub upload | Optional | Needs keys; mocked in tests |
| Images | Local image lookup and generation | Optional | Needs a vision model or Stable Diffusion |
| NOMAD | Offline library search | Optional | Needs a Project NOMAD server |
| Screen | Understanding a selected screenshot or window | Not implemented | Planned for increment 3 |
| Apps | Approved app actions | Not implemented | Planned for increment 3 |
| Extensions | Declared-permission extension interface | Not implemented | Planned for increment 3 |
