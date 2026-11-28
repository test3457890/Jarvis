"""Settings for Jarvis. Stored as JSON in %APPDATA%\\Jarvis\\config.json."""
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from .assistants import CHOICES

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Jarvis"
CONFIG_PATH = APP_DIR / "config.json"

MODES = ("everyday", "coding", "research", "cybersecurity", "briefing", "talk")
THEMES = ("hud", "simple", "light", "contrast", "midnight", "paper")
WORKSPACE_VIEWS = ("classic", "command", "ambient")
VOICE_CHOICES = ("auto", "windows", "piper")
VOICE_LIMITS = {"follow_up_seconds": 60, "room_context_seconds": 600}

DEFAULTS = {
    "mode": "everyday",
    "stream_replies": True,
    "assistant": "auto",
    "everyday_model": "qwen3:4b",
    "technical_keep_alive": 0,
    "everyday_keep_alive": "2m",
    "embed_keep_alive": "2m",
    "memory_embeddings": True,
    "performance_profile": "standard",
    "theme": "hud",
    "workspace_view": "classic",
    "voice_choice": "auto",
    # TUKI speaks with its own voice. "auto" picks a different installed voice from Jarvis.
    "tuki_voice_choice": "auto",
    "tuki_sapi_voice_contains": "",
    "tuki_piper_model": "",
    "tuki_speech_rate": 200,
    # First-run wizard. Existing installs are marked complete when their config loads.
    "setup_complete": False,
    "voice_enabled": True,
    "voice_input_mode": "wake",  # wake | manual (hold-to-record in the HUD)
    "storage_budget_gb": None,
    # Folders the user explicitly selected for general file tasks. Separate from code_dir.
    "file_folders": [],
    # Coding: add related project files as read-only context automatically.
    "auto_context": True,
    # Local OCR with Tesseract for scanned PDFs and images in document search. Off by default.
    "ocr_enabled": False,
    "tesseract_path": "",
    # Programs the user approved for app actions: [{"name", "program", "takes_file"}].
    "app_actions": [],
    # Extensions the user enabled, with the permissions they approved.
    "enabled_extensions": {},
    "name": "Jarvis",
    "user_name": "",
    "response_style": "balanced",
    "language": "en-GB",
    "standing_instructions": "",
    # Local language model served by Ollama (must support tool calling).
    "model": "qwen3:8b",
    # Small local model used to turn memories into vectors for smarter recall.
    "embed_model": "nomic-embed-text",
    "ollama_url": "http://127.0.0.1:11434",
    "lmstudio_url": "http://127.0.0.1:1234",
    "chat_provider": "ollama",
    "local_chat_url": "http://127.0.0.1:8081",
    "local_chat_model": "",
    "local_chat_stream": False,
    "privacy_mode": "hybrid",
    "fast_path_enabled": True,
    # Optional per-request-consented cloud AI provider (off by default, never silent fallback).
    "allow_cloud_provider": False,
    "cloud_provider": "",
    "cloud_model": "",
    "custom_cloud_url": "",
    # Approved saved RSS/Atom feed subscriptions and local stdio MCP servers (disabled by default).
    "saved_feeds": [],
    "mcp_servers": [],
    "connector_write_permissions": {},
    "domain_permissions": {},
    # Privacy & conversation state
    "temporary_chat": False,
    "active_project": "",
    # Optional explicit audio device indices (None = OS default)
    "mic_device": None,
    "speaker_device": None,
    # Speech recognition (faster-whisper). tiny.en / base.en / small.en / medium.en
    "whisper_model": "small.en",
    "whisper_device": "auto",  # auto | cuda | cpu
    "wake_words": ["jarvis", "jarvus", "jervis", "travis"],
    # Seconds Jarvis keeps listening for a follow-up without the wake word.
    "follow_up_seconds": 8,
    # Seconds of room conversation Jarvis remembers so it can join in.
    "room_context_seconds": 120,
    "mic_sensitivity": 1.0,
    # Text to speech. "sapi" = built-in Windows voice. Or set piper_model to a .onnx voice.
    "tts": "sapi",
    "sapi_voice_contains": "",
    "speech_rate": 185,
    "piper_exe": "piper",
    "piper_model": "",
    "speak_replies": True,
    # Safety: risky actions (shutdown, empty recycle bin...) need a spoken/typed "yes".
    "confirm_risky_actions": True,
    # Lockdown mode: instantly disables all risky skills (can be toggled from the HUD).
    "lockdown": False,
    # Per-skill permission overrides: "off" | "ask" | "allowed". Risky skills can never be "allowed".
    "skill_permissions": {},
    # Rate limits on outbound communications (phone_call, text_message, send_email, draft_email).
    "comms_rate_limit_max": 5,
    "comms_rate_limit_window_seconds": 300,
    # Offline by default. Turn on to allow tools that use the internet (Wikipedia).
    "allow_internet_tools": False,
    "allow_web_search": False,
    "vision_url": "http://127.0.0.1:11434",
    "vision_model": "gemma3:4b",
    "image_generation_url": "",
    "github_upload_repo": "",
    "github_upload_branch": "main",
    "notes_dir": str(APP_DIR / "notes"),
    "document_folders": [],
    # Optional local search index. Off unless explicitly enabled in Setup.
    "document_index_enabled": False,
    "search_folders": [
        str(Path.home() / "Documents"),
        str(Path.home() / "Desktop"),
        str(Path.home() / "Downloads"),
    ],
    "web_port": 8765,
    "history_turns": 10,
    "num_ctx": 8192,
    "honorific": "sir",
    # Coding
    "coder_model": "qwen2.5-coder:7b",
    "code_dir": str(Path.home() / "Documents" / "Jarvis Code"),
    # Planning
    "work_hours": [8, 22],
    "study_block_minutes": 50,
    "study_lead_hours": 24,  # flag work scheduled inside this deadline buffer
    "max_planned_minutes_per_day": 240,
    "default_task_minutes": 60,
    "briefing_time": "08:00",
    "briefing_enabled": True,
    "briefing_speak": True,
    "event_heads_up_minutes": 15,
    # Project NOMAD (https://www.projectnomad.us). Change the host if NOMAD runs on another machine.
    "nomad_url": "http://127.0.0.1:8080",
    "kiwix_url": "",
    "personality": (
        "You are J.A.R.V.I.S., a calm, dry-witted, fiercely loyal AI assistant in the style of "
        "a British butler, running locally on the user's computer. You are practical "
        "first: you get things done, keep the user on schedule and gently call out anything "
        "slipping. Address the user as '{honorific}' now and then. Replies are usually read "
        "aloud, so keep them to one to three sentences unless asked for detail, and never use "
        "markdown, lists or emoji in spoken replies. Use your tools whenever they help, and "
        "never invent tool results or claim you did something you didn't."
    ),
}


