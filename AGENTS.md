# Guide for AI contributors

Read this first. Keep changes small, tested and honest. Do not remove existing features, user
data handling or security controls. Never describe Jarvis as "the best" without a defined
comparison and evidence.

## Architecture

Jarvis is a single local Python process. `python -m jarvis` starts a loopback HTTP server that serves
the HUD (`jarvis/ui.html`) to the user's browser, a background watchdog, and optionally the
microphone listener. Local models run in Ollama. There are no containers in this repository. Project
NOMAD is a separate, optional server that the user installs; Jarvis only probes its ports and
queries its Kiwix library.

```
browser HUD (ui.html) <-> webui.py (127.0.0.1, session key) <-> App (__main__.py)
                                                         |-> Brain (brain.py) -> Ollama
                                                         |-> skills.py tools (risky ones need confirmation)
                                                         |-> voice.py Speaker / Listener
```

## Module map

| Module | Feature |
|---|---|
| `__main__.py` | `App`, CLI (`run`, `setup`, `doctor`, `briefing`, `--text`), HUD operations, watchdog |
| `webui.py` | Loopback server, Host/Origin/session-key checks, `/api/*` routes |
| `ui.html` | The whole HUD: panels, themes, setup wizard, file tasks, coding tools. Never declare globals named after browser APIs (`confirm`, `alert`, `open`) |
| `brain.py` | Ollama chat, streaming, `/commands`, tool loop, confirmations |
| `assistants.py` | Jarvis vs TUKI routing, TUKI confidence labels |
| `skills.py` | Tool registry, permissions, confirmation and audit; everyday tools |
| `coder.py` | Coding workspace, related-file context, patch proposals, apply/undo (persisted), syntax checks, approved runs, builds and tests |
| `filejobs.py` | Workspace copy/move jobs and selected-folder file tasks with journal and undo |
| `setupwizard.py` | First-run wizard, download plan, storage budget, resumable downloads |
| `config.py` | Settings, defaults, profiles, themes |
| `voice.py` | Speech output (Windows voice or Piper, per assistant) and wake-word listening |
| `memory.py`, `recovery.py` | SQLite memory, facts, history, backup and restore |
| `planner.py` | Tasks, calendar, Canvas feed, weekly plan |
| `documents.py` | Search inside selected PDF, Word, text and Markdown files; optional Tesseract OCR |
| `docindex.py` | Optional SQLite full-text index of explicitly selected documents; removed when disabled |
| `net.py`, `online.py` | Fail-closed network allowlist, web search, source pages, uploads |
| `secure.py` | DPAPI secrets, audit log, injection fencing |
| `images.py`, `nomad.py`, `comms.py` | Images, Project NOMAD, email/calls/texts |
| `appactions.py` | Approved app actions: allowlisted programs, previews, Stop |
| `extensions.py` | Extension manifests, approval, out-of-process tool calls, declared tests (`docs/Extensions.md`) |

## Entry points
- Start menu or folder shortcut created by `install.ps1`: `.venv\Scripts\python.exe -m jarvis`
- `python -m jarvis --text`, `setup`, `doctor`, `briefing`
- `install.ps1`, `upgrade.ps1`, `scripts/package_release.py`, `scripts/capture_hud.py`, `scripts/benchmark.py`

## Configuration and data
- `%APPDATA%\Jarvis\config.json` settings (never overwrite or delete during upgrades)
- `%APPDATA%\Jarvis\memory.db` conversations, facts, tasks, events, job journals (`kv` table)
- `%APPDATA%\Jarvis\secrets.bin` DPAPI-encrypted secrets; `actions.log` audit log
- `%APPDATA%\Jarvis\setup-state.json` wizard download progress
- `%APPDATA%\Jarvis\extensions\<id>` user-installed extensions (off until enabled)
- `Documents\Jarvis Code` coding workspace; `file_folders` setting for general file tasks
- Ollama models and the Hugging Face cache are shared, outside Jarvis's control

## Security boundaries
- HUD listens on 127.0.0.1 only and requires the per-session key.
- Risky skills always need explicit confirmation; Lockdown disables them.
- All outbound requests go through `net.py`'s allowlist. Offline by default.
- Coding edits stay inside the coding workspace. Generated code never runs without approval.
- File tasks stay inside selected folders, never follow links, never overwrite, and keep the coding
  workspace separate.
- Text from files, web pages and tools is untrusted data, fenced and checked for injected instructions.

## Tests
```
python -m pip install "pytest>=8,<10" "Pillow>=10.4" "pypdf>=5,<7" "python-docx>=1.1,<2"
python -m pytest -q
python -m pip install playwright && python -m playwright install chromium
python -m scripts.capture_hud      # live HUD walkthrough and screenshots in hud-captures/
python -m scripts.hud_control_audit  # every control, verified results, hud-captures/control-report.md
```
Windows-only tests (installer, updater, rollback, DPAPI) run in GitHub Actions on `windows-latest`.

## Release steps
1. Bump `jarvis/__init__.py`, add a `CHANGELOG.md` section, update `docs/ReleaseNotes.md`.
2. Merge through a reviewed PR with passing Tests.
3. The Release workflow builds `Jarvis<version>.zip` and `SHA256SUMS.txt` and publishes them.
4. Verify the archive with `python -m scripts.package_release` locally and compare checksums.

See `docs/Capabilities.md` for what is working, optional, untested on hardware or not implemented.

## Known limitations
- Not code-signed. Defender behaviour is documented, not solved (`docs/WindowsDefender.md`).
- No hard per-app storage quota is possible in shared Ollama or Hugging Face caches.
- No benchmark results yet on an 8 GB Windows PC (`docs/Benchmarks.md`).
- File tasks do not empty `.Jarvis Recycle`; the user removes it in Explorer.
- Windows Recycle Bin integration is not implemented. The optional document index needs Windows lifecycle testing.
- No spoken interruption while Jarvis is speaking; the microphone is muted during speech.
- Extensions run as the Windows user; permissions are declared and approved, not sandboxed.

## Next tasks
- Collect 8 GB Windows benchmarks for both profiles, including `--coding`.
- Code-sign scripts and publish signed releases; consider an MSIX or MSI installer.
- Optional Windows Recycle Bin emptying for `.Jarvis Recycle`.
- More HUD accessibility review with a screen reader.
