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
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser

from . import appactions, assistants, config, documents, extensions, filejobs, images, net, nomad, planner, recovery, secure, setupwizard, skills, watchchecks
from .brain import Brain
from .memory import Memory


class App:
    def __init__(self, cfg, use_voice=True):
        from .webui import EventBus
        self.cfg = cfg
        self.bus = EventBus()
        self.memory = Memory()
        watchchecks.init_db(self.memory)
        self.brain = Brain(cfg, self.memory)
        self._settings_lock = threading.Lock()
        self._turn_lock = threading.Lock()
        self._stream_spoken = 0
        self._allow_stream_speech = False
        self.brain.on_stream = self._stream_reply
        self.brain.on_metrics = lambda values: self.emit("metrics", values)
        self._image_job = threading.Lock()
        self.brain.ctx.on_images = lambda cards: self.emit("image_results", cards)
        self.memory.embed = self.brain.embed
        try:
            extensions.register(cfg)
        except Exception as error:  # A broken extension folder must not stop Jarvis.
            print(f"[extensions] {error}")
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
                "image_generator": bool(net.local_image_endpoint(self.cfg.get("image_generation_url"))),
                "github_upload": bool(self.cfg.get("github_upload_repo") and secure.has_secret("github_upload_token")),
                "pending": {"text": pending["preview"], "id": pending.get("id")} if pending else None,
                "model": (self.cfg.get("coder_model") or self.cfg["model"])
                if self.cfg.get("mode") == "coding" else self.cfg["model"],
                "mode": self.cfg.get("mode", "everyday"), "theme": self.cfg.get("theme", "hud"),
                "assistant": self.cfg.get("assistant", "auto"),
                "voice_choice": self.cfg.get("voice_choice", "auto"),
                "tuki_voice_choice": self.cfg.get("tuki_voice_choice", "auto"),
                "tuki_piper_available": bool(self.cfg.get("tuki_piper_model")),
                "piper_available": bool(self.cfg.get("piper_model")),
                "honorific": self.cfg.get("honorific", "sir"),
                "first_run": not self.cfg.get("setup_complete")}

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

    def activity_operation(self):
        return secure.recent_activity()

    def toggle(self, what):
        with self._settings_lock:
            return self._toggle(what)

    def _toggle(self, what):
        if what == "speak":
            self.cfg["speak_replies"] = not self.cfg.get("speak_replies")
            config.save(self.cfg)
        elif what == "mic" and self.listener:
            if self.listener.paused.is_set():
                self.listener.resume()
            else:
                self.listener.pause()
                self.emit("heard", "")
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
        choices = {"mode": config.MODES, "theme": config.THEMES, "assistant": assistants.CHOICES,
                   "voice_choice": config.VOICE_CHOICES, "tuki_voice_choice": config.VOICE_CHOICES}
        if key not in choices or value not in choices[key]:
            raise ValueError("Unknown setting.")
        if key == "voice_choice" and value == "piper" and not self.cfg.get("piper_model"):
            raise ValueError("Set your local Piper voice model in Jarvis setup first.")
        if key == "tuki_voice_choice" and value == "piper" and not self.cfg.get("tuki_piper_model"):
            raise ValueError("Set TUKI's Piper voice model in setup first.")
        with self.brain._lock, self._settings_lock:
            config.save({**self.cfg, key: value})
            self.cfg[key] = value
            if key == "mode" and value == "talk" and self.brain.ctx.pending:
                self.brain.confirm_pending(False)
            state = self.state()
        self.emit("toggles", state)
        return state

    def image_operation(self, kind, data):
        if self.cfg.get("mode") == "talk" or self.cfg.get("lockdown"):
            raise ValueError("Image tools are unavailable in Talk or Lockdown.")
        if not self._image_job.acquire(blocking=False):
            raise ValueError("An image task is already running.")
        try:
            if kind == "lookup":
                if data.get("source") == "screen":
                    # The user chose and previewed this capture. Record that it was sent, not its content.
                    secure.audit("screen_capture_described", {"question_chars": len(str(data.get("question") or ""))})
                return images.describe(self.cfg, data.get("image"), data.get("question"))
            return images.generate(self.cfg, data.get("prompt"), data.get("quality"))
        finally:
            self._image_job.release()

    def stop(self):
        self.brain.cancelled.set()
        if self.speaker:
            self.speaker.stop()
        self.brain.ctx.pending = None
        self.emit("pending", None)
        self.emit("stream", "")
        return {"ok": True}

    def _stream_reply(self, text):
        self.emit("stream", text)
        if self._allow_stream_speech and self.speaker and not self.brain.cancelled.is_set():
            # Speech starts early only in Talk mode, which has no action tools.
            tail = text[self._stream_spoken:]
            for sentence in re.finditer(r".+?[.!?](?:\s+|$)", tail, re.S):
                self.speaker.say(sentence[0], self.brain.assistant)
                self._stream_spoken += len(sentence[0])

    def settings_operation(self, data=None):
        with self.brain._lock, self._settings_lock:
            if data is not None:
                if self.cfg.get("lockdown"):
                    raise ValueError("Turn off Lockdown to change setup.")
                from pathlib import Path
                updated = dict(self.cfg)
                if "profile" in data:
                    updated = config.apply_profile(updated, data["profile"])
                if "document_folders" in data:
                    folders = data["document_folders"]
                    if not isinstance(folders, list) or len(folders) > 20 or any(
                        not isinstance(item, str) or not item.strip() for item in folders
                    ):
                        raise ValueError("Enter up to 20 folder paths, one per line.")
                    folders = [str(Path(item).expanduser().resolve()) for item in folders]
                    if any(not Path(item).is_dir() for item in folders):
                        raise ValueError("Every selected document folder must exist.")
                    updated["document_folders"] = folders
                if "file_folders" in data:
                    updated = setupwizard.apply_choices(updated, {"file_folders": data["file_folders"]})
                if "ocr_enabled" in data:
                    updated["ocr_enabled"] = bool(data["ocr_enabled"])
                if "document_index_enabled" in data:
                    if type(data["document_index_enabled"]) is not bool:
                        raise ValueError("Choose whether to enable the local document index.")
                    updated["document_index_enabled"] = data["document_index_enabled"]
                for key, limit in config.VOICE_LIMITS.items():
                    if key in data:
                        value = data[key]
                        if type(value) is not int or not 0 <= value <= limit:
                            raise ValueError(f"Invalid {key} option.")
                        updated[key] = value
                if (not updated["document_index_enabled"] or
                    updated.get("document_folders") != self.cfg.get("document_folders") or
                    updated.get("ocr_enabled") != self.cfg.get("ocr_enabled")):
                    from . import docindex
                    docindex.delete()
                config.save(updated)
                self.cfg.update(updated)
                if self.listener and not updated["room_context_seconds"]:
                    self.listener.clear_context()
            return {"profile": self.cfg.get("performance_profile", "standard"),
                    "document_folders": self.cfg.get("document_folders", []),
                    "file_folders": self.cfg.get("file_folders", []),
                    "ocr_enabled": bool(self.cfg.get("ocr_enabled")),
                    "document_index_enabled": bool(self.cfg.get("document_index_enabled")),
                    "follow_up_seconds": self.cfg.get("follow_up_seconds", 8),
                    "room_context_seconds": self.cfg.get("room_context_seconds", 120),
                    "ocr_available": bool(documents.tesseract_path({**self.cfg, "ocr_enabled": True})),
                    "model": self.cfg["model"], "coder_model": self.cfg.get("coder_model")}

    def recovery_operation(self, data=None):
        with self.brain._lock:
            result = {}
            if data is not None:
                if self.cfg.get("lockdown"):
                    raise ValueError("Turn off Lockdown to use recovery actions.")
                if data.get("action") == "backup":
                    result["saved"] = recovery.backup(self.memory)
                elif data.get("action") == "restore" and data.get("confirmed") is True:
                    result["rescue_backup"] = recovery.restore(self.memory, data.get("name"))
                    self.brain.history = self.memory.recent_messages(self.cfg.get("history_turns", 10))
                    self.brain.ctx.pending = None
                    self.brain.ctx.code_proposal = None
                    self.brain.ctx.applied_code = None
                    self.emit("pending", None)
                else:
                    raise ValueError("Choose Backup or confirm a selected restore.")
            return {**result, "backups": recovery.list_backups()}

    def watches_operation(self, data=None):
        if data is None:
            return watchchecks.list_watches(self.memory)
        if data.get('action') == 'add':
            if not self.cfg.get('document_folders'):
                raise ValueError('Choose document folders in Setup first.')
            if skills.permission_level(self.cfg, 'search_documents') != 'allowed':
                raise ValueError('Allow automatic document search in skill permissions first.')
        return watchchecks.operate(self.memory, data)

    def repository_operation(self, data=None):
        """Explicitly grant one existing local Git repository as the coding workspace."""
        from pathlib import Path
        from . import coder
        with self.brain._lock, self._settings_lock:
            if data is not None:
                if self.cfg.get('lockdown'):
                    raise ValueError('Turn off Lockdown to change the coding workspace.')
                if data.get('action') not in ('select', 'reset'):
                    raise ValueError('Choose select or reset.')
                if data['action'] == 'select':
                    value = data.get('path')
                    if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                        raise ValueError('Enter an existing local repository folder.')
                    path = Path(value).expanduser()
                    if not path.is_absolute() or not path.is_dir() or path.is_symlink() or getattr(os.path, 'isjunction', lambda p: False)(path):
                        raise ValueError('Choose an existing absolute repository folder, not a link.')
                    path = path.resolve()
                    marker = path / '.git'
                    if not marker.is_dir() and not (marker.is_file() and marker.stat().st_size < 1000 and
                                                    marker.read_text(encoding='utf-8', errors='replace').startswith('gitdir: ')):
                        raise ValueError('This folder is not a Git repository or worktree.')
                    for item in self.cfg.get('file_folders', []):
                        other = Path(item).resolve()
                        if path == other or path in other.parents or other in path.parents:
                            raise ValueError('Keep the coding repository separate from file-task folders.')
                else:
                    path = Path(config.DEFAULTS['code_dir']).expanduser().resolve()
                if str(path) != str(coder.code_dir(self.cfg).resolve()):
                    coder.preserve_legacy_undo(self.brain.ctx)
                    config.save({**self.cfg, 'code_dir': str(path)})
                    self.cfg['code_dir'] = str(path)
                    self.brain.ctx.code_proposal = None
                    self.brain.ctx.applied_code = None
                    self.brain.ctx.last_test_output = ''
                    self.brain.ctx.last_test_root = ''
                    self.brain.ctx.last_test_file = ''
                    self.brain.ctx.pending = None
                    self.brain.ctx.on_pending(None)
            root = coder.code_dir(self.cfg).resolve()
            summary = coder.project_context(self.cfg, root)
            return {'path': str(root), 'is_repository': (root / '.git').exists(), **summary}

    def memory_operation(self, data=None):
        with self.brain._lock:
            if data is not None:
                if self.cfg.get("lockdown"):
                    raise ValueError("Turn off Lockdown to change remembered facts.")
                if data.get("action") == "clear_history" and data.get("confirmed") is True:
                    with self.memory._lock, self.memory.db:
                        self.memory.db.execute("DELETE FROM messages")
                    self.brain.history = []
                    return {"facts": [{"id": key, "text": text} for key, text in self.memory.all_facts()]}
                fact_id = data.get("id")
                if type(fact_id) is not int or fact_id < 1:
                    raise ValueError("Choose a remembered fact.")
                if data.get("action") == "edit":
                    changed = self.memory.edit_fact(fact_id, data.get("text"))
                elif data.get("action") == "delete" and data.get("confirmed") is True:
                    changed = self.memory.delete_fact(fact_id)
                else:
                    raise ValueError("Choose Edit or confirm deletion.")
                if not changed:
                    raise ValueError("This remembered fact has already been removed. Refresh the list.")
            return {"facts": [{"id": key, "text": text} for key, text in self.memory.all_facts()]}

    def files_operation(self, data):
        """Selected-folder file tasks for the HUD. Changes always go through a confirmation."""
        action = data.get("action")
        if self.cfg.get("mode") == "talk" or self.cfg.get("lockdown"):
            raise ValueError("File tasks are unavailable in Talk or Lockdown.")
        if action == "roots":
            return {"roots": [str(root) for root in filejobs.folder_roots(self.cfg)],
                    "limits": filejobs.LIMITS_TEXT}
        index = data.get("root", 0)
        if action == "browse":
            return filejobs.browse(self.cfg, index, data.get("path", ""))
        if action == "search":
            return filejobs.search(self.cfg, index, data.get("query"), data.get("path", ""))
        with self.brain._lock:
            ctx = self.brain.ctx
            if action == "jobs":
                return {"jobs": [{"id": job["id"], "state": job["state"], "action": job["action"],
                                  "root": job["root"], "steps": len(job["steps"]),
                                  "done": sum(step["state"] == "done" for step in job["steps"]),
                                  "error": next((step.get("error") for step in job["steps"] if step.get("error")), ""),
                                  "summary": filejobs.describe_steps(job["steps"], limit=5)}
                                 for job in filejobs.folder_jobs(ctx)]}
            if action == "prepare":
                spec = data.get("spec") or {}
                if not isinstance(spec, dict):
                    raise ValueError("Expected file task details.")
                result = filejobs.prepare_folder_task(ctx, index, data.get("task"), spec)
                result["pending"] = {"text": ctx.pending["preview"], "id": ctx.pending["id"]} if ctx.pending else None
                return result
            if action in ("resume", "undo"):
                tool = "execute_folder_job" if action == "resume" else "undo_folder_job"
                message = skills.run(ctx, tool, {"job_id": data.get("job_id")})
                return {"message": message,
                        "pending": {"text": ctx.pending["preview"], "id": ctx.pending["id"]} if ctx.pending else None}
        raise ValueError("Unknown file task action.")

    def apps_operation(self, data=None):
        """Approved app actions. Running one always goes through the confirmation banner."""
        if data is None:
            return {"actions": appactions.actions(self.cfg), "running": appactions.running(),
                    "roots": [str(root) for root in filejobs.folder_roots(self.cfg)]}
        action = data.get("action")
        if action == "stop":
            return {"stopped": appactions.stop_all(), "running": appactions.running()}
        if self.cfg.get("lockdown") or self.cfg.get("mode") == "talk":
            raise ValueError("App actions are unavailable in Talk or Lockdown.")
        with self.brain._lock, self._settings_lock:
            if action == "save":
                items = data.get("actions")
                if not isinstance(items, list):
                    raise ValueError("Expected a list of app actions.")
                appactions.save_actions(self.cfg, items)
                return self.apps_operation()
            if action == "run":
                ctx = self.brain.ctx
                message = skills.run(ctx, "run_app_action", {"name": str(data.get("name", "")),
                                                            "file": str(data.get("file", ""))})
                return {"message": message,
                        "pending": {"text": ctx.pending["preview"], "id": ctx.pending["id"]} if ctx.pending else None}
        raise ValueError("Choose save, run or stop.")

    def extensions_operation(self, data=None):
        if data is None:
            return {"extensions": extensions.status(self.cfg), "folder": str(extensions.folder()),
                    "permissions": extensions.PERMISSIONS}
        if self.cfg.get("lockdown"):
            raise ValueError("Turn off Lockdown to change extensions.")
        ext_id = str(data.get("id", ""))
        with self.brain._lock, self._settings_lock:
            if data.get("action") == "enable":
                rows = extensions.set_enabled(self.cfg, ext_id, True, data.get("permissions"))
            elif data.get("action") == "disable":
                rows = extensions.set_enabled(self.cfg, ext_id, False)
            elif data.get("action") == "test":
                passed, failed, details = extensions.run_tests(self.cfg, ext_id)
                return {"passed": passed, "failed": failed, "details": details}
            else:
                raise ValueError("Choose enable, disable or test.")
        return {"extensions": rows}

    def wizard_operation(self, data=None):
        """First-run setup wizard. GET returns status; POST saves choices or starts downloads."""
        if data is None:
            return setupwizard.summary(self.cfg)
        if self.cfg.get("lockdown"):
            raise ValueError("Turn off Lockdown to change setup.")
        action = data.get("action")
        choices = data.get("choices") or {}
        if not isinstance(choices, dict):
            raise ValueError("Expected setup choices.")
        if action == "plan":
            return setupwizard.plan(self.cfg, choices)
        with self.brain._lock, self._settings_lock:
            if action == "start":
                setupwizard.start(self.cfg, choices)
            elif action == "finish":
                setupwizard.finish_without_downloads(self.cfg, choices)
            else:
                raise ValueError("Choose plan, start or finish.")
        self.emit("toggles", self.state())
        return setupwizard.summary(self.cfg)

    def preview_voice(self, assistant="jarvis"):
        if not self.speaker:
            return {"error": "Speech is unavailable."}
        if assistant == "tuki":
            text = f"{assistants.TUKI_NAME} here. I check sources, maths and code, and I say when I'm unsure."
        else:
            assistant = "jarvis"
            honorific = self.cfg.get("honorific") or "sir"
            text = f"At your service, {honorific}. Shall we get started?"
        self.speaker.say(text, assistant)
        describe = getattr(self.speaker, "describe", None)
        return {"ok": True, "voice": describe(assistant) if describe else ""}

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
                watchchecks.run_due(self.memory, self.cfg, lambda message: self.notify(message, speak=False))
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

    def submit_request(self, text):
        if text.strip().casefold().rstrip('.!?') in ("stop", "/stop", "cancel reply"):
            self.handle(text)
            return True
        if not self._turn_lock.acquire(blocking=False):
            return False
        try:
            threading.Thread(target=self._run_handle, args=(text, "", "typed"), daemon=True).start()
        except BaseException:
            self._turn_lock.release()
            raise
        return True

    def handle(self, text, room_context="", via="typed"):
        if text.strip().casefold().rstrip('.!?') in ("stop", "/stop", "cancel reply"):
            self.stop()
            self.emit("system", "Stop requested. Any completed actions remain in task history.")
            return "Stop requested."
        if not self._turn_lock.acquire(blocking=False):
            self.emit("system", "Jarvis is working. Use Stop before starting another request.")
            return "Jarvis is working."
        return self._run_handle(text, room_context, via)

    def _run_handle(self, text, room_context, via):
        try:
            self._stream_spoken = 0
            self._allow_stream_speech = bool(self.cfg.get("mode") == "talk" and self.cfg.get("speak_replies"))
            return self._handle(text, room_context, via)
        finally:
            self._allow_stream_speech = False
            self.emit("stream", "")
            self.emit("status", "listening" if self.listener else "idle")
            self._turn_lock.release()

    def _handle(self, text, room_context="", via="typed"):
        self.emit("user", {"text": text, "via": via})
        self.emit("status", "thinking")
        switch = re.fullmatch(r"(?:jarvis[, :]+)?(?:switch to|turn on|use) (everyday|coding|briefing|talk)(?: mode)?[.!?]?",
                              text.strip(), re.IGNORECASE)
        assistant_switch = re.fullmatch(
            r"(?:jarvis[, :]+)?(?:switch to|use) (auto|jarvis|tuki)(?: assistant)?[.!?]?",
            text.strip(), re.IGNORECASE,
        )
        label = None
        model = None
        if assistant_switch:
            try:
                chosen = assistant_switch[1].lower()
                self.set_preference("assistant", chosen)
                answer = "Automatic routing is on." if chosen == "auto" else f"{assistants.display_name(chosen)} is selected."
            except OSError:
                answer = "I couldn't save that setting."
        elif switch:
            mode = switch[1].lower()
            try:
                self.set_preference("mode", mode)
                answer = f"{mode.title()} mode, {self.cfg.get('honorific') or 'sir'}."
            except OSError:
                answer = "I couldn't save that setting."
        else:
            with self.brain._lock:
                answer = self.brain.ask(text, room_context)
                label = assistants.display_name(self.brain.assistant)
                model = self.brain.model_used
        if self._stream_spoken and self.speaker and not self.brain.cancelled.is_set():
            self.speaker.say(answer[self._stream_spoken:], self.brain.assistant)
        self.reply(answer, speak=(not self._stream_spoken and not self.brain.cancelled.is_set() and
                                 (via == "voice" or self.cfg.get("speak_replies"))), assistant=label, model=model)
        if self.speaker:
            self.speaker.wait()
        if via == "voice" and self.listener:
            self.listener.keep_listening_for_follow_up()
        self.emit("status", "listening" if self.listener else "idle")
        return answer

    def reply(self, text, speak, assistant=None, model=None):
        self.emit("reply", {"text": text, "assistant": assistant, "model": model} if assistant else text)
        if speak and self.speaker and self.cfg.get("speak_replies", True):
            self.emit("status", "speaking")
            spoken = text
            if spoken.startswith(("Preview only.", "Proposed edit for", "Brave search results.", "Fact-check based")):
                spoken = (spoken.split("\n", 1)[0] if not spoken.startswith(("Brave", "Fact-check")) else
                          "I've put the search results on screen.")
            elif self.cfg.get("mode") == "coding":
                spoken = spoken.split("\n\n", 1)[0].split("```", 1)[0].strip()[:350]
            voice = "tuki" if assistant == assistants.TUKI_NAME else "jarvis"
            self.speaker.say(spoken or "The details are on screen.", voice)


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

    profile = input("Performance profile [Enter to keep current, standard, low-memory]: ").strip()
    if profile:
        updated = config.apply_profile(cfg, profile)
        config.save(updated)
        cfg.update(updated)
        print("Profile saved. Run install.ps1 -Profile " + profile + " to download its models.")

    folders = input("Document search folders (separate paths with |, Enter to keep, 'clear' to remove): ").strip()
    if folders:
        from pathlib import Path
        selected = [] if folders.casefold() == "clear" else [
            str(Path(value.strip()).expanduser().resolve()) for value in folders.split("|") if value.strip()
        ]
        if all(Path(value).is_dir() for value in selected):
            cfg["document_folders"] = selected
        else:
            print("One or more document folders do not exist. Current selection kept.")

    ask("Your name (used to sign emails)", "user_name")
    ask("What should Jarvis call you (sir, ma'am, boss, your name)", "honorific")
    ask("Daily briefing time (HH:MM)", "briefing_time")
    ask("Windows voice name (try George if installed)", "sapi_voice_contains")
    ask("Optional local Piper voice model (.onnx path)", "piper_model")
    ask("TUKI Windows voice name (try Zira or Aria; blank picks a different voice)", "tuki_sapi_voice_contains")
    ask("Optional Piper voice model for TUKI (.onnx path)", "tuki_piper_model")
    ask("Local vision model (optional, pull it in Ollama first)", "vision_model")
    ask("Local image generation API URL (optional, loopback only)", "image_generation_url")

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
        line(has(cfg["model"]), f"{assistants.TUKI_NAME} model {cfg['model']}", f"run: ollama pull {cfg['model']}")
        everyday = cfg.get("everyday_model") or cfg["model"]
        line(has(everyday), f"Jarvis model {everyday}", f"run: ollama pull {everyday}", optional=True)
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
    line(secure.has_secret("canvas_feed_url"), "Canvas connected", "run: .venv\\Scripts\\python.exe -m jarvis setup", optional=True)
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


