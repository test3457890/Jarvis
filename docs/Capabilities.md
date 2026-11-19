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
| HUD | Every visible control | Working | `docs/ControlReport.md` (54 checks) |
| HUD | Six themes with contrast checks, phone-width layout | Working | `tests/test_themes.py`, HUD audit |
| Chat | Jarvis and TUKI routing, streaming, Stop and Escape | Working (stubbed model) | HUD audit, unit tests |
| Chat | Answer quality and speed with real models | Untested on hardware | `docs/Benchmarks.md` |
| Voice | Spoken replies, separate TUKI voice | Untested on hardware | Voice selection unit tests only |
| Voice | Wake word and microphone input | Untested on hardware | |
| Voice | "Jarvis, stop" cancels a reply still being prepared; wider hallucination filter | Working (unit tests); untested with a microphone | `tests/test_phase3.py` |
| Voice | Spoken interruption while Jarvis is speaking | Not implemented | Jarvis mutes its microphone while speaking to avoid hearing itself; reliable barge-in needs echo cancellation |
| Coding | Focused multi-file patches, preview, apply, undo, approved tests | Working (stubbed model) | `tests/test_coding_patches.py`, HUD audit |
| Coding | Relevant-file selection, profile-sized context, bounded scans, link refusal | Working (stubbed model) | `tests/test_coding_phase2.py` |
| Coding | Approved build command, failure files fed back, undo after restart | Working (stubbed model) | `tests/test_coding_phase2.py`, HUD audit |
| Benchmarks | Reply time, first sentence, peak memory, coding suite | Harness working; no results yet | `tests/test_benchmark_harness.py`, `docs/Benchmarks.md` |
| Coding | Patch success rate with real coding models | Untested on hardware | |
| Files | Selected-folder file tasks with journal, resume, undo | Working | `tests/test_folder_tasks.py`, HUD audit |
| Files | Windows Recycle Bin integration | Not implemented | Uses `.Jarvis Recycle` instead |
| Documents | Search in PDF, Word, text, Markdown | Working | `tests/test_documents_and_memory.py` |
| Documents | Local OCR (Tesseract) for scanned PDFs and images, session cache | Optional | Needs Tesseract; real Tesseract test on Linux CI when installed |
| Documents | Persistent search index | Not implemented, by measurement | 220 files searched in 0.07 to 0.16 s here; see `docs/Benchmarks.md` |
| Planner | Tasks, weekly plan, Canvas feed | Working | `tests/test_week_planner.py` |
| Memory | Facts, history, backup and restore | Working | unit tests, HUD audit |
| Online | Brave search, source pages, GitHub upload | Optional | Needs keys; mocked in tests |
| Images | Local image lookup and generation | Optional | Needs a vision model or Stable Diffusion |
| NOMAD | Offline library search | Optional | Needs a Project NOMAD server |
| Screen | One user-chosen window or screen still, previewed, sent to the local vision model only on Ask | Working (fake capture source); vision answer needs a vision model | HUD audit |
| Apps | Approved programs (absolute path, no shells), files from selected folders, confirm, Stop, failure reports | Working on Linux; untested on Windows | `tests/test_phase3.py`, HUD audit |
| Extensions | Manifest with permissions, inputs, outputs and tests; off until approved; separate process | Working | `tests/test_phase3.py`, HUD audit, `docs/Extensions.md` |
