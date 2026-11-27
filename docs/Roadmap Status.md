# Jarvis roadmap status: November 27, 2026

This checks every one of the 44 IDs in the master plan. Code presence and fixture/CI success do not establish real hardware, account access or model quality. No overall completion percentage is claimed.

PR #37 and #38 passed their four CI jobs. PR #39 passed all four after the provider-form phone-layout fix at fe60a5c. The feed/weather increment has 325 local tests passing and 6 platform-specific skips; its own remote CI is pending publication.

| ID | Capability | Status | Actual scope and remaining work |
|---|---|---|---|
| V01 | Real microphone, transcription, TTS diagnostic | Code present; hardware unverified | voice-check diagnostic; real microphone, recognition and audible playback still required. |
| V02 | Follow-ups without repeating wake word | Code present; hardware unverified | Follow-up window and controls; real room conversation flow still required. |
| V03 | Interrupt speech by voice | Planned | No reliable spoken interruption during speech; echo cancellation and hardware tests remain. |
| V04 | Push to talk and system tray hotkey | Partial | Focused-HUD hold shortcut is present; global hotkey and system tray remain. |
| V05 | Dictation into chosen application | Partial | Editable transcript and clipboard copy are present; chosen-application dictation remains. |
| V06 | Voice engine and British voice picker | Code present; hardware unverified | Installed voice picker and separate assistant choices; Windows voice availability and sound quality remain. |
| V07 | Spoken daily digest | Partial | Saved briefing time, replay and mute; connected-feed digest sections remain. |
| V08 | Privacy and room context controls | Code present; hardware unverified | Temporary context, pause/cancellation and manual-only processing; verify actual microphone behavior. |
| V09 | Responsive conversational latency | Partial | Default Ollama streaming and timing metrics; real latency results and cache tuning remain. |
| C01 | Account connection center | Partial | Built-in configuration/scopes and local credential removal; full OAuth reconnect and provider revocation remain. |
| C02 | Google calendar, email, tasks, Drive | Partial | Existing Canvas feed and mail draft paths; Google Calendar/Gmail/Tasks/Drive OAuth adapters remain. |
| C03 | Outlook and Microsoft 365 | Partial | Existing mail-app drafting; Microsoft calendar/mail/files OAuth adapter remains. |
| C04 | GitHub repository read and issues | Partial | Approved repo/README, issue/comment reads, explicit issue creation and file upload; Git push and PR operations remain. |
| C05 | Weather, RSS and news | Partial | Manual approved RSS/Atom and NWS forecasts added; saved subscriptions, recurring external polling and digest inclusion remain. |
| C06 | Discord, Teams or Slack | Planned | Discord, Teams and Slack adapters remain. |
| C07 | MCP client with server permission screen | Planned | MCP client and per-server permission management remain. |
| C08 | Optional smart-home and music adapters | Planned | Optional smart-home and music adapters remain. |
| C09 | Mobile access | Partial | Responsive loopback HUD exists; authenticated phone access and companion service remain. |
| A01 | User-defined recurring checks | Partial | Daily local-document checks with pause/resume; general recurring external checks remain. |
| A02 | Reusable workflows | Partial | Reviewed deterministic local read workflows; effectful and external workflow steps remain. |
| A03 | Specialist agents | Partial | Jarvis/TUKI routing exists; independent specialist task state and budgets remain. |
| A04 | Long-running tasks and progress | Partial | File jobs and local workflow checkpoints/Stop/resume; generalized long-running agent tasks remain. |
| A05 | Agent handoff and delegation | Planned | Agent handoff and delegation remain. |
| R01 | Indexed knowledge base | Code present; hardware unverified | Opt-in local full-text index with refresh/deletion/rebuild behavior; Windows file lifecycle remains. |
| R02 | Research across files and web pages | Partial | Approved combined local/page evidence and document research; real answer quality and richer source citations remain. |
| R03 | Project knowledge spaces | Planned | Project-scoped knowledge spaces and memory remain. |
| R04 | Memory provenance and expiry | Code present; hardware unverified | Fact origin/date, editing, forgetting and expiry; real Windows migration/date review remains. |
| R05 | Image, screen and PDF understanding | Partial | Selected still image, vision lookup and OCR; multiple-image/region workflows remain. |
| D01 | Open a selected Git repository for coding | Code present; hardware unverified | Explicit existing repository grant and scoped edits/tests; actual Windows project verification remains. |
| D02 | Isolated coding worktrees | Planned | Isolated coding worktrees and their reviewed command/rollback lifecycle remain. |
| D03 | Test failure investigation | Partial | Read-only failure extraction and focused fix previews; real-project diagnosis quality remains. |
| D04 | Multi-agent coding panes | Planned | Multi-agent coding panes remain. |
| M01 | Model selection and memory budget UI | Partial | Ollama inventory and role selection; real RAM/VRAM estimates and measured timings remain. |
| M02 | More local model providers | Partial | Loopback chat-completions adapter with completed replies and validated tools; real-model compatibility, auth and streaming remain. |
| M03 | Optional cloud model fallback | Planned | Optional per-request-consented cloud fallback remains; none is enabled or silently used. |
| M04 | Performance and quality evaluations | Partial | Benchmark harness exists; actual target-hardware latency, memory and quality results remain. |
| S01 | Curated skill gallery | Partial | Approved extension manifests exist; pinned curated gallery, update and uninstall lifecycle remain. |
| S02 | Permissions that enforce scope | Planned | OS-enforced least-privilege isolation for extensions remains; declarations are not a sandbox. |
| S03 | Desktop/browser actions | Partial | Approved app launch and user-selected screen still; broader bounded desktop/browser automation remains. |
| S04 | Activity and audit timeline | Partial | Redacted local timeline, undo hints and workflow progress; broader agent traces remain. |
| S05 | Installer signing and native package | Partial | Reproducible source ZIP and tested Windows installer/updater; signing and native MSI/MSIX remain. |
| U01 | Compact floating voice view | Partial | Compact browser view and initial Ambient view; native floating/tray view remains. |
| U02 | Accessibility and onboarding | Partial | Wizard, contrast, focus, skip link and reduced motion; screen-reader and 200% zoom review remain. |
| U03 | Task artifacts and export | Partial | Workflow JSON export/deletion plus code/image exports; searchable artifact catalog remains. |

## Broader Phase 2

The three original design concepts are now preserved, and Classic/Command Center/Ambient browser views are present. This does not complete the full concepts. Rust foundation, finance/brokerage, Garmin/fitness/chef, Sentinel/cyber-defense expansion, expanded NOMAD, native mobile, household/server deployment and account integrations remain to be built or verified. Existing NOMAD library integration and current security controls are retained.

## Verification and release dependencies

- Run the target-laptop checklist for real speech, actual model quality/performance, DPAPI and user-data migrations.
- Configure and test only accounts/services the owner chooses with the required credentials and scopes; mocked API responses do not establish access.
- Complete OS isolation and signing with the actual Windows environment and signing identity before claiming those capabilities.
- Review and merge the stacked pull requests in order, reconcile the voice-picker overlap with PR #36, then perform versioned release checks. These branches are not a published new release.

See [Capabilities](Capabilities.md), [Master Development Plan](Master%20Development%20Plan.md), [Development Review](Development%20Review.md) and [Windows Verification](Windows%20Verification.md).
