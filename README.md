# J.A.R.V.I.S. — your offline personal assistant

A movie-style AI assistant that runs entirely on your own PC. The brain (`qwen3:8b`),
speech, voice, memory and planner are all local. It works with the internet unplugged,
and it's built to pair with [Project NOMAD](https://www.projectnomad.us).

## Screenshots

| Boot sequence | HUD | Confirmation banner |
|---|---|---|
| ![Boot sequence](docs/screenshots/boot.png) | ![Jarvis HUD](docs/screenshots/hud.png) | ![Confirmation banner](docs/screenshots/confirm.png) |

## What it does

**Keeps your week on track**
- Reads Canvas through your private calendar-feed link, so no API key is needed. It keeps
  a copy, so it still works offline.
- Tasks, a calendar, and "plan my week": it fits study blocks into your free time before
  every deadline, and tells you when there isn't enough time.
- A watchdog that runs in the background: a daily briefing, deadline warnings 24 hours
  and 3 hours ahead, heads-ups before events, and reminders.
- "What's falling behind?" shows anything overdue, due soon, or not planned yet.
- Exports everything to an `.ics` file for Google or Outlook calendar.

**Acts on your behalf, but safely**
- Email: Jarvis writes it and opens it in your mail app, and you press Send. Direct
  sending is optional.
- Calls and texts go through Windows Phone Link on your own phone. Jarvis can write
  talking points before a call.
- Contacts, so "text Mom" just works.

**Codes**
- Writes and fixes source files in `Documents\Jarvis Code` using a local Ollama coding model.
- Checks generated Python syntax before saving and keeps the previous version in a `.bak` file.
- Ask “Preview the fix for budget.py so it handles an empty input file.” Jarvis shows a proposed
  diff without saving it. A later edit request generates a fresh change.
- Runs supported files only after confirmation. The syntax check does not execute code.

**Project NOMAD**
- Searches NOMAD's offline library (Wikipedia, medical, repair guides).
- Opens NOMAD's maps, Khan Academy, notes and other services.
- Shows NOMAD's status on the HUD.

**Feels like the movies**
- Boot sequence, arc-reactor HUD, live CPU/GPU/RAM gauges, today's schedule, deadlines.
- Say "Jarvis" anywhere in a sentence, ask follow-ups, and it understands the
  conversation in the room. A British voice is used if Windows has one.

## Security
- **Nothing happens without your "yes":** calls, texts, sending email, running code,
  shutting down, and emptying the Recycle Bin all show exactly what will happen and wait
  for you to say yes or click Confirm.
- **Hidden-instruction protection:** text from files, Canvas and the library is fenced
  off. If it tries to give Jarvis orders, code (not the AI) blocks it and warns you.
- **Encrypted secrets:** your Canvas link, token and email password are locked to your
  Windows account (DPAPI). They're never stored in plain text.
- **This PC only:** the HUD listens only on 127.0.0.1, needs a per-session key, and
  rejects other websites and spoofed hosts.
- **Code workspace:** Jarvis confines its file editing tools to the configured code
  folder. Python and JavaScript runs have a 60-second timeout.
- **Audit log:** every outside action is recorded in `%APPDATA%\Jarvis\actions.log`.
- Passwords, card numbers and SSNs are scrubbed before anything is saved to memory.
- Offline by default. Internet tools are off unless you turn them on, and every outbound
  request goes through a fail-closed central allowlist.
- **Lockdown mode & per-skill permissions:** one-click **Lockdown** button on the HUD
  disables all risky skills immediately; `skill_permissions` in `config.json` can disable
  or require confirmation for any skill (risky skills can never bypass confirmation).
- **Execution limits:** outbound calls, texts, and emails are rate-limited. For Python
  and JavaScript runs, Jarvis strips environment variables, blocks common networking
  APIs, and attempts to apply Windows Job Object limits. Approved scripts run under
  your Windows account with its permissions. Review generated code before running it.

## License

Licensed under the [Apache License 2.0](LICENSE).

## Install (once)
```
powershell -ExecutionPolicy Bypass -File install.ps1
```
Keep this folder at a short path such as `Documents\Jarvis`. Windows can't load
some of the voice libraries from very long paths.

## Use
| Command | What it does |
|---|---|
| `Jarvis.bat` | Voice plus the HUD |
| `Jarvis.bat setup` | Your name, Canvas link, email (encrypted) |
| `Jarvis.bat --text` | Type in the terminal |
| `Jarvis.bat doctor` | Check everything |
| `Jarvis.bat briefing` | Hear today's briefing |

Try saying: "Jarvis, plan my week." "What's falling behind?" "Email Professor Lee
asking to move our meeting to Thursday afternoon." "Text Mom I'll be home at 6."
"Write a Python script that renames my photos by date." "Look up how to treat a
sprain in the library."

**Connecting Canvas:** in Canvas open **Calendar**, click **Calendar Feed** (bottom
right), copy the link, and paste it into `Jarvis.bat setup`.

**Phone calls and texts:** set up the **Phone Link** app with your phone once.

**Project NOMAD on another machine:** set `nomad_url` in
`%APPDATA%\Jarvis\config.json` to that machine's address. In NOMAD's Command Center
you can add a link tile pointing to `http://127.0.0.1:8765`.

## Inspired by (ideas re-implemented, no code copied)
[CS50 Jarvis](https://github.com/diegofcn/Jarvis-CS50-Final-Project) ·
[OpenJarvis](https://github.com/open-jarvis/OpenJarvis) ·
[isair/jarvis](https://github.com/isair/jarvis) ·
[PersonalJarvis](https://github.com/tbckdev/PersonalJarvis) ·
[OpenDex](https://github.com/wassgha/opendex) ·
[Project NOMAD](https://github.com/Crosstalk-Solutions/project-nomad)
