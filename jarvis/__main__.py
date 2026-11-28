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

from . import (
    agents, appactions, assistants, bgtasks, browser_auto, clipboard, cloudprovider, config, connections, connectors,
    desktop, documents, domains, extensions, fastpath, filejobs, hardware, images, localprovider,
    macros, mcp_client, memextract, monitors, net, nomad, planner, pro_workspace, providers, recovery, secure,
    sentinel, setupwizard, skills, telemetry, undo, watchchecks, workflows,
)
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
        workflows.init_db(self.memory)
        bgtasks.recover_interrupted(self.memory)
        monitors.init_db(self.memory)
        macros.init_db(self.memory)
        self._workflow_cancelled = threading.Event()
        self._workflow_lock = threading.Lock()
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
                "voice_input_mode": self.cfg.get("voice_input_mode", "wake"),
                "lockdown": bool(self.cfg.get("lockdown")),
                "internet": bool(self.cfg.get("allow_internet_tools")),
                "web_search": bool(self.cfg.get("allow_web_search") and secure.has_secret("brave_search_key")),
                "image_generator": bool(net.local_image_endpoint(self.cfg.get("image_generation_url"))),
                "github_upload": bool(self.cfg.get("github_upload_repo") and secure.has_secret("github_upload_token")),
                "pending": {"text": pending["preview"], "id": pending.get("id")} if pending else None,
                "model": self.cfg.get("local_chat_model") if self.cfg.get("chat_provider") == "openai_local" else
                ((self.cfg.get("coder_model") or self.cfg["model"]) if self.cfg.get("mode") == "coding" else self.cfg["model"]),
                "chat_provider": self.cfg.get("chat_provider", "ollama"),
                "mode": self.cfg.get("mode", "everyday"), "theme": self.cfg.get("theme", "hud"),
                "workspace_view": self.cfg.get("workspace_view", "classic"),
                "assistant": self.cfg.get("assistant", "auto"),
                "active_assistant": self.brain.assistant,
                "voice_choice": self.cfg.get("voice_choice", "auto"),
                "tuki_voice_choice": self.cfg.get("tuki_voice_choice", "auto"),
                "sapi_voice_contains": self.cfg.get("sapi_voice_contains", ""),
                "tuki_sapi_voice_contains": self.cfg.get("tuki_sapi_voice_contains", ""),
                "tuki_piper_available": bool(self.cfg.get("tuki_piper_model")),
                "piper_available": bool(self.cfg.get("piper_model")),
                "speech_rate": int(self.cfg.get("speech_rate", 185)),
                "tuki_speech_rate": int(self.cfg.get("tuki_speech_rate", 200)),
                "temporary_chat": bool(self.cfg.get("temporary_chat", False)),
                "active_project": self.cfg.get("active_project", ""),
                "conversation_id": self.brain.conversation_id,
                "cloud_provider_ready": cloudprovider.ready(self.cfg),
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

    def connections_operation(self, data=None):
        if data is not None:
            with self.brain._lock, self._settings_lock:
                if self.cfg.get('lockdown'):
                    raise ValueError('Turn off Lockdown to change connections.')
                service = data.get('service')
                if data.get('action') == 'disconnect_oauth' and data.get('confirmed') is True:
                    connectors.disconnect_oauth(str(data.get('connector') or ''))
                elif data.get('action') == 'revoke' and data.get('confirmed') is True and service in connections.REVOCABLE:
                    secure.set_secret(connections.REVOCABLE[service], '')
                    if service == 'Canvas calendar feed':
                        planner.CANVAS_CACHE.unlink(missing_ok=True)
                    secure.audit('connection_revoked', {'service': service})
                else:
                    raise ValueError('Choose a supported connection and confirm credential removal.')
        return connectors.all_connector_summary(self.cfg)

    def hardware_operation(self):
        return hardware.summary()

    def audio_devices_operation(self):
        from . import voice
        return {
            **voice.audio_devices(),
            "selected_mic": self.cfg.get("mic_device"),
            "selected_speaker": self.cfg.get("speaker_device"),
        }

    def security_operation(self, include_nomad=False):
        return sentinel.audit_posture(self.cfg, include_nomad=include_nomad)

    def agents_operation(self):
        return {
            "profiles": agents.list_profiles(),
            "active": self.cfg.get("assistant", "auto"),
            "last_trace": (
                {"task": self.brain.last_trace.task, "steps": self.brain.last_trace.steps,
                 "cancelled": self.brain.last_trace.cancelled}
                if self.brain.last_trace else None
            ),
        }

    def mcp_operation(self, data=None):
        with self.brain._lock, self._settings_lock:
            if data is not None:
                action = data.get("action")
                if action == "save":
                    mcp_client.save_server(self.cfg, data.get("server"))
                elif action == "enable":
                    mcp_client.set_enabled(self.cfg, str(data.get("id", "")), True, data.get("capabilities"))
                elif action == "disable":
                    mcp_client.set_enabled(self.cfg, str(data.get("id", "")), False)
                elif action == "remove" and data.get("confirmed") is True:
                    mcp_client.remove_server(self.cfg, str(data.get("id", "")))
                elif action == "discover":
                    return {"tools": mcp_client.discover_tools(self.cfg, str(data.get("id", "")))}
                else:
                    raise ValueError("Choose save, enable, disable, discover, or confirmed remove.")
            return {"servers": mcp_client.list_servers(self.cfg), "capabilities": mcp_client.CAPABILITIES}

    def feeds_operation(self, data=None):
        with self.brain._lock, self._settings_lock:
            if data is not None:
                action = data.get("action")
                if action == "add":
                    connectors.add_feed(self.cfg, data.get("name"), data.get("url"), bool(data.get("include_in_briefing")))
                elif action == "remove":
                    connectors.remove_feed(self.cfg, str(data.get("url") or ""))
                else:
                    raise ValueError("Choose add or remove for feed subscriptions.")
            return {"feeds": connectors.list_feeds(self.cfg)}

    def conversations_operation(self, data=None):
        with self.brain._lock:
            if data is not None:
                action = data.get("action")
                if action == "create":
                    created = self.memory.create_conversation(data.get("title"), data.get("project", ""))
                    self.brain.conversation_id = created["id"]
                    self.brain.history = []
                    return {"active": created["id"], "conversations": self.memory.list_conversations()}
                if action == "switch":
                    cid = str(data.get("id") or "default")[:64]
                    self.brain.conversation_id = cid
                    self.brain.history = self.memory.recent_messages(self.cfg.get("history_turns", 12), conversation_id=cid)
                    return {"active": cid, "messages": self.brain.history, "conversations": self.memory.list_conversations()}
                if action == "rename":
                    if not self.memory.rename_conversation(str(data.get("id") or ""), data.get("title")):
                        raise ValueError("Conversation not found.")
                elif action == "delete" and data.get("confirmed") is True:
                    cid = str(data.get("id") or "")
                    if cid == "default":
                        raise ValueError("Use Clear conversation history to clear the default conversation.")
                    if not self.memory.delete_conversation(cid):
                        raise ValueError("Conversation not found.")
                    if self.brain.conversation_id == cid:
                        self.brain.conversation_id = "default"
                        self.brain.history = self.memory.recent_messages(self.cfg.get("history_turns", 12), conversation_id="default")
                elif action == "search":
                    q = str(data.get("query") or "").strip()[:300]
                    return {"matches": self.memory.search_diary(q, limit=15)}
                else:
                    raise ValueError("Choose create, switch, rename, search, or confirmed delete.")
            return {"active": self.brain.conversation_id, "conversations": self.memory.list_conversations()}

    def projects_operation(self, data=None):
        with self.brain._lock, self._settings_lock:
            if data is not None:
                if self.cfg.get("lockdown"):
                    raise ValueError("Turn off Lockdown to modify projects.")
                action = data.get("action")
                if action == "save":
                    self.memory.save_project(
                        data.get("name"), data.get("description", ""),
                        data.get("code_dir", ""), data.get("document_folders", []),
                    )
                elif action == "delete" and data.get("confirmed") is True:
                    if not self.memory.delete_project(str(data.get("name") or "")):
                        raise ValueError("Project not found.")
                elif action == "activate":
                    name = str(data.get("name") or "").strip()[:60]
                    updated = {**self.cfg, "active_project": name}
                    config.save(updated)
                    self.cfg.update(updated)
                    self.emit("toggles", self.state())
                else:
                    raise ValueError("Choose save, activate, or confirmed delete.")
            return {"active": self.cfg.get("active_project", ""), "projects": self.memory.list_projects()}

    def document_preview_operation(self, data):
        """Safely preview a dropped/uploaded local text, Markdown, or PDF file in memory without saving."""
        import base64
        import binascii
        import io
        if self.cfg.get("mode") == "talk" or self.cfg.get("lockdown"):
            raise ValueError("Document preview is unavailable in Talk or Lockdown.")
        name = str(data.get("name") or "").strip()
        encoded = data.get("content_base64")
        if not name or not isinstance(encoded, str) or len(encoded) > 4_000_000:
            raise ValueError("Provide a text, Markdown, or PDF file up to 3 MB.")
        suffix = os.path.splitext(name)[1].lower()
        if suffix not in (".txt", ".md", ".pdf", ".json", ".csv", ".py", ".js"):
            raise ValueError("Supported preview formats: .txt, .md, .pdf, .json, .csv, .py, .js.")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("Invalid base64 file content.") from None
        if len(raw) > 3 * 1024 * 1024:
            raise ValueError("File exceeds the 3 MB preview limit.")
        if suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw))
            if reader.is_encrypted:
                raise ValueError("Encrypted PDF requires an unlocked copy.")
            pages = [(p.extract_text() or "") for p in reader.pages[:20]]
            text = "\n\n".join(pages)
        else:
            text = raw.decode("utf-8-sig", errors="replace")
        injection = secure.looks_like_injection(text)
        return {
            "name": os.path.basename(name)[:120],
            "chars": len(text),
            "preview": text[:12_000],
            "truncated": len(text) > 12_000,
            "injection_flagged": injection,
        }

    def models_operation(self, data=None):
        """Inspect locally installed Ollama models and assign one to an assistant role."""
        with self.brain._lock, self._settings_lock:
            installed = setupwizard.installed_ollama(self.cfg)
            if data is not None:
                if self.cfg.get('lockdown'):
                    raise ValueError('Turn off Lockdown to change models.')
                role, name = data.get('role'), data.get('name')
                if role not in ('everyday_model', 'model', 'coder_model') or not isinstance(name, str):
                    raise ValueError('Choose a model role and an installed model.')
                if installed is None:
                    raise ValueError('Ollama is unavailable. Start it and refresh models.')
                if name not in installed:
                    raise ValueError('Choose a model reported as installed by Ollama.')
                config.save({**self.cfg, role: name})
                self.cfg[role] = name
            return {'reachable': installed is not None,
                    'models': [{'name': name, 'disk_bytes': size} for name, size in sorted((installed or {}).items())
                               if not name.endswith(':latest')][:50],
                    'selected': {key:self.cfg.get(key) for key in ('everyday_model', 'model', 'coder_model', 'embed_model')},
                    'profile': self.cfg.get('performance_profile'), 'context_tokens': self.cfg.get('num_ctx'),
                    'note': 'Ollama reports disk size, not RAM or speed. Model role compatibility is not verified.'}

    def provider_operation(self, data=None):
        with self.brain._lock, self._settings_lock:
            extra = {}
            if data is not None:
                if data.get("action") == "save":
                    if self.cfg.get("lockdown"):
                        raise ValueError("Turn off Lockdown to change the chat provider.")
                    provider = data.get("provider")
                    if provider not in ("ollama", "openai_local"):
                        raise ValueError("Choose Ollama or a loopback chat-completions server.")
                    candidate = {**self.cfg, "chat_provider":provider}
                    if "url" in data:
                        candidate["local_chat_url"] = data["url"]
                    candidate["local_chat_url"] = localprovider.endpoint(candidate)
                    if "model" in data:
                        candidate["local_chat_model"] = data["model"]
                    if "stream" in data:
                        candidate["local_chat_stream"] = bool(data["stream"])
                    if provider == "openai_local":
                        candidate["local_chat_model"] = localprovider.model_name(candidate.get("local_chat_model"))
                    config.save(candidate)
                    self.cfg.update(candidate)
                    self.brain._missing_models.clear()
                    self.brain._no_tools.clear()
                    self.brain._no_think.clear()
                    self.brain._embed_ok = True
                    self.emit("toggles", self.state())
                elif data.get("action") == "models":
                    if self.cfg.get("chat_provider") == "openai_local":
                        extra["models"] = localprovider.models(self.cfg)
                    else:
                        extra["models"] = sorted((setupwizard.installed_ollama(self.cfg) or {}).keys())[:100]
                else:
                    raise ValueError("Choose Save provider or List active provider models.")
            return {"provider":self.cfg.get("chat_provider", "ollama"),
                    "url":self.cfg.get("local_chat_url"), "model":self.cfg.get("local_chat_model"),
                    "stream":bool(self.cfg.get("local_chat_stream", False)), **extra}

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
        elif what == "temporary_chat":
            self.cfg["temporary_chat"] = not self.cfg.get("temporary_chat", False)
            config.save(self.cfg)
            if self.cfg["temporary_chat"]:
                self.brain.history = []
        st = self.state()
        self.emit("toggles", st)
        return st

    def set_preference(self, key, value):
        choices = {"mode": config.MODES, "theme": config.THEMES, "assistant": assistants.CHOICES,
                   "voice_choice": config.VOICE_CHOICES, "tuki_voice_choice": config.VOICE_CHOICES,
                   "voice_input_mode": ("wake", "manual"), "workspace_view": config.WORKSPACE_VIEWS}
        if key in ("sapi_voice_contains", "tuki_sapi_voice_contains"):
            from .voice import installed_voice_names
            if not isinstance(value, str) or (value and value not in installed_voice_names()):
                raise ValueError("Choose an installed system voice or Automatic.")
            with self.brain._lock, self._settings_lock:
                config.save({**self.cfg, key: value})
                self.cfg[key] = value
                state = self.state()
            self.emit("toggles", state)
            return state
        if key not in choices or value not in choices[key]:
            raise ValueError("Unknown setting.")
        if key == "voice_choice" and value == "piper" and not self.cfg.get("piper_model"):
            raise ValueError("Set your local Piper voice model in Jarvis setup first.")
        if key == "tuki_voice_choice" and value == "piper" and not self.cfg.get("tuki_piper_model"):
            raise ValueError("Set TUKI's Piper voice model in setup first.")
        with self.brain._lock, self._settings_lock:
            config.save({**self.cfg, key: value})
            self.cfg[key] = value
            if key == "voice_input_mode" and self.listener:
                paused = self.listener.paused.is_set()
                self.listener.pause()
                if not paused:
                    self.listener.resume()
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
        self._workflow_cancelled.set()
        if self.listener:
            self.listener.cancel_manual()
        if self.speaker:
            self.speaker.stop()
        self.brain.ctx.pending = None
        self.emit("pending", None)
        self.emit("stream", "")
        return {"ok": True}

    def dictation_operation(self, data):
        if not self.listener:
            raise ValueError("Voice input is unavailable. Check microphone setup first.")
        action = data.get("action")
        if action == "start":
            return self.listener.begin_manual()
        if action == "finish" and isinstance(data.get("id"), str):
            return self.listener.finish_manual(data["id"])
        if action == "cancel":
            self.listener.cancel_manual()
            return {"ok": True}
        raise ValueError("Choose start, finish or cancel recording.")

    def workflows_operation(self, data=None):
        with self._workflow_lock:
            if data is not None:
                action = data.get("action")
                key = data.get("id")
                if action == "save":
                    workflows.save_template(self.memory, data.get("name"), data.get("steps"))
                elif action in ("delete", "delete_run") and data.get("confirmed") is True:
                    workflows.delete(self.memory, "workflows" if action == "delete" else "workflow_runs", key)
                elif action in ("run", "resume"):
                    if self.cfg.get("lockdown"):
                        raise ValueError("Turn off Lockdown before running a workflow.")
                    if data.get("confirmed") is not True:
                        raise ValueError("Review every step and confirm the workflow preview.")
                    if not isinstance(key, str):
                        raise ValueError("Choose a saved workflow or run.")
                    if not self._turn_lock.acquire(blocking=False):
                        raise ValueError("Jarvis is working. Use Stop and wait for the current task to end.")
                    run_id = None
                    try:
                        if action == "run":
                            run_id = workflows.create_run(self.memory, key, data.get("revision"))
                        else:
                            run = workflows.get_run(self.memory, key)
                            if run["state"] not in ("cancelled", "interrupted", "failed", "blocked"):
                                raise ValueError("Only an interrupted or blocked run can be resumed.")
                            if data.get("revision") != run["revision"]:
                                raise ValueError("Review the current run preview before resuming.")
                            run_id = key
                            workflows.update(self.memory, run_id, state="running", error="")
                        self._workflow_cancelled.clear()
                        self.emit("status", "working")
                        threading.Thread(target=self._run_workflow, args=(run_id,), daemon=True).start()
                    except BaseException:
                        if run_id:
                            workflows.update(self.memory, run_id, state="failed", error="Could not start the workflow worker.")
                        self._turn_lock.release()
                        raise
                else:
                    raise ValueError("Choose a workflow action and confirm deletion or execution.")
            return {"templates": workflows.list_templates(self.memory), "runs": workflows.list_runs(self.memory)}

    def _run_workflow(self, run_id):
        try:
            # Recovery and model operations already share this lock. A restore cannot
            # replace the run database halfway through a workflow step.
            with self.brain._lock:
                workflows.execute(self.memory, self.cfg, run_id, self._workflow_cancelled,
                                  lambda: self.emit("workflow", {"id": run_id}))
        finally:
            self._turn_lock.release()
            self.emit("status", "listening" if self.listener else "idle")

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
                if "briefing_time" in data:
                    if not isinstance(data["briefing_time"], str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d', data["briefing_time"]):
                        raise ValueError('Choose a daily briefing time in HH:MM format.')
                    updated["briefing_time"] = data["briefing_time"]
                for key in ('briefing_enabled', 'briefing_speak', 'local_chat_stream'):
                    if key in data:
                        if type(data[key]) is not bool:
                            raise ValueError('Choose whether the daily briefing is on and spoken.')
                        updated[key] = data[key]
                for rate_key in ('speech_rate', 'tuki_speech_rate'):
                    if rate_key in data:
                        val = data[rate_key]
                        if type(val) is not int or not 100 <= val <= 320:
                            raise ValueError('Speech rate must be an integer between 100 and 320 WPM.')
                        updated[rate_key] = val
                for dev_key in ('mic_device', 'speaker_device'):
                    if dev_key in data:
                        val = data[dev_key]
                        if val is not None and (type(val) is not int or val < 0):
                            raise ValueError('Choose a valid audio device index or OS default.')
                        updated[dev_key] = val
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
                    "briefing_time": self.cfg.get("briefing_time", "08:00"),
                    "briefing_enabled": bool(self.cfg.get("briefing_enabled", True)),
                    "briefing_speak": bool(self.cfg.get("briefing_speak", True)),
                    "follow_up_seconds": self.cfg.get("follow_up_seconds", 8),
                    "room_context_seconds": self.cfg.get("room_context_seconds", 120),
                    "speech_rate": int(self.cfg.get("speech_rate", 185)),
                    "tuki_speech_rate": int(self.cfg.get("tuki_speech_rate", 200)),
                    "mic_device": self.cfg.get("mic_device"),
                    "speaker_device": self.cfg.get("speaker_device"),
                    "local_chat_stream": bool(self.cfg.get("local_chat_stream", False)),
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
                    self.brain.ctx.last_test_failed = False
                    self.brain.ctx.last_test_kind = ''
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
                    return {"facts": self.memory.fact_details()}
                if data.get("action") == "find_duplicates":
                    return {"duplicates": self.memory.find_duplicate_facts(), "facts": self.memory.fact_details()}
                if data.get("action") == "deduplicate" and data.get("confirmed") is True:
                    removed = self.memory.deduplicate_facts()
                    return {"removed": removed, "facts": self.memory.fact_details()}
                if data.get("action") == "import":
                    added = self.memory.import_facts(data.get("facts"), project=self.cfg.get("active_project", ""))
                    secure.audit("memory_imported", {"added": added})
                    return {"added": added, "facts": self.memory.fact_details()}
                fact_id = data.get("id")
                if type(fact_id) is not int or fact_id < 1:
                    raise ValueError("Choose a remembered fact.")
                if data.get("action") == "edit":
                    changed = self.memory.edit_fact(fact_id, data.get("text"))
                elif data.get("action") == "delete" and data.get("confirmed") is True:
                    changed = self.memory.delete_fact(fact_id)
                elif data.get("action") == "expire":
                    if 'expires' not in data or data['expires'] is None:
                        raise ValueError('Choose a future expiration date.')
                    changed = self.memory.set_fact_expiry(fact_id, data.get('expires'))
                elif data.get("action") == "clear_expiry":
                    changed = self.memory.set_fact_expiry(fact_id, None)
                else:
                    raise ValueError("Choose Edit or confirm deletion.")
                if not changed:
                    raise ValueError("This remembered fact has already been removed. Refresh the list.")
            return {"facts": self.memory.fact_details()}

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

    def vitals_operation(self):
        return telemetry.snapshot()

    def providers_operation(self, data=None):
        if data is None:
            return providers.health_summary(self.cfg, probe_local=False)
        action = str(data.get("action") or "").strip().lower()
        if action == "probe":
            return providers.health_summary(self.cfg, probe_local=True)
        if action == "privacy_mode":
            if self.cfg.get("lockdown"):
                raise ValueError("Turn off Lockdown to change privacy mode.")
            mode = str(data.get("privacy_mode") or "").strip().lower()
            if mode not in providers.PRIVACY_MODES:
                raise ValueError("Choose local, hybrid, or cloud privacy mode.")
            with self.brain._lock, self._settings_lock:
                updated = {**self.cfg, "privacy_mode": mode}
                config.save(updated)
                self.cfg["privacy_mode"] = mode
            secure.audit("privacy_mode_changed", {"privacy_mode": mode})
            return providers.health_summary(self.cfg, probe_local=False)
        raise ValueError("Choose probe or privacy_mode.")

    def tool_history_operation(self):
        return {
            "total_skills": len(skills.SKILLS),
            "history": skills.recent_tool_history(limit=40),
        }

    def dry_run_operation(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("tool"), str) or not data["tool"].strip():
            raise ValueError("Provide a tool name to inspect.")
        args = data.get("args")
        if args is not None and not isinstance(args, dict):
            raise ValueError("Tool args must be a JSON object.")
        return skills.dry_run(self.brain.ctx, data["tool"].strip(), args or {})

    def undo_operation(self):
        return {"entries": undo.JOURNAL.list_entries(limit=40)}

    def bgtasks_operation(self, data=None):
        if data is None:
            return {"tasks": bgtasks.list_tasks(self.memory)}
        action = str(data.get("action") or "").strip().lower()
        if action == "create":
            task = bgtasks.create_task(self.memory, data.get("title", ""), data.get("steps") or [], kind=data.get("kind", "sequential"))
            return {"task": task, "tasks": bgtasks.list_tasks(self.memory)}
        if action == "run":
            task = bgtasks.execute_task(self.memory, self.brain.ctx, str(data.get("id") or ""))
            return {"task": task, "tasks": bgtasks.list_tasks(self.memory)}
        if action == "cancel":
            task = bgtasks.cancel_task(self.memory, str(data.get("id") or ""))
            return {"task": task, "tasks": bgtasks.list_tasks(self.memory)}
        if action == "delete":
            bgtasks.delete_task(self.memory, str(data.get("id") or ""))
            return {"tasks": bgtasks.list_tasks(self.memory)}
        raise ValueError("Choose create, run, cancel, or delete.")

    def monitors_operation(self, data=None):
        if data is None:
            return {"monitors": monitors.list_monitors(self.memory), "metrics": monitors.METRICS}
        action = str(data.get("action") or "").strip().lower()
        if action == "create":
            mon = monitors.create_monitor(
                self.memory, name=data.get("name", ""), metric=data.get("metric", ""),
                operator=data.get("operator", ">"), threshold=data.get("threshold", 90),
            )
            return {"monitor": mon, "monitors": monitors.list_monitors(self.memory)}
        if action in ("pause", "resume"):
            rows = monitors.set_enabled(self.memory, str(data.get("id") or ""), action == "resume")
            return {"monitors": rows}
        if action == "delete":
            return {"monitors": monitors.delete_monitor(self.memory, str(data.get("id") or ""))}
        if action == "evaluate":
            alerts = monitors.evaluate_all(self.memory)
            return {"alerts": alerts, "monitors": monitors.list_monitors(self.memory)}
        raise ValueError("Choose create, pause, resume, delete, or evaluate.")

    def macros_operation(self, data=None):
        if data is None:
            return {"macros": macros.list_macros(self.memory), "recording": macros.recording_status()}
        action = str(data.get("action") or "").strip().lower()
        if action == "save":
            m = macros.save_macro(self.memory, name=data.get("name", ""), steps=data.get("steps") or [],
                                  description=data.get("description", ""), macro_id=data.get("id"))
            return {"macro": m, "macros": macros.list_macros(self.memory)}
        if action == "delete":
            macros.delete_macro(self.memory, str(data.get("id") or ""))
            return {"macros": macros.list_macros(self.memory)}
        if action == "preview":
            return macros.preview_macro(self.memory, self.brain.ctx, str(data.get("id") or ""))
        if action == "replay":
            return macros.replay_macro(self.memory, self.brain.ctx, str(data.get("id") or ""))
        if action == "record_start":
            return {"recording": macros.start_recording(data.get("name", ""), data.get("description", ""))}
        if action == "record_step":
            return {"recording": macros.record_step(data.get("tool", ""), data.get("args") or {})}
        if action == "record_stop":
            return macros.stop_recording(self.memory, save=bool(data.get("save", True)))
        raise ValueError("Choose save, delete, preview, replay, record_start, record_step, or record_stop.")

    def daily_summary_operation(self, data=None):
        if data and data.get("action") == "extract":
            existing = [f[1] for f in self.memory.all_facts()]
            return {"candidates": memextract.extract_candidates(data.get("text", ""), existing_facts=existing)}
        if data and data.get("action") == "approve":
            saved = memextract.approve_candidate(self.memory, data.get("text", ""), project=self.cfg.get("active_project", ""))
            return {"saved": saved}
        return memextract.daily_summary(self.memory, self.cfg)

    def pro_operation(self, data=None):
        if data is None:
            return {"uat": pro_workspace.uat_list(self.memory), "cases": pro_workspace.case_list(self.memory)}
        action = str(data.get("action") or "").strip().lower()
        if action == "csv_variance":
            return pro_workspace.compare_csv_tables(
                data.get("baseline", ""), data.get("actual", ""),
                key_col=str(data.get("key_col") or "item"), value_col=str(data.get("value_col") or "amount"),
            )
        if action == "doc_diff":
            return pro_workspace.compare_revisions(
                data.get("text_a", ""), data.get("text_b", ""),
                label_a=str(data.get("label_a") or "Revision A"), label_b=str(data.get("label_b") or "Revision B"),
            )
        if action == "uat_add":
            item = pro_workspace.uat_add(
                self.memory, req_id=data.get("req_id", ""), title=data.get("title", ""),
                status=data.get("status", "pending"), evidence=data.get("evidence", ""),
            )
            return {"item": item, "uat": pro_workspace.uat_list(self.memory)}
        if action == "case_create":
            c = pro_workspace.case_create(self.memory, title=data.get("title", ""), category=data.get("category", "general"), note=data.get("note", ""))
            return {"case": c, "cases": pro_workspace.case_list(self.memory)}
        if action == "finance_summary":
            return pro_workspace.finance_budget_summary(self.cfg, data.get("transactions") or [])
        raise ValueError("Choose csv_variance, doc_diff, uat_add, case_create, or finance_summary.")

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
                self.memory.purge_expired()
                watchchecks.run_due(self.memory, self.cfg, lambda message: self.notify(message, speak=False))
                for alert in monitors.evaluate_all(self.memory):
                    self.notify(alert["message"], speak=False)
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
        if not self.cfg.get('briefing_enabled', True):
            return
        hh, mm = map(int, self.cfg.get("briefing_time", "08:00").split(":"))
        now = dt.datetime.now()
        today = now.date().isoformat()
        if now.time() >= dt.time(hh, mm) and planner.kv_get(self.memory, "last_briefing") != today:
            planner.kv_set(self.memory, "last_briefing", today)
            self.notify(skills.briefing(self.brain.ctx), speak=self.cfg.get('briefing_speak', True))

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
    hw = hardware.summary()
    mem = hw["memory"]
    print(f"  [HW] OS: {hw['os']}")
    print(f"  [HW] CPU: {hw['cpu']['processor']} ({hw['cpu']['physical_cores'] or '?'}C/{hw['cpu']['logical_cores']}T)")
    if mem["total_gb"] is not None:
        print(f"  [HW] RAM: {mem['total_gb']} GB total ({mem['available_gb']} GB available)")
    for gpu in hw["gpus"]:
        print(f"  [HW] GPU: {gpu['name']} ({gpu['vram_total_gb']} GB VRAM, {gpu['vram_free_gb']} GB free)")
    print(f"  [HW] Recommended profile: {hw['recommendation']['profile']} ({hw['recommendation']['tier']})\n")
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
    p.add_argument("command", nargs="?", default="run", choices=["run", "doctor", "voice-check", "briefing", "setup", "security-audit"])
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
    if args.command == "security-audit":
        report = sentinel.audit_posture(cfg, include_nomad=True)
        print("Jarvis Sentinel Local Security Audit\n")
        for chk in report["checks"]:
            print(f"  [{chk['status'].upper():4s}] {chk['label']}: {chk['detail']}")
        return 0
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
