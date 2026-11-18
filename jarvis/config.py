"""Settings for Jarvis. Stored as JSON in %APPDATA%\\Jarvis\\config.json."""
import json
import os
import tempfile
from pathlib import Path

from .assistants import CHOICES

APP_DIR = Path(os.environ.get("APPDATA", str(Path.home()))) / "Jarvis"
CONFIG_PATH = APP_DIR / "config.json"

MODES = ("everyday", "coding", "briefing", "talk")
THEMES = ("hud", "simple", "light")

DEFAULTS = {
    "mode": "everyday",
    "assistant": "auto",
    "everyday_model": "qwen3:4b",
    "technical_keep_alive": 0,
    "theme": "hud",
    "voice_choice": "auto",
    "name": "Jarvis",
    "user_name": "",
    # Local language model served by Ollama (must support tool calling).
    "model": "qwen3:8b",
    # Small local model used to turn memories into vectors for smarter recall.
    "embed_model": "nomic-embed-text",
    "ollama_url": "http://127.0.0.1:11434",
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
    "github_upload_repo": "",
    "github_upload_branch": "main",
    "notes_dir": str(APP_DIR / "notes"),
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
    "max_planned_minutes_per_day": 240,
    "default_task_minutes": 60,
    "briefing_time": "08:00",
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
            cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as e:
            print(f"[config] Could not read {CONFIG_PATH}: {e}. Using defaults.")
    # The built-in personality always comes from the code (so upgrades apply);
    # put your own text in "custom_personality" to replace it.
    cfg["personality"] = cfg.get("custom_personality") or DEFAULTS["personality"]
    cfg.setdefault("custom_personality", "")
    for key, choices in (("mode", MODES), ("theme", THEMES), ("assistant", CHOICES),
                         ("voice_choice", ("auto", "windows", "piper"))):
        if cfg.get(key) not in choices:
            cfg[key] = choices[0]
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
        temporary.replace(CONFIG_PATH)
    finally:
        temporary.unlink(missing_ok=True)