def voice_check(cfg):
    """Exercise real input, transcription and output without storing the recording."""
    print("Jarvis voice check: a four-second microphone sample stays on this PC.")
    try:
        input("Press Enter when ready to speak (Ctrl+C to cancel): ")
    except (EOFError, KeyboardInterrupt):
        print("\nVoice check cancelled.")
        return 1
    try:
        import sounddevice as sd
        from .voice import RATE, Speaker, load_whisper

        audio = sd.rec(4 * RATE, samplerate=RATE, channels=1, dtype="float32")
        sd.wait()
        model = load_whisper(cfg)
        segments, _ = model.transcribe(audio[:, 0], language="en", beam_size=1,
                                        vad_filter=False, condition_on_previous_text=False)
        heard = " ".join(part.text for part in segments if part.no_speech_prob < 0.7).strip()
        if not heard:
            print("No speech recognized. Check the input device and microphone permission.")
            return 1
        print(f"Recognized: {heard}")
        print("Playing a test reply now.")
        speaker = Speaker(cfg)
        speaker.say("Jarvis voice check complete.")
        speaker.wait()
        print("If you heard the reply, input and output are ready. This command cannot verify audio quality.")
        return 0
    except Exception as exc:
        print(f"Voice check failed: {type(exc).__name__}: {exc}")
        return 1


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
            answer = app.handle(text)
            print(f"{assistants.display_name(app.brain.assistant)}: {answer}\n")


