"""Start Jarvis.

    python -m jarvis            voice + on-screen HUD (default)
    python -m jarvis --text     chat in this terminal
    python -m jarvis setup      your name, Canvas, email (secrets are encrypted)
    python -m jarvis doctor     check that everything is installed
    python -m jarvis briefing   speak a briefing and exit
"""
import argparse
import datetime as dt
import getpass
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import config, nomad, planner, secure, skills
from .brain import Brain
from .memory import Memory


class App:
    def __init__(self, cfg, use_voice=True):
        from .webui import EventBus
        self.cfg = cfg
        self.bus = EventBus()
        self.memory = Memory()
        self.brain = Brain(cfg, self.memory)
        self._settings_lock = threading.Lock()
        self.memory.embed = self.brain.embed
        self.brain.ctx.on_pending = lambda p: self.emit(
            "pending", {"text": p["preview"], "id": p["id"]} if p else None)
        self.speaker = None
        self.listener = None
        self.voice_error = ""
        self.status = "idle"
        self._sys_cache = (0, {})
        self._nomad_cache = (0, {})
        try:
            from .voice import Speaker
            self.speaker = Speaker(cfg)
        except Exception as e:
            print(f"[voice] Speaker unavailable: {e}")
        if use_voice:
            threading.Thread(target=self._start_listener, daemon=True, name="listener").start()
        threading.Thread(target=self._watchdog, daemon=True, name="watchdog").start()

    # ------------------------------------------------------------ plumbing
    def emit(self, kind, data):
        if kind == "status":
            self.status = data
        self.bus.publish(kind, data)

    def notify(self, text, speak=True):
        print(f"\n[jarvis] {text}")
        self.emit("system", text)
        if speak and self.speaker and self.cfg.get("speak_replies", True) and self.cfg.get("mode") != "talk":
            self.speaker.say(text)

    def state(self):
        pending = self.brain.ctx.pending
        return {"status": self.status, "speak_replies": bool(self.cfg.get("speak_replies")),
                "mic_on": bool(self.listener and not self.listener.paused.is_set()),
                "voice_available": self.listener is not None, "voice_error": self.voice_error,
                "lockdown": bool(self.cfg.get("lockdown")),
                "internet": bool(self.cfg.get("allow_internet_tools")),
                "web_search": bool(self.cfg.get("allow_web_search") and secure.has_secret("brave_search_key")),
                "github_upload": bool(self.cfg.get("github_upload_repo") and secure.has_secret("github_upload_token")),
                "pending": {"text": pending["preview"], "id": pending.get("id")} if pending else None,
                "model": (self.cfg.get("coder_model") or self.cfg["model"])
                if self.cfg.get("mode") == "coding" else self.cfg["model"],
                "mode": self.cfg.get("mode", "everyday"), "theme": self.cfg.get("theme", "hud"),
                "voice_choice": self.cfg.get("voice_choice", "auto"),
                "piper_available": bool(self.cfg.get("piper_model")),
                "honorific": self.cfg.get("honorific", "sir")}

    def dashboard(self):
        now = time.time()
        if now - self._sys_cache[0] > 5:
            self._sys_cache = (now, _system_stats())
        if now - self._nomad_cache[0] > 60:
            self._nomad_cache = (now, nomad.status(self.cfg))
        data = planner.dashboard(self.memory)
        data["system"] = self._sys_cache[1]
        data["nomad"] = self._nomad_cache[1]
        data["state"] = self.state()
        return data

    def toggle(self, what):
        with self._settings_lock:
            return self._toggle(what)

    def _toggle(self, what):
        if what == "speak":
            self.cfg["speak_replies"] = not self.cfg.get("speak_replies")
            config.save(self.cfg)
        elif what == "mic" and self.listener:
            if self.listener.paused.is_set():
                self.listener.paused.clear()
            else:
                self.listener.paused.set()
        elif what == "internet":
            self.cfg["allow_internet_tools"] = not self.cfg.get("allow_internet_tools")
            config.save(self.cfg)
        elif what == "lockdown":
            self.cfg["lockdown"] = not self.cfg.get("lockdown")
            config.save(self.cfg)
            if self.cfg["lockdown"] and self.brain.ctx.pending:
                self.brain.ctx.pending = None
                self.brain.ctx.on_pending(None)
            secure.audit("lockdown_toggled", {"enabled": self.cfg["lockdown"]})
        st = self.state()
        self.emit("toggles", st)
        return st

    def set_preference(self, key, value):
        choices = {"mode": config.MODES, "theme": config.THEMES,
                   "voice_choice": ("auto", "windows", "piper")}
        if key not in choices or value not in choices[key]:
            raise ValueError("Unknown setting.")
        if key == "voice_choice" and value == "piper" and not self.cfg.get("piper_model"):
            raise ValueError("Set your local Piper voice model in Jarvis setup first.")
        with self.brain._lock, self._settings_lock:
            config.save({**self.cfg, key: value})
            self.cfg[key] = value
            if key == "mode" and value == "talk" and self.brain.ctx.pending:
                self.brain.confirm_pending(False)
            state = self.state()
        self.emit("toggles", state)
        return state

    def preview_voice(self):
        if not self.speaker:
            return {"error": "Speech is unavailable."}
        honorific = self.cfg.get("honorific") or "sir"
        self.speaker.say(f"At your service, {honorific}. Shall we get started?")
        return {"ok": True}

    def confirm(self, yes: bool, expected_id: str):
        result = self.brain.confirm_pending(yes, expected_id=expected_id)
        self.reply(result, speak=True)
        if self.speaker:
            self.speaker.wait()
        self.emit("status", "listening" if self.listener else "idle")
        return {"result": result}

    def _start_listener(self):
        try:
            from .voice import Listener
            print("[voice] Loading speech recognition (first run can take a minute)...")
            self.listener = Listener(self.cfg, self.speaker, self._on_voice, self.emit)
            self.emit("toggles", self.state())
            print(f"[voice] Listening. Say \"{self.cfg.get('name', 'Jarvis')}\" followed by what you need.")
            self.listener.run()
        except Exception as e:
            self.listener = None
            self.voice_error = str(e)
            print(f"[voice] Voice input is off: {e}")
            self.emit("system", f"Voice input is off: {e}")
            self.emit("toggles", self.state())
            self.emit("status", "idle")

    # ------------------------------------------------------------ watchdog
    def _watchdog(self):
        """Runs in the background: reminders, event heads-ups, deadline nudges,
        the daily briefing, and Canvas syncing. This is what stops things slipping."""
        time.sleep(3)
        self.greet()
        last_canvas = 0
        while True:
            try:
                for text in self.memory.pop_due_reminders():
                    self.notify(f"Reminder: {text}")
                self._event_heads_up()
                self._deadline_nudges()
                self._daily_briefing()
                if planner.canvas_configured() and time.time() - last_canvas > 3 * 3600:
                    last_canvas = time.time()
                    planner.sync_canvas_now(self.memory, self.cfg)
            except Exception as e:
                print(f"[watchdog] {e}")
            time.sleep(30)

    def _event_heads_up(self):
        lead = self.cfg.get("event_heads_up_minutes", 15) * 60
        now = time.time()
        rows = planner._q(self.memory, "SELECT id, title, start, source FROM events WHERE nudged=0 AND start>? AND start<=?",
                          (now - 60, now + lead))
        for eid, title, start, source in rows:
            planner._q(self.memory, "UPDATE events SET nudged=1 WHERE id=?", (eid,))
            mins = max(1, round((start - now) / 60))
            if source == "plan":
                self.notify(f"In {mins} minutes it's time to {title[0].lower() + title[1:]}.")
            else:
                self.notify(f"Heads up, {title} starts in {mins} minutes.")

    def _deadline_nudges(self):
        now = time.time()
        for level, window in ((1, 24 * 3600), (2, 3 * 3600)):
            rows = planner._q(self.memory, "SELECT id, title, due FROM tasks WHERE status='open' AND due>? AND due<=? "
                                           "AND nudged<?", (now, now + window, level))
            for tid, title, due in rows:
                planner._q(self.memory, "UPDATE tasks SET nudged=? WHERE id=?", (level, tid))
                self.notify(f"{self._sir()}{title} is due {planner.fmt_ts(due)}. "
                            + ("Shall I find time for it?" if level == 1 else "This is your final warning."))

    def _daily_briefing(self):
        hh, mm = map(int, self.cfg.get("briefing_time", "08:00").split(":"))
        now = dt.datetime.now()
        today = now.date().isoformat()
        if now.time() >= dt.time(hh, mm) and planner.kv_get(self.memory, "last_briefing") != today:
            planner.kv_set(self.memory, "last_briefing", today)
            if now.hour < 13:
                self.notify(skills.briefing(self.brain.ctx))

    def _sir(self):
        h = self.cfg.get("honorific")
        return f"{h.capitalize()}, " if h else ""

    def greet(self):
        hour = dt.datetime.now().hour
        part = "morning" if hour < 12 else "afternoon" if hour < 18 else "evening"
        r = planner.behind_report(self.memory)
        extra = ""
        if r["overdue"]:
            extra = f" {len(r['overdue'])} item{'s are' if len(r['overdue']) > 1 else ' is'} overdue."
        elif r["soon"]:
            extra = f" You have {len(r['soon'])} deadline{'s' if len(r['soon']) > 1 else ''} in the next 48 hours."
        h = self.cfg.get("honorific")
        self.notify(f"Good {part}{', ' + h if h else ''}. All systems are online.{extra}")

    # ------------------------------------------------------------ conversation
    def _on_voice(self, command, room_context):
        if not command:  # only the name was said
            self.reply(f"Yes, {self.cfg.get('honorific') or 'sir'}?", speak=True)
            if self.speaker:
                self.speaker.wait()
            self.listener.keep_listening_for_follow_up()
            return
        self.handle(command, room_context, "voice")

    def handle(self, text, room_context="", via="typed"):
        self.emit("user", {"text": text, "via": via})
        self.emit("status", "thinking")
        switch = re.fullmatch(r"(?:jarvis[, :]+)?(?:switch to|turn on|use) (everyday|coding|briefing|talk)(?: mode)?[.!?]?",
                              text.strip(), re.IGNORECASE)
        if switch:
            mode = switch[1].lower()
            try:
                self.set_preference("mode", mode)
                answer = f"{mode.title()} mode, {self.cfg.get('honorific') or 'sir'}."
            except OSError:
                answer = "I couldn't save that setting."
        else:
            answer = self.brain.ask(text, room_context)
        self.reply(answer, speak=(via == "voice" or self.cfg.get("speak_replies")))
        if self.speaker:
            self.speaker.wait()
        if via == "voice" and self.listener:
            self.listener.keep_listening_for_follow_up()
        self.emit("status", "listening" if self.listener else "idle")
        return answer

    def reply(self, text, speak):
        self.emit("reply", text)
        if speak and self.speaker and self.cfg.get("speak_replies", True):
            self.emit("status", "speaking")
            spoken = text
            if spoken.startswith(("Preview only.", "Proposed edit for", "Brave search results.")):
                spoken = (spoken.split("\n", 1)[0] if not spoken.startswith("Brave") else
                          "I've put the search results on screen.")
            elif self.cfg.get("mode") == "coding":
                spoken = spoken.split("\n\n", 1)[0].split("```", 1)[0].strip()[:350]
            self.speaker.say(spoken or "The details are on screen.")


