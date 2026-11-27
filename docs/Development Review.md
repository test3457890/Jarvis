# Development review: November 27, 2026

This is a local implementation review, not a completion or release claim.

## Baseline

- Main at `2bbc58499ae9f766dd4d8469c366a3d86c82c2cc`: 217 passed, 6 skipped locally.
- Open PR #36, `feature/voice-inventory`, at `d15728dff2f7be787bb7f74606e0f829046440ac`: included as the starting point of this working branch. It was not merged when checked.
- Working branch: `feature/deliberate-voice-and-workflows`.
- Legacy interfaces, permissions, offline behavior and data are preserved.

## Implemented in this batch

| Roadmap area | Actual behavior | Remaining scope |
|---|---|---|
| V04 / V05 | Hold-to-record button and focused-page Ctrl+Shift+Space; local editable transcript; copy or explicitly use in an empty message | System-wide hotkey, tray, automatic app dictation |
| Voice privacy | Manual-only processing mode, 25-second capture limit, cancellation and stale transcription rejection, bounded ambient queue | Real microphone and Whisper testing on Windows |
| U01 / U02 | Saved compact browser layout, keyboard focus, skip link and reduced motion | Native floating widget, screen-reader and visual browser review |
| A02 / A04 | Saved fixed local read workflows, exact step review, progress checkpoints, Stop, restart recovery and resume | General workflows with effects, external steps, scheduling and agent delegation |
| U03 | Workflow results with source references returned by the document tool, JSON export, deletion and bounded retention | Broader artifact catalog and project knowledge spaces |
| CI | NumPy explicitly installed for the voice tests and HUD job; expanded HUD audit | CI must run after branch publication |

Workflows support selected-document search, saved schedule, open tasks, deadline review and arithmetic. No result from a step becomes an executable instruction or an argument to another step. Ask and Off permissions block execution. Invalid calculations and unsafe source content do not count as completed steps.

## Verification

- `python -m pytest -q`: 254 passed, 6 skipped. The platform-only checks were not established by this Linux run.
- `python -m compileall -q jarvis scripts tests`: passed.
- `git diff --check`: passed.
- Extracted HUD JavaScript checked with `node --check`: passed.
- Local jsdom harness: full script initialisation, compact toggles, transcript preview, preserving an existing draft, no automatic submission, and workflow save/run/render/delete passed with stubbed endpoints. This is a DOM check, not visual browser verification.
- `python -m scripts.package_release`: passed. This was a local source-package build, not a published release or a version bump.
- Playwright browser installation: failed with HTTP 403. The available `/usr/bin/chromium` launcher points to a missing executable. The expanded HUD audit is prepared but has not passed locally.
- No real microphone, speakers, Windows voice inventory, Ollama models, private account adapters, GPU or Windows installer was tested here.

## Publication

The user explicitly authorized publishing this branch to `test3457890/Jarvis` and continuing development. Git CLI authentication is unavailable in this workspace, so publication uses the connected GitHub API. CI status must be checked after the pull request is opened. PR #36 is included in this branch; reconcile that overlap before merging.

## Outstanding roadmap

The project is not finished. See `Master Development Plan.md` for the full inventory. Work still includes reliable spoken interruption, global shortcuts/tray, Google and Microsoft account adapters, MCP, feeds, GitHub issues and PR operations, broader routines and specialist agents, worktrees, additional model providers, sandboxed extensions, signed packaging, mobile access and hardware benchmarks. Phase 2 finance, Garmin/fitness/chef, Rust foundation, Sentinel, expanded NOMAD, server/household features and the three design concepts are not implemented or verified by this batch.

## Follow-up implementation

PR #37 at `63bf65042986b484ce2f550f700dbe00353f0889` passed all four GitHub CI jobs: Ubuntu tests, Windows tests, full Windows installation/first launch, and browser HUD audit. This establishes automated Windows installation and browser behavior, not real microphone/model quality.

The follow-up branch `feature/workspace-views-and-github` adds the three selectable browser workspace views and approved GitHub issue list/read/create operations, plus repository-change approval invalidation. Its own CI results must be checked separately. GitHub push/PR tools, native tray/global hotkeys, the remaining account connectors and broader Phase 2 work remain outstanding.

## Local chat-provider and design-reference follow-up

PR #38 at `8b5847fa071d02daa1238c4a3d4d333122e892f1` passed all four GitHub CI jobs, including the workspace-view browser checks. Its CI artifacts contain the initial Command Center and Ambient application captures using synthetic test data.

The next branch adds a numeric-loopback-only chat-completions adapter with a selected model ID, saved setup, real HTTP fixture tests, strict completed-tool parsing and no automatic fallback. It does not establish real inference quality or performance. The three original design concepts are also restored without altering their source bytes. All other outstanding roadmap entries retain their documented status.
