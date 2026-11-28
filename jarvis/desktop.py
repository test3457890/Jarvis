"""Desktop Window Management, Screenshot Organization & Safe Project Scaffolding.

Security rules:
- Window enumeration is read-only (T0). Window focus/minimize/maximize are risky (T2)
  and require explicit confirmation + Lockdown OFF.
- Screenshot organization stays strictly inside %APPDATA%\\Jarvis\\screenshots.
- Project scaffolding stays strictly inside code_dir, rejects path traversal/reserved names,
  never overwrites existing projects, and logs every creation to the Undo Journal.
"""
import ctypes
import json
import os
import re
from pathlib import Path
import time

from . import config, secure, undo
from .skills import skill

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_RESERVED = frozenset({"con", "prn", "aux", "nul"} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)})

TEMPLATES = {
    "python-cli": {
        "README.md": "# {name}\n\nPython CLI project scaffolded by Jarvis.\n",
        "main.py": 'def main():\n    print("Hello from {name}")\n\n\nif __name__ == "__main__":\n    main()\n',
        "test_main.py": "from main import main\n\n\ndef test_main_runs():\n    main()\n",
    },
    "static-site": {
        "index.html": "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\"><title>{name}</title></head><body><h1>{name}</h1></body></html>\n",
        "styles.css": "body { font-family: system-ui, sans-serif; margin: 2rem; }\n",
        "app.js": "console.log('{name} ready');\n",
    },
}


# ------------------------------------------------------------------ Window Management
def list_windows(limit: int = 40) -> list[dict]:
    """Enumerate visible top-level desktop windows on Windows via user32; graceful empty list elsewhere."""
    if os.name != "nt":
        return []
    user32 = ctypes.windll.user32
    windows = []

    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

    def _cb(hwnd, _lparam):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title:
                    windows.append({"hwnd": int(hwnd), "title": title[:160]})
        return len(windows) < max(1, min(limit, 100))

    try:
        user32.EnumWindows(EnumWindowsProc(_cb), 0)
    except Exception:
        return []
    return windows


def focus_window(title_query: str) -> str:
    """Bring a matching visible window to the foreground (Windows only)."""
    if os.name != "nt":
        raise ValueError("Window focus is currently supported on Windows.")
    needle = str(title_query or "").strip().lower()
    if not needle:
        raise ValueError("Specify part of the window title to focus.")
    matches = [w for w in list_windows(80) if needle in w["title"].lower()]
    if not matches:
        raise ValueError(f"No visible window matched '{title_query}'.")
    target = matches[0]
    user32 = ctypes.windll.user32
    user32.ShowWindow(target["hwnd"], 9)  # SW_RESTORE
    user32.SetForegroundWindow(target["hwnd"])
    secure.audit("window_focused", {"title": target["title"][:80]})
    return f"Focused window: {target['title']}"


_WINDOW_STATES = {"minimize": 6, "maximize": 3, "restore": 9}
_BLOCKED_HOTKEYS = frozenset({"ctrl+alt+del", "ctrl+alt+delete", "win+r", "win+x"})


def set_window_state(title_query: str, state: str) -> str:
    """Minimize, maximize, or restore a visible window by partial title (Windows only)."""
    st = str(state or "").strip().lower()
    if st not in _WINDOW_STATES:
        raise ValueError(f"Choose a supported window state: {', '.join(sorted(_WINDOW_STATES))}.")
    if os.name != "nt":
        raise ValueError("Window state control is currently supported on Windows.")
    needle = str(title_query or "").strip().lower()
    matches = [w for w in list_windows(80) if needle and needle in w["title"].lower()]
    if not matches:
        raise ValueError(f"No visible window matched '{title_query}'.")
    target = matches[0]
    ctypes.windll.user32.ShowWindow(target["hwnd"], _WINDOW_STATES[st])
    secure.audit("window_state_changed", {"title": target["title"][:80], "state": st})
    return f"Set window '{target['title']}' to {st}."


def validate_hotkey(combo: str) -> list[str]:
    parts = [p.strip().lower() for p in str(combo or "").split("+") if p.strip()]
    if not 1 <= len(parts) <= 4:
        raise ValueError("Provide 1 to 4 keys separated by '+' (e.g. ctrl+c).")
    normalized = "+".join(parts)
    if normalized in _BLOCKED_HOTKEYS:
        raise PermissionError(f"Hotkey '{normalized}' is blocked by security policy.")
    return parts