def _system_stats():
    out = {}
    try:
        import psutil
        out["cpu"] = round(psutil.cpu_percent(interval=None))
        out["ram"] = round(psutil.virtual_memory().percent)
        bat = psutil.sensors_battery()
        if bat:
            out["battery"] = round(bat.percent)
            out["plugged"] = bool(bat.power_plugged)
    except Exception:
        pass
    if shutil.which("nvidia-smi"):
        try:
            r = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.used,memory.total",
                                "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=3,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            util, used, total = [float(x) for x in r.stdout.split("\n")[0].split(",")]
            out["gpu"] = round(util)
            out["vram"] = round(100 * used / total)
        except Exception:
            pass
    return out


# ================================================================ commands
def setup(cfg):
    print("Jarvis setup. Press Enter to keep the current value.\n")

    def ask(label, key):
        cur = cfg.get(key, "")
        val = input(f"{label} [{cur}]: ").strip()
        if val:
            cfg[key] = val

    ask("Your name (used to sign emails)", "user_name")
    ask("What should Jarvis call you (sir, ma'am, boss, your name)", "honorific")
    ask("Daily briefing time (HH:MM)", "briefing_time")
    ask("Windows voice name (try George if installed)", "sapi_voice_contains")
    ask("Optional local Piper voice model (.onnx path)", "piper_model")

    print("\nCANVAS. In Canvas open Calendar, click 'Calendar Feed' (bottom right), copy the link.")
    print(f"  Currently: {'connected' if secure.has_secret('canvas_feed_url') else 'not connected'}")
    feed = getpass.getpass("  Paste the Canvas calendar feed link (hidden, Enter to skip): ").strip()
    if feed:
        if not feed.startswith("https://") or ".ics" not in feed:
            print("  That doesn't look like a Canvas feed link (should start with https:// and contain .ics). Skipped.")
        else:
            secure.set_secret("canvas_feed_url", feed)
            print("  Saved (encrypted).")
    print("  Optional: a Canvas access token lets Jarvis see what you've already submitted.")
    print("  (Canvas > Account > Settings > New Access Token.) You can skip this.")
    tok = getpass.getpass("  Canvas access token (hidden, Enter to skip): ").strip()
    if tok:
        secure.set_secret("canvas_token", tok)
        print("  Saved (encrypted).")

    print("\nEMAIL. By default Jarvis writes emails and opens them in your mail app for you to send.")
    if input("  Also let Jarvis send emails directly after you say yes? (y/N): ").strip().lower() == "y":
        print("  For Gmail: turn on 2-step verification, then create an App Password at")
        print("  https://myaccount.google.com/apppasswords and use that here (not your real password).")
        user = input("  Your email address: ").strip()
        host = input("  SMTP server [smtp.gmail.com]: ").strip() or "smtp.gmail.com"
        pw = getpass.getpass("  App password (hidden): ").strip()
        if user and pw:
            secure.set_secret("smtp_user", user)
            secure.set_secret("smtp_host", host)
            secure.set_secret("smtp_password", pw)
            print("  Saved (encrypted).")
    print("\nONLINE TOOLS. Jarvis starts offline. Configure only the services you want to use.")
    brave = getpass.getpass("  Brave Search API key (hidden, Enter to keep current): ").strip()
    if brave:
        secure.set_secret("brave_search_key", brave)
        cfg["allow_web_search"] = True
        cfg["allow_internet_tools"] = True
    ask("GitHub upload repository (owner/repo)", "github_upload_repo")
    if cfg.get("github_upload_repo"):
        ask("GitHub upload branch", "github_upload_branch")
        token = getpass.getpass("  GitHub token for that repository (hidden, Enter to keep current): ").strip()
        if token:
            secure.set_secret("github_upload_token", token)
            cfg["allow_internet_tools"] = True
    config.save(cfg)
    print("\nDone. Your secrets are encrypted with your Windows account and never stored in config.json.")
    if secure.has_secret("canvas_feed_url"):
        m = Memory()
        Brain(cfg, m)
        print(planner.sync_canvas_now(m, cfg, force=True))
    return 0


