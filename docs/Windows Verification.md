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
| Test failure review | Confirm `/test` in a disposable project with a failing test. Use Investigate failure, compare named files and error lines with actual output, then confirm a passed test clears the old failure. No investigation command should run another test or edit. | Not tested |
| Activity timeline | Run an approved test and apply/undo a disposable coding edit, then Refresh activity. Confirm labels, local timestamps and undo hints. Inspect that no message body or secret appears in the HUD or newly written action log. | Not tested |
| Memory/documents | PDF/Word/text searches, opt-in OCR, remembered fact edits/deletion, separate conversation clearing, backup/restore/rescue backup with synthetic content. | Not tested |
| Memory expiry | Save a disposable fact, review saved date and source, set expiry for a later local date, restart Jarvis, clear expiry, and verify an expired fact disappears from recall and the SQLite fact list. | Not tested |
| Document index | Turn on the optional index, search selected files, edit and delete one, remove a selected folder, then turn the index off. Confirm stale results disappear and `%APPDATA%\Jarvis\documents-index.sqlite3` is removed when disabled. | Not tested |
| Document research | With two disposable local sources, run `/research-docs` and check that numbered excerpts match the actual file sections; try with Ollama unavailable and with a malicious instruction in a source. Do not infer research quality from stubbed answers. | Not tested |
| Combined research | With disposable local notes and one public page, run `/research-all question | https://source-url`, check the URL approval, compare the actual local and public excerpts, cancel once, then try an injected source. Confirm no local excerpt leaves the configured Ollama endpoint. | Not tested |
| GitHub repository read | Configure a disposable repository and least-privilege token, run `/repo`, cancel once, then approve. Confirm the README matches the repository, no commit is made, and offline and Lockdown modes prevent access. Try a private repository only with authorized read scope. | Not tested |
| System voice picker | In HUD, list installed voices, choose a real British voice for Jarvis and a distinct voice for TUKI, preview both aloud, restart and verify choices. Remove or disable one voice and check fallback reporting. | Not tested |
| Daily document checks | Choose a disposable document folder, add a 1-minute-ahead query, check first-run baseline, edit a match before the next day, then verify one HUD notification. Pause/resume/delete and restart Jarvis to check saved state. Try with an unsafe document and search permission Ask. Schedule uses the PC's local clock and runs only while Jarvis is open. | Not tested |
| Planner | Add/edit/complete tasks, Plan my week, View week, all-day/free events, deadline buffers, export and optional private Canvas sync. | Not tested |
| Daily briefing | Choose a time a minute ahead and turn speech off, observe one HUD digest with no sound, then use Read briefing to replay. Turn speech on and verify real output next day; disable the automatic digest and confirm no scheduled notification. | Not tested |
| Model inventory | With Ollama running, Refresh models in Setup and compare names and disk sizes to Ollama's list. Select each role, test a real conversation or coding proposal, and confirm restarting Jarvis retains the choices. Stop Ollama and check the unavailable state. | Not tested |
| Connections | Review local statuses without exposing secrets. With disposable credentials, remove one from Jarvis after confirmation, restart and confirm the service needs setup; verify Canvas cache deletion and that imported events remain. Provider-side token revocation is separate. | Not tested |
| Images/screen | Opt-in screen picker/cancel, still preview before Ask, local vision lookup, invalid/oversized images, Draft/Balanced/High generation and download with actual local backends. | Not tested |
| NOMAD | Service panel with server absent/present; actual Kiwix content search and sources; no assumption that Jarvis installs NOMAD. Keep real server addresses local. | Not tested |
| Network/security | Offline/Internet/Lockdown toggles; confirmation cancel/expiry; approved public search and throwaway upload only; malformed URL errors must omit private paths/tokens. | Not tested |
| Apps/extensions | Allowlist an innocuous program, preview/confirm/Stop; reject shells, outside files and unapproved extensions. Extensions run as the user and are not sandboxed. | Not tested |

Run the repository Tests workflow on the reviewed commit. Use the existing HUD
control audit for repeatable fixture coverage and the table above for real hardware.
Full production dependency vulnerability resolution, code signing and device-specific
model/audio performance are still separate release work. Never infer safety from
a fixture-only green check or disable protections to make installation succeed.

## Manual input, compact layout and local workflows

- Hold and release the record button and Ctrl+Shift+Space with the HUD focused. Verify the local transcript appears without sending, editing works, and Use in message preserves existing text.
- Record while pausing Mic, pressing Stop/Escape, changing input mode, and switching windows. Confirm no cancelled text appears later. Hold longer than 25 seconds and verify automatic completion. Check the speech model unavailable error.
- Select Hold to record only and verify nearby wake phrases do not run commands or create room context. The input stream remains open; this setting controls processing.
- Toggle Compact view, reload, test all approval controls, inspect at 200% zoom and navigate with a keyboard and screen reader.
- Save a local workflow with tasks, schedule, calculation and a disposable document query. Decline a preview, then run it. Check each actual result, export JSON, Stop and resume, restart and resume, and delete results. Disable a step or set it to Ask and verify the run blocks.
- Status for all these Windows hardware checks: Not tested.

## Workspace views and GitHub issues

- Select Classic, Command Center and Ambient; restart to confirm the choice persists. Test Compact followed by Ambient and confirm conversation and action details remain hidden. Verify active TUKI color, real listening/speaking status, clock toggle, keyboard navigation, reduced motion, Stop, Mic and Lockdown. Ambient does not mute speech or lock Windows.
- With a disposable repository, verify `/issues`, `/issue NUMBER` and cancelled approvals. Test offline, Lockdown, a repository change and insufficient token scopes. Draft a disposable issue with `/new-issue title | body`, review the full text, cancel once and publish once. Confirm no duplicate request after a timeout. Do not test on another person's repository.
- Real Windows hardware and real account verification for this increment: Not tested.
