# Jarvis master development plan

Status: planning and implementation tracker, November 26, 2026. This document describes proposed work, not features already shipped. The source of truth for shipped behavior is [Capabilities](Capabilities.md). The first delivered item under this plan is the optional `voice-check` command. Its audio path still requires a real Windows test.

## Product goal

A private, useful Windows assistant that can hold a natural spoken conversation, help with research, planning and coding, and act on the user's PC within visible permissions. Keep offline operation as the default. Distinguish Jarvis's everyday help from TUKI's technical work without splitting their shared conversation. Prefer useful tasks over adding modes or animations that do not improve a task.

## Starting point

Already in this repository: local Ollama chat, Jarvis/TUKI routing, HUD and Talk mode, wake word and speech code, planner and Canvas feed, reminders and briefing, selected-folder file tasks with undo, bounded PDF/Word/text search, remembered facts, coding diff/apply/undo and approved tests, optional search/images/NOMAD, screen still capture, allowlisted app actions, approved extensions, confirmations, audit and Lockdown. Many paths pass automated tests with model or audio stubs. The microphone, speaker, actual Windows voice quality, real model performance, installed extensions and several hardware integrations have not been end-to-end verified. See [Windows verification](Windows%20Verification.md).

## Projects reviewed and reuse rules

| Source | Useful concepts | Reuse approach |
|---|---|---|
| [OpenJarvis](https://github.com/open-jarvis/OpenJarvis) | Scheduled agents, indexed research, service connectors, composable skills, model and efficiency evaluation, spoken digest, agent traces | Compare documented behavior, design small independent components; Apache 2.0 code only if attribution, notices and compatibility are reviewed before copying. |
| [isair/Jarvis](https://github.com/isair/jarvis) | Room conversation, temporary context, voice-first status, dictation, activity timeline, local model selection and MCP connections | Our room context already overlaps; adapt interaction ideas. Confirm the license for any specific source file before code reuse. |
| [Personal Jarvis](https://github.com/PersonalJarvis/PersonalJarvis) | Specialist agents with separate workspaces, coding worktrees, routines, plugin connections, audit timeline, dictated input and adjustable permissions | Use as feature inspiration. Verify repository license and individual dependencies before copying any implementation. |
| [OpenDex](https://github.com/wassgha/opendex) | Compact desktop view, interchangeable voice input/output, hotkeys, readable tool approval, model provider selection | Rebuild with our Python/HUD architecture; inspect MIT license and attribution before copying. |
| [Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad) | Offline content services, library and maps | Preserve optional integration; NOMAD is a separate server, not a bundled Jarvis feature. |

A public repository is not permission to paste its code or artwork without reviewing its license and dependencies. Do not import large unreviewed skill catalogs into the default installation. Record source URL, commit, file, license, changes and required notices in a reuse ledger if code or assets are actually copied. No third-party code was copied for this plan or the first implementation.

## Feature inventory and decisions

Status values: Existing means code is present, not necessarily verified with hardware. Partial means an adjacent feature exists. New means no equivalent shipped capability is established. Each entry is a proposal until implemented and verified.

| ID | Proposed capability | Current state | Initial approach | Priority |
|---|---|---|---|---|
| V01 | Real microphone, transcription, TTS diagnostic | Partial: `doctor` checks packages and device presence | Optional local `voice-check`; verify real Windows input and output | P0 |
| V02 | Follow-ups without repeating wake word | Existing short configurable follow-up window | Test actual room flow; expose duration and listening indicator | P0 |
| V03 | Interrupt speech by voice | New: mic is muted during replies | Echo cancellation or separate hotkey path; test against feedback and false stops | P1 |
| V04 | Push to talk and system tray hotkey | New | Explicit opt-in capture with visible state and cancel | P1 |
| V05 | Dictation into chosen application | New | Hold-to-dictate, preview text and paste via accessibility-safe Windows API | P2 |
| V06 | Voice engine and British voice picker | Partial: Windows/Piper selection | Device/voice previews, availability and fallback reporting | P1 |
| V07 | Spoken daily digest | Partial: briefing/watchdog | Sections for schedule, tasks and optionally connected feeds; replay and mute | P1 |
| V08 | Privacy and room context controls | Partial: rolling transcript and mic toggle | Explicit retention and context settings, visible pause, no raw audio persistence | P0 |
| V09 | Responsive conversational latency | Partial: streaming drafts and sentence speech | Measure time to first spoken word on real hardware, warm caches, cancel stale replies | P1 |
| C01 | Account connection center | New | Per-service scopes, status, reconnect and revoke; default read-only | P1 |
| C02 | Google calendar, email, tasks, Drive | Partial: Canvas calendar feed only | Optional OAuth adapters, separate scopes, preview writes | P2 |
| C03 | Outlook and Microsoft 365 | Partial: mail-app draft | Optional calendar/mail/files adapter with narrow scopes | P2 |
| C04 | GitHub repository read and issues | Partial: one-repository upload | Read-only repo context first; explicit approval for issue, push or PR | P1 |
| C05 | Weather, RSS and news | New | Source selection and attribution; only fetch when enabled | P2 |
| C06 | Discord, Teams or Slack | New | Per-channel read permission first; no unattended posting | P3 |
| C07 | MCP client with server permission screen | New | Per-server capability and origin review, timeouts and audit; disabled by default | P2 |
| C08 | Optional smart-home and music adapters | New | Separate opt-in permissions, bounded commands | P3 |
| C09 | Mobile access | Partial: phone-width HUD on loopback, no phone service | Authenticated local-network companion only after threat review; no automatic port exposure | P3 |
| A01 | User-defined recurring checks | Partial: fixed watchdog reminders | Schedules, pause/resume, last-run state, change-only notifications | P1 |
| A02 | Reusable workflows | New | Small declarative steps, dry run, per-step confirmation for effects | P2 |
| A03 | Specialist agents | Partial: Jarvis/TUKI routing | Explicit Research, Coding and Planner roles with task state and tool budgets | P2 |
| A04 | Long-running tasks and progress | New | Cancel, resume, checkpoint and visible timeline | P2 |
| A05 | Agent handoff and delegation | New | First implement single-agent traces; add handoff only with clear value | P3 |
| R01 | Indexed knowledge base | New: current bounded search reads files on each request | Optional local SQLite full-text index, incremental updates, delete and rebuild | P1 |
| R02 | Research across files and web pages | Partial: document search and approved web read | Multiple source gathering, contradictions, inline page or paragraph citations | P1 |
| R03 | Project knowledge spaces | New | User-selected folders/repos, scoped search and memory | P2 |
| R04 | Memory provenance and expiry | Partial: fact editor and backup | Show source and date; correct, forget and expire per item | P1 |
| R05 | Image, screen and PDF understanding | Partial: image lookup, still capture and optional OCR | Multiple images and selected regions, visible outbound data preview | P2 |
| D01 | Open a selected Git repository for coding | Partial: Jarvis Code folder | Explicit workspace grant, read-only discovery, controlled test commands | P1 |
| D02 | Isolated coding worktrees | New | Branch/worktree, bounded commands, diff review and rollback | P2 |
| D03 | Test failure investigation | Partial: approved test and fix flow | Collect failure trace and changed files; propose next diff | P1 |
| D04 | Multi-agent coding panes | New | Defer until one-workspace review and cancellation are dependable | P3 |
| M01 | Model selection and memory budget UI | Partial: profiles and setup wizard | Per-task model inventory, RAM/VRAM estimate and measured timings | P1 |
| M02 | More local model providers | New: Ollama only | Opt-in OpenAI-compatible local server with strict URL trust boundary | P2 |
| M03 | Optional cloud model fallback | New | Separate consent per request, cost and data preview, never silent fallback | P3 |
| M04 | Performance and quality evaluations | Partial: benchmark harness, no real results | Publish hardware, model, prompt set, latency, memory and failure rate | P0 |
| S01 | Curated skill gallery | Partial: extension manifest and permissions | Signed or pinned sources, review, updates, disable and uninstall | P2 |
| S02 | Permissions that enforce scope | Partial: extension permissions not OS sandbox | Separate least-privilege process/OS boundary before untrusted marketplace | P1 |
| S03 | Desktop/browser actions | Partial: allowlisted app launch and one screen still | Narrow task-specific actions, visible target and reversible steps | P2 |
| S04 | Activity and audit timeline | Partial: actions.log and control report | Human-readable tool input/output, redaction, reason and undo link | P1 |
| S05 | Installer signing and native package | New | Signed builds, reproducible release manifest and clean Windows install test | P1 |
| U01 | Compact floating voice view | New: HUD has themes | Small listening/thinking/speaking panel with keyboard access | P2 |
| U02 | Accessibility and onboarding | Partial: wizard and contrast checks | Screen reader pass, 200% zoom, transcript and input device guidance | P1 |
| U03 | Task artifacts and export | Partial: code and image downloads | Searchable local results, export with provenance and deletion controls | P2 |

## Build order and acceptance gates

### Gate 0: establish a truthful baseline

Run the existing test suite, HUD control audit and Windows checklist at a pinned commit. Test on a clean Windows account with a microphone, speaker, Ollama models and an 8 GB profile. Record failures without changing statuses to Working. `voice-check` exercises a sample in memory and reports recognized words; the user must confirm hearing playback. It does not prove wake words, echo handling or overall voice quality.

### Gate 1: conversation that works

Deliver V01, V02, V06, V08, V09, then V03 and V04. Acceptance: say a wake phrase, receive an audible reply, ask a follow-up, pause the mic, recover from a denied mic, stop a response, and leave no raw recording on disk. Track recognition accuracy, false wakes, speech delay and CPU/RAM on target hardware. If spoken barge-in fails echo tests, use the hotkey while refining it.

### Gate 2: useful information

Deliver R01/R02 and V07, then C01/C04. Acceptance: sources have clickable provenance; a file removal removes indexed content; offline mode performs no external request; each connected account exposes its granted scopes. A digest never sends or modifies anything.

### Gate 3: supervised work

Deliver A01, D01/D03, S04. Acceptance: recurring checks have a last-run record, disabled jobs never run, external requests show their destinations, repository edits stay in the granted workspace, test commands require approval, and every change has a diff and rollback path.

### Gate 4: ecosystem

Deliver C02/C03/C07, A02, M01/M02 and U01/U02. Acceptance: connection revocation works, credentials stay in protected storage, no plugin gains undeclared access, errors are actionable, and a clean Windows install and upgrade preserve existing user data.

### Gate 5: optional expansions

Consider dictation, specialist agents, smart-home/music integrations, mobile access, cloud models, marketplace and additional platforms only after the preceding gates pass. Each needs a separate design, measurable benefit and threat review.

## Test matrix for every shipped feature

1. Unit tests for parsing and permissions; integration tests for actual adapters where a disposable account or fake local server is appropriate.
2. Negative tests for cancelled approvals, expired sessions, unavailable service, malformed responses, offline/Lockdown, revoked access and restart after interruption.
3. Manual Windows tests on the target laptop for speech, audio, tray, screen, Phone Link, DPAPI, installer and GPU. Fixture screenshots and stubbed models do not count as hardware proof.
4. Record commit, Windows build, dependency versions, hardware, results and unresolved limitations in `docs/Capabilities.md` and `docs/Windows Verification.md` before a release claim.
5. Run existing CI and packaging checks; do not merge a feature just because a documentation example works.

## Current delivery record

- Added `python -m jarvis voice-check`: after an explicit Enter, records four seconds locally, transcribes with the configured local Whisper model, displays recognized text and attempts a spoken reply. No audio file is written. CI can validate control flow with fake audio; only a Windows microphone and speaker test can validate the real path.
- Added Setup controls for follow-up and temporary room context (V02/V08), including a zero-context choice. Pausing Mic clears temporary context and prevents an in-progress transcription from issuing a command after pause/resume. Unit tested; real Windows microphone behavior remains to verify.
- Added an opt-in SQLite full-text document index (R01). Search refreshes changed files, removes deleted files, respects the selected folders and existing scan limits, and wipes the index when disabled or folders change. Automated tests cover the lifecycle; Windows storage and hardware behavior remain untested.
- Added `/research-docs` (part of R02) to ask the local model to compare matching local excerpts while showing the original numbered file and section excerpts. It blocks a summary if the document injection screen flags content. Public web source comparison already exists separately through `/check`; combined web and document research remains planned. Real model answer quality is unverified.
- Added a first A01 slice: opt-in daily checks for a chosen query against selected local document folders. The HUD supports pause, resume, delete and last-run review; notifications occur when matching excerpts change after a baseline. Automated tests cover schedule state, safety and edits. Broader recurring external checks remain planned; Windows scheduling behavior is unverified.
- Added a first D01 slice: the Setup panel can grant an existing local Git repository as the Coding mode workspace. Project discovery stays read-only, `.git` paths are excluded, the existing diff and test approvals apply, and undo state follows the chosen workspace. Automated tests cover path and workspace isolation; real Windows Git folder behavior remains unverified.
- Added a first S04 slice: the HUD can show a bounded local activity timeline with action labels and undo hints without exposing raw message content or tool results. Newly logged risky and internet tool calls record field names instead of their values. Automated tests cover filtering and log privacy; Windows HUD review remains unverified.
- Added a first R04 slice: remembered facts show saved time and source category, and users can set or clear an expiry. Expired facts are deleted and excluded from recall. The existing database migrates in place. Automated tests cover migration and expiry; Windows date UI remains unverified.
- Added a D03 investigation step: after an approved failed test run, `/investigate-tests` extracts bounded error lines and likely files inside the selected workspace without another command or model call. A passing run or workspace switch clears the old failure state. Automated tests cover the sequence; real project output quality is unverified.
- All other entries in this plan remain proposals. No bulk connector, agent, voice, marketplace or model feature is represented as implemented by this document.