def doctor(cfg):
    ok = True

    def line(good, label, hint="", optional=False):
        nonlocal ok
        if not optional:
            ok &= good
        mark = "OK" if good else ("--" if optional else "!!")
        print(f"  [{mark}] {label}" + (f"\n        -> {hint}" if hint and not good else ""))

    print("Jarvis doctor\n")
    brain = Brain(cfg, Memory())
    try:
        models = brain.installed_models()
        line(True, f"Ollama is running ({len(models)} models installed)")
        has = lambda m: any(x == m or x == m + ":latest" for x in models)
        line(has(cfg["model"]), f"Brain model {cfg['model']}", f"run: ollama pull {cfg['model']}")
        line(has(cfg["coder_model"]), f"Coding model {cfg['coder_model']}", f"run: ollama pull {cfg['coder_model']}",
             optional=True)
        line(has(cfg["embed_model"]), f"Memory model {cfg['embed_model']}", f"run: ollama pull {cfg['embed_model']}",
             optional=True)
    except Exception as e:
        line(False, "Ollama is running", f"start the Ollama app ({e})")
    for mod, label in [("faster_whisper", "Speech recognition"), ("sounddevice", "Microphone access"),
                       ("pyttsx3", "Text to speech"), ("psutil", "System monitor")]:
        try:
            __import__(mod)
            line(True, label)
        except Exception as e:
            line(False, label, str(e))
    try:
        import sounddevice as sd
        line(True, f"Microphone: {sd.query_devices(kind='input')['name']}")
    except Exception as e:
        line(False, "Microphone found", str(e))
    line(secure.has_secret("canvas_feed_url"), "Canvas connected", "run: Jarvis.bat setup", optional=True)
    line(secure.has_secret("smtp_password"), "Direct email sending", "optional; drafts work without it", optional=True)
    st = nomad.status(cfg)
    found = st["command center"] or st["library"]
    line(found, "Project NOMAD reachable" + (f" ({', '.join(k for k, v in st.items() if v)})" if found else ""),
         "install NOMAD or set nomad_url in config.json", optional=True)
    print(f"\n  Offline mode: {'OFF' if cfg.get('allow_internet_tools') else 'ON'}")
    print(f"  Settings: {config.CONFIG_PATH}")
    print(f"  Action log: {secure.AUDIT_PATH}")
    print(f"  Skills loaded: {len(skills.SKILLS)}")
    print("\nAll good." if ok else "\nFix the items marked !! above.")
    return 0 if ok else 1