def send_approved_hotkey(combo: str, *, dry_run: bool = False) -> dict:
    """Validate and optionally send a keyboard shortcut via Win32 keybd_event (approved only)."""
    parts = validate_hotkey(combo)
    if dry_run:
        return {"ok": True, "dry_run": True, "keys": parts}
    if os.name != "nt":
        raise ValueError("Keyboard shortcut injection is currently supported on Windows.")
    vk_map = {
        "ctrl": 0x11, "alt": 0x12, "shift": 0x10, "enter": 0x0D, "tab": 0x09,
        "esc": 0x1B, "escape": 0x1B, "space": 0x20, "backspace": 0x08,
    }
    vks = []
    for k in parts:
        if k in vk_map:
            vks.append(vk_map[k])
        elif len(k) == 1 and k.isalnum():
            vks.append(ord(k.upper()))
        else:
            raise ValueError(f"Unsupported key '{k}'.")
    user32 = ctypes.windll.user32
    for vk in vks:
        user32.keybd_event(vk, 0, 0, 0)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, 2, 0)  # KEYEVENTF_KEYUP
    secure.audit("desktop_hotkey_sent", {"keys": parts})
    return {"ok": True, "keys": parts}


# ------------------------------------------------------------------ Screenshot Organizer
def screenshots_dir() -> Path:
    d = config.APP_DIR / "screenshots"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _init_tags_db(mem) -> None:
    with mem._lock:
        mem.db.execute("CREATE TABLE IF NOT EXISTS screenshot_tags (name TEXT PRIMARY KEY, tags_json TEXT NOT NULL)")
        mem.db.commit()


def list_screenshots(mem) -> list[dict]:
    _init_tags_db(mem)
    root = screenshots_dir()
    with mem._lock:
        tags_map = {r[0]: json.loads(r[1]) for r in mem.db.execute("SELECT name, tags_json FROM screenshot_tags").fetchall()}
    rows = []
    for p in sorted(root.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file() or p.suffix.lower() not in (".png", ".jpg", ".jpeg", ".webp"):
            continue
        rows.append({
            "name": p.name,
            "size_bytes": p.stat().st_size,
            "modified": round(p.stat().st_mtime, 2),
            "tags": tags_map.get(p.name, []),
        })
    return rows[:100]


def tag_screenshot(mem, name: str, tags: list[str]) -> dict:
    _init_tags_db(mem)
    clean_name = Path(str(name or "")).name
    target = screenshots_dir() / clean_name
    if not target.is_file() or target.parent.resolve() != screenshots_dir().resolve():
        raise ValueError("Screenshot file not found.")
    clean_tags = [re.sub(r"[^\w\- ]", "", str(t)).strip()[:30] for t in (tags or []) if str(t).strip()][:10]
    with mem._lock:
        mem.db.execute("INSERT OR REPLACE INTO screenshot_tags (name, tags_json) VALUES (?, ?)", (clean_name, json.dumps(clean_tags)))
        mem.db.commit()
    return {"name": clean_name, "tags": clean_tags}


# ------------------------------------------------------------------ Project Scaffolding
def scaffold_project(cfg: dict, name: str, template: str = "python-cli") -> dict:
    """Create a starter project strictly inside code_dir without overwriting existing folders."""
    clean_name = str(name or "").strip()
    if not _SAFE_NAME_RE.match(clean_name) or clean_name.lower().split(".")[0] in _RESERVED:
        raise ValueError("Use a safe alphanumeric project name (letters, digits, ., _, -).")
    if template not in TEMPLATES:
        raise ValueError(f"Choose a supported template: {', '.join(sorted(TEMPLATES))}.")
    root = Path(cfg.get("code_dir") or config.DEFAULTS["code_dir"]).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    dest = (root / clean_name).resolve()
    if dest.parent != root or dest.exists():
        raise ValueError(f"Project folder '{clean_name}' already exists or is outside the coding workspace.")
    dest.mkdir(parents=False, exist_ok=False)
    created = []
    for rel, body in TEMPLATES[template].items():
        fp = dest / rel
        fp.write_text(body.format(name=clean_name), encoding="utf-8")
        created.append(rel)
    undo.JOURNAL.record(
        category="scaffolding",
        tool="scaffold_project",
        summary=f"Scaffolded {template} project '{clean_name}' ({len(created)} files)",
        target=str(dest),
        undo_hint=f"Remove folder {dest.name} from coding workspace",
    )
    secure.audit("project_scaffolded", {"name": clean_name, "template": template, "files": len(created)})
    return {"name": clean_name, "template": template, "path": str(dest), "files": created}


@skill("List currently visible desktop windows.")
def desktop_windows_list(ctx):
    wins = list_windows(30)
    if not wins:
        return "No visible desktop windows enumerated on this platform."
    return "\n".join(f"- {w['title']}" for w in wins)


@skill(
    "Focus a visible desktop window by partial title.",
    params={"title": ("string", "Part of the window title", True)},
    risky=True,
    preview=lambda ctx, title: f"focus the desktop window matching '{title}'",
)
def desktop_window_focus(ctx, title):
    return focus_window(title)
