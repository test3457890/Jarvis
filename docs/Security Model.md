# Jarvis Defensive Security Model

Jarvis is built around a fail-closed, local-first security posture. Every capability assumes that external content (web pages, feeds, GitHub text, local documents, clipboard, and MCP/extension responses) is untrusted data.

## Core Security Controls

1. **Loopback-Only Local Service (`jarvis/webui.py`)**
   - Binds exclusively to `127.0.0.1:<port>` (never `0.0.0.0`).
   - Enforces exact `Host` allowlist (`127.0.0.1:<port>`, `localhost:<port>`) to prevent DNS rebinding.
   - Enforces `Origin` header validation and a per-session random `X-Jarvis-Key` secret (`secrets.compare_digest`) on all API calls and SSE streams.
   - Enforces `Content-Security-Policy`, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`, bounded `Content-Length`, request body timeouts, and rejects `Transfer-Encoding` smuggling.

2. **Fail-Closed Network Allowlist (`jarvis/net.py`)**
   - Offline by default (`allow_internet_tools = False`).
   - Every HTTP/HTTPS/TCP/SMTP call passes through `net.py`.
   - Public page, RSS/Atom, and NWS weather reads resolve DNS and verify every address is globally routable (blocking SSRF to RFC1918, link-local, or loopback metadata services), pin the resolved IP, refuse redirects, reject compressed/oversized payloads (>1 MB), and enforce strict content types.
   - Local providers (`localprovider.py`, `images.py`) require numeric `127.0.0.1:<port>` with no paths, queries, credentials, redirects, or system proxies.
   - Optional cloud providers (`cloudprovider.py`) are excluded from the allowlist unless explicitly enabled AND configured, and require per-request user confirmation.

3. **Human Confirmation & Lockdown (`jarvis/skills.py`, `jarvis/brain.py`)**
   - Risky skills (file modifications, code/test/build execution, web searches, GitHub reads/writes, cloud prompts, calls/texts/emails, power controls) ALWAYS require explicit user approval with a human-readable preview and unique confirmation ID.
   - `skill_permissions` can disable (`off`) or require confirmation (`ask`) for any tool; risky skills can NEVER be promoted to `allowed`.
   - One-click **Lockdown** immediately blocks all risky skills, settings mutations, workflows, MCP calls, and clears pending approvals.

4. **Prompt Injection Defense (`jarvis/secure.py`)**
   - All untrusted tool outputs are wrapped in `<<<OUTSIDE CONTENT START ... OUTSIDE CONTENT END>>>` fences and scanned for injection patterns.
   - When injection is detected, any queued pending action is cleared, action-claim sentences are scrubbed from the reply, and an `injection_blocked` audit event is recorded.

5. **Workspace & Path Isolation (`jarvis/coder.py`, `jarvis/filejobs.py`, `rust/jarvis-core`)**
   - Coding edits are restricted to the selected coding workspace, forbid `..`, drive prefixes, Windows reserved device names (`CON`, `NUL`, etc.), `.git` metadata, symlinks, and directory junctions.
   - File tasks operate strictly inside explicitly selected `file_folders` (isolated from `code_dir`), never overwrite existing files, use atomic journals, and support verified undo.

6. **Credential Storage & Redaction (`jarvis/secure.py`, `jarvis/memory.py`)**
   - API keys, tokens, calendar links, and passwords are encrypted with Windows DPAPI (`CryptProtectData`) bound to the current Windows user in `%APPDATA%\Jarvis\secrets.bin` and never written to `config.json`.
   - Card numbers, SSNs, and password/token patterns are redacted before writing to conversation history, remembered facts, workflow templates, or GitHub issue drafts.

7. **Sentinel Local Audit (`jarvis/sentinel.py`)**
   - Run `python -m jarvis security-audit` or open **Sentinel security & MCP** in the HUD to inspect local security posture, blocked audit events, active extensions/MCP servers, and Finance/Health domain boundaries.
   - Strictly defensive and local-only. Never disables Windows Defender, adds AV exclusions, or targets unauthorized systems.

## Known Security Boundaries & Limitations

- Extensions and local stdio MCP servers run as the current Windows user without an OS AppContainer/VM sandbox. Only enable extensions and MCP servers you trust.
- Release packages and PowerShell scripts are not Authenticode code-signed yet; verify downloads via `SHA256SUMS.txt`. See [WindowsDefender.md](WindowsDefender.md).
- SQLite backups in `%APPDATA%\Jarvis\backups\` are local unencrypted files; keep them private.