def text_chat(app):
    name = app.cfg.get("name", "Jarvis")
    print(f"{name} is ready. Type your message (or 'quit').\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if text.lower() in ("quit", "exit", "bye"):
            break
        if text:
            print(f"{name}: {app.handle(text)}\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="jarvis", description="Offline personal assistant")
    p.add_argument("command", nargs="?", default="run", choices=["run", "doctor", "briefing", "setup"])
    p.add_argument("--text", action="store_true", help="chat in the terminal instead of by voice")
    p.add_argument("--no-voice", action="store_true", help="don't use the microphone")
    p.add_argument("--mode", choices=config.MODES, help="Start in this mode")
    p.add_argument("--theme", choices=config.THEMES, help="Start with this theme")
    p.add_argument("--no-browser", action="store_true", help="don't open the HUD window")
    args = p.parse_args(argv)
    cfg = config.load()
    if args.mode:
        cfg["mode"] = args.mode
    if args.theme:
        cfg["theme"] = args.theme
    elif args.mode == "talk":
        cfg["theme"] = "simple"

    if args.command == "doctor":
        return doctor(cfg)
    if args.command == "setup":
        return setup(cfg)
    if args.command == "briefing":
        m = Memory()
        b = Brain(cfg, m)
        text = skills.briefing(b.ctx)
        print(text)
        try:
            from .voice import Speaker
            s = Speaker(cfg)
            s.say(text)
            s.wait()
        except Exception:
            pass
        return 0
    if args.text:
        cfg["speak_replies"] = False
        text_chat(App(cfg, use_voice=False))
        return 0

    from .webui import serve
    app = App(cfg, use_voice=not args.no_voice)
    port = cfg.get("web_port", 8765)
    serve(app, port)
    url = f"http://127.0.0.1:{port}"
    print(f"Jarvis HUD: {url}   (Ctrl+C to quit)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("Goodbye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