def main(argv=None):
    p = argparse.ArgumentParser(prog="jarvis", description="Offline personal assistant")
    p.add_argument("command", nargs="?", default="run", choices=["run", "doctor", "voice-check", "briefing", "setup"])
    p.add_argument("--text", action="store_true", help="chat in the terminal instead of by voice")
    p.add_argument("--no-voice", action="store_true", help="don't use the microphone")
    p.add_argument("--mode", choices=config.MODES, help="Start in this mode")
    p.add_argument("--theme", choices=config.THEMES, help="Start with this theme")
    p.add_argument("--no-browser", action="store_true", help="don't open the HUD window")
    p.add_argument("--profile", choices=tuple(config.PERFORMANCE_PROFILES), help="Save a performance profile")
    args = p.parse_args(argv)
    # Speech models load from the local cache only. The setup wizard downloads them in a
    # separate process. This replaces the setting that Jarvis.bat used to provide.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    cfg = config.load()
    if args.profile:
        cfg = config.apply_profile(cfg, args.profile)
        config.save(cfg)
    if args.mode:
        cfg["mode"] = args.mode
    if args.theme:
        cfg["theme"] = args.theme
    elif args.mode == "talk":
        cfg["theme"] = "simple"

    if args.command == "doctor":
        return doctor(cfg)
    if args.command == "voice-check":
        return voice_check(cfg)
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
    app = App(cfg, use_voice=not args.no_voice and cfg.get("voice_enabled", True))
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