def load() -> dict:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        try:
            saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            # Keep the unreadable file for the user instead of overwriting it with defaults.
            backup = CONFIG_PATH.with_name(f"config.unreadable-{int(time.time())}.json")
            try:
                shutil.copy2(CONFIG_PATH, backup)
            except OSError:
                pass
            print(f"[config] Could not read {CONFIG_PATH}: {e}. A copy was kept at {backup}. Using defaults.")
            saved = {"setup_complete": True}
        if isinstance(saved, dict):
            # Configurations written before the setup wizard existed belong to working installs.
            saved.setdefault("setup_complete", True)
            cfg.update(saved)
    # The built-in personality always comes from the code (so upgrades apply);
    # put your own text in "custom_personality" to replace it.
    cfg["personality"] = cfg.get("custom_personality") or DEFAULTS["personality"]
    cfg.setdefault("custom_personality", "")
    for key, choices in (("mode", MODES), ("theme", THEMES), ("assistant", CHOICES),
                         ("voice_choice", VOICE_CHOICES), ("tuki_voice_choice", VOICE_CHOICES)):
        if cfg.get(key) not in choices:
            cfg[key] = choices[0]
    for key, limit in VOICE_LIMITS.items():
        if type(cfg.get(key)) is not int or not 0 <= cfg[key] <= limit:
            cfg[key] = DEFAULTS[key]
    save(cfg)  # writes any new default keys
    Path(cfg["notes_dir"]).mkdir(parents=True, exist_ok=True)
    return cfg


def save(cfg: dict) -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)
    data = {k: v for k, v in cfg.items() if k != "personality"}
    with tempfile.NamedTemporaryFile(dir=CONFIG_PATH.parent, mode="w", encoding="utf-8",
                                     delete=False) as stream:
        temporary = Path(stream.name)
        try:
            json.dump(data, stream, indent=2)
        except Exception:
            stream.close()
            temporary.unlink(missing_ok=True)
            raise
    try:
        for attempt in range(5):
            try:
                temporary.replace(CONFIG_PATH)
                break
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.02)
    finally:
        temporary.unlink(missing_ok=True)


PERFORMANCE_PROFILES = {
    "standard": {
        "model": "qwen3:8b", "everyday_model": "qwen3:4b",
        "coder_model": "qwen2.5-coder:7b", "num_ctx": 8192,
        "whisper_model": "small.en", "memory_embeddings": True,
        "everyday_keep_alive": "2m", "technical_keep_alive": 0,
        "embed_keep_alive": "2m",
    },
    "low-memory": {
        "model": "qwen3:4b", "everyday_model": "qwen3:4b",
        "coder_model": "qwen2.5-coder:1.5b", "num_ctx": 2048,
        "whisper_model": "base.en", "memory_embeddings": False,
        "everyday_keep_alive": 0, "technical_keep_alive": 0,
        "embed_keep_alive": 0,
    },
}


def apply_profile(cfg, profile):
    """Return explicit model and memory settings while preserving personal settings."""
    if profile not in PERFORMANCE_PROFILES:
        raise ValueError("Choose standard or low-memory.")
    return {**cfg, **PERFORMANCE_PROFILES[profile], "performance_profile": profile}
