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
| Voice | Configurable follow-up and temporary room context; pause clears context and ignores pending transcription | Working in unit tests; untested on microphone hardware | Setup controls, `tests/test_phase3.py` |
| Voice | Opt-in local `voice-check` diagnostic | Working with stubbed audio; untested on Windows hardware | Requires microphone, local Whisper model and audible speaker confirmation |
| Voice | "Jarvis, stop" cancels a reply still being prepared; wider hallucination filter | Working (unit tests); untested with a microphone | `tests/test_phase3.py` |
| Voice | Spoken interruption while Jarvis is speaking | Not implemented | Jarvis mutes its microphone while speaking to avoid hearing itself; reliable barge-in needs echo cancellation |
| Coding | Focused multi-file patches, preview, apply, undo, approved tests | Working (stubbed model) | `tests/test_coding_patches.py`, HUD audit |
| Coding | Relevant-file selection, profile-sized context, bounded scans, link refusal | Working (stubbed model) | `tests/test_coding_phase2.py` |
| Coding | Approved build command, failure files fed back, undo after restart | Working (stubbed model) | `tests/test_coding_phase2.py`, HUD audit |
| Coding | Read-only review of last failed approved test output and likely workspace files | Working in automated tests; real project errors unverified | `/investigate-tests`, `tests/test_coding_phase2.py` |
| Coding | Explicit selection of an existing local Git repository as a scoped workspace | Working in automated tests; local Windows repository untested | `tests/test_repository_workspace.py` |
| Benchmarks | Reply time, first sentence, peak memory, coding suite | Harness working; no results yet | `tests/test_benchmark_harness.py`, `docs/Benchmarks.md` |
| Coding | Patch success rate with real coding models | Untested on hardware | |
| Files | Selected-folder file tasks with journal, resume, undo | Working | `tests/test_folder_tasks.py`, HUD audit |
| Files | Windows Recycle Bin integration | Not implemented | Uses `.Jarvis Recycle` instead |
| Documents | Search in PDF, Word, text, Markdown | Working | `tests/test_documents_and_memory.py` |
| Documents | Local OCR (Tesseract) for scanned PDFs and images, session cache | Optional | Needs Tesseract; real Tesseract test on Linux CI when installed |
| Documents | Optional local SQLite full-text index | Working in automated tests; Windows file lifecycle untested | On by explicit Setup choice; `tests/test_document_index.py` |
| Research | Local model comparison of selected document excerpts, with original source sections attached | Working with stubbed model; real answer quality untested | `/research-docs`, `tests/test_document_research.py` |
| Recurring checks | Daily selected-folder document query, local last-run state, change-only notification, pause/resume/delete | Working in automated tests; Windows schedule and notification untested | `tests/test_document_watches.py` |
| Planner | Tasks, weekly plan, Canvas feed | Working | `tests/test_week_planner.py` |
| Briefing | User-selected local time, automatic show/mute and manual replay | Working in automated tests; real speech unverified | `tests/test_briefing_controls.py` |
| Models | Read-only local Ollama inventory with reported disk sizes and explicit model role selection | Working in automated tests; model compatibility and real timings unverified | `tests/test_model_inventory.py` |
| Memory | Facts, history, backup and restore | Working | unit tests, HUD audit |
| Memory | Saved date, source category and per-fact expiration with deletion on due | Working in automated tests; Windows local-date UI untested | `tests/test_memory_expiry.py` |
| Audit | Bounded human-readable action timeline with redacted metadata and undo hints | Working in automated tests; Windows HUD review untested | `tests/test_activity_timeline.py` |
| Online | Brave search, source pages, GitHub upload | Optional | Needs keys; mocked in tests |
| Images | Local image lookup and generation | Optional | Needs a vision model or Stable Diffusion |
| NOMAD | Offline library search | Optional | Needs a Project NOMAD server |
| Screen | One user-chosen window or screen still, previewed, sent to the local vision model only on Ask | Working (fake capture source); vision answer needs a vision model | HUD audit |
| Apps | Approved programs (absolute path, no shells), files from selected folders, confirm, Stop, failure reports | Working on Linux; untested on Windows | `tests/test_phase3.py`, HUD audit |
| Extensions | Manifest with permissions, inputs, outputs and tests; off until approved; separate process | Working | `tests/test_phase3.py`, HUD audit, `docs/Extensions.md` |
