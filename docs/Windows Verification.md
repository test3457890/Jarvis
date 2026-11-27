# Windows verification handoff

Prepared November 19, 2026 for owner and Claude testing beginning November 25.
All hardware/visual checks below remain Not tested in this engineering pass.
Use an owned test account with synthetic files, record the commit and Windows build,
and keep private calendar links, conversations, keys and screen captures out of Git.

The baseline Linux suite passed 166 tests with six platform skips. The new request
boundary tests use an inert application over real loopback HTTP. They do not verify
real models, microphone, NOMAD, image backends or Windows UI. Existing screenshots
and the 54-control report use documented fixture/model data. Do not treat them as
completed hardware verification. This pass adds no new screenshots.

| Area | Owner and Claude test | Initial status |
|---|---|---|
| Install/upgrade | Verify release checksum; use a fresh standard Windows account, then upgrade an expendable older install. Confirm shortcuts, preserved config/secrets, missing-prerequisite errors and program-file rollback. Respect device policy. | Not tested |
| First run | Test every wizard page, folder picker, standard/8 GB profile, storage budget, cancel, interrupted download and Resume setup. Missing Ollama must produce useful guidance. | Not tested |
| Assistants/models | Auto/Jarvis/TUKI selections, everyday/coding/vision models, missing-model fallback, real reply streaming, Stop and Escape. Record model names and actual timings on 8 GB hardware. | Not tested |
| Voice | Run `python -m jarvis voice-check` with a disposable spoken phrase; check the displayed transcription and confirm the reply is audible. In Setup, test follow-ups off/8/20 seconds and room context off/30/120 seconds. Pause Mic during transcription, then resume and confirm the old command is ignored. Test Voice and Mic toggles, both voice previews, installed backends, wake words and microphone denial. Spoken interruption during speech is unimplemented. | Not tested |
| Modes/themes | Everyday, Coding, Briefing and Talk; all six themes; 200% zoom, phone width, keyboard focus, screen reader labels and live status. | Not tested |
| Coding/files | In disposable selected folders preview/apply/undo multi-file fixes; confirm tests separately; deny outside paths, links and overwrites; interrupt/resume jobs; ensure changed files block undo. | Not tested |
| Git coding workspace | Select an existing disposable Git repository in Setup, inspect listed files and test command, edit a file only after diff review, confirm the test command, switch back to Jarvis Code, and verify undo is scoped to its original folder. Try a `.git/config` path and Lockdown. | Not tested |
| Activity timeline | Run an approved test and apply/undo a disposable coding edit, then Refresh activity. Confirm labels, local timestamps and undo hints. Inspect that no message body or secret appears in the HUD or newly written action log. | Not tested |
| Memory/documents | PDF/Word/text searches, opt-in OCR, remembered fact edits/deletion, separate conversation clearing, backup/restore/rescue backup with synthetic content. | Not tested |
| Document index | Turn on the optional index, search selected files, edit and delete one, remove a selected folder, then turn the index off. Confirm stale results disappear and `%APPDATA%\Jarvis\documents-index.sqlite3` is removed when disabled. | Not tested |
| Document research | With two disposable local sources, run `/research-docs` and check that numbered excerpts match the actual file sections; try with Ollama unavailable and with a malicious instruction in a source. Do not infer research quality from stubbed answers. | Not tested |
| Daily document checks | Choose a disposable document folder, add a 1-minute-ahead query, check first-run baseline, edit a match before the next day, then verify one HUD notification. Pause/resume/delete and restart Jarvis to check saved state. Try with an unsafe document and search permission Ask. Schedule uses the PC's local clock and runs only while Jarvis is open. | Not tested |
| Planner | Add/edit/complete tasks, Plan my week, View week, all-day/free events, deadline buffers, export and optional private Canvas sync. | Not tested |
| Images/screen | Opt-in screen picker/cancel, still preview before Ask, local vision lookup, invalid/oversized images, Draft/Balanced/High generation and download with actual local backends. | Not tested |
| NOMAD | Service panel with server absent/present; actual Kiwix content search and sources; no assumption that Jarvis installs NOMAD. Keep real server addresses local. | Not tested |
| Network/security | Offline/Internet/Lockdown toggles; confirmation cancel/expiry; approved public search and throwaway upload only; malformed URL errors must omit private paths/tokens. | Not tested |
| Apps/extensions | Allowlist an innocuous program, preview/confirm/Stop; reject shells, outside files and unapproved extensions. Extensions run as the user and are not sandboxed. | Not tested |

Run the repository Tests workflow on the reviewed commit. Use the existing HUD
control audit for repeatable fixture coverage and the table above for real hardware.
Full production dependency vulnerability resolution, code signing and device-specific
model/audio performance are still separate release work. Never infer safety from
a fixture-only green check or disable protections to make installation succeed.
