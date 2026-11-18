"""Jarvis's skills (tools the AI can call). Add your own with the @skill decorator:

    @skill("Describe what it does", params={"thing": ("string", "what it means", True)})
    def my_skill(ctx, thing):
        return "result text"
"""
import ast
import ctypes
import datetime as dt
import operator
import os
import random
import secrets
import re
import subprocess
import time
import urllib.parse
import urllib.request
import json
import math
import webbrowser
from pathlib import Path

from . import net, secure

SKILLS = {}


def skill(description, params=None, risky=False, internet=False, untrusted=False,
          preview=None, available=None, manual=False):
    """risky:     needs the user's spoken/typed/clicked "yes" first (and is audited)
    internet:  only offered when internet tools are allowed
    untrusted: result comes from outside (web, files, Canvas) and is fenced off
    preview:   fn(ctx, **args) -> text describing exactly what will happen
    manual:    available to direct commands only, outside the model tool list
    available: fn(cfg) -> bool, hide the skill when it isn't set up"""
    def deco(fn):
        SKILLS[fn.__name__] = {"fn": fn, "description": description, "params": params or {},
                               "risky": risky, "internet": internet, "untrusted": untrusted,
                               "preview": preview, "available": available, "manual": manual}
        return fn
    return deco


RATE_LIMITED_SKILLS = frozenset({"phone_call", "text_message", "send_email", "draft_email"})


def permission_level(cfg: dict, name: str) -> str:
    """Return effective permission for a skill: 'off', 'ask', or 'allowed'.
    Risky skills can NEVER be set to 'allowed'."""
    s = SKILLS.get(name)
    if not s:
        return "off"
    raw = str((cfg.get("skill_permissions") or {}).get(name, "")).strip().lower()
    if raw == "off":
        return "off"
    if s["risky"]:
        return "ask"  # non-negotiable: risky skills never bypass confirmation
    if raw in ("ask", "allowed"):
        return raw
    return "allowed"


def tool_schemas(cfg) -> list:
    tools = []
    lockdown = bool(cfg.get("lockdown"))
    for name, s in SKILLS.items():
        if s["manual"]:
            continue
        if s["internet"] and not cfg.get("allow_internet_tools"):
            continue
        if lockdown and s["risky"]:
            continue
        if permission_level(cfg, name) == "off":
            continue
        if s["available"] and not s["available"](cfg):
            continue
        props, required = {}, []
        for p, (ptype, pdesc, req) in s["params"].items():
            props[p] = {"type": ptype, "description": pdesc}
            if req:
                required.append(p)
        tools.append({"type": "function", "function": {
            "name": name, "description": s["description"],
            "parameters": {"type": "object", "properties": props, "required": required}}})
    return tools


class Context:
    """What skills can see: settings, memory, and a place to park risky actions."""
    def __init__(self, cfg, memory):
        self.cfg = cfg
        self.memory = memory
        self.code_proposal = None
        self.applied_code = None
        self.proposal_seen = False
        self.pending = None  # {"name", "args", "preview"} waiting for the user's "yes"
        self.on_images = lambda images: None
        self.on_pending = lambda pending: None
        self.injection_seen = False  # outside content this turn tried to give orders
        self.rate_limiter = secure.RateLimiter()


def run(ctx: Context, name: str, args: dict, confirmed=False) -> str:
    s = SKILLS.get(name)
    if not s:
        return f"Unknown tool {name}. Use one of the listed tools."
    if ctx.cfg.get("lockdown") and s["risky"]:
        if ctx.pending:
            ctx.pending = None
            ctx.on_pending(None)
        secure.audit("lockdown_blocked", {"skill": name})
        return "Lockdown mode is active. Risky actions are disabled."
    level = permission_level(ctx.cfg, name)
    if level == "off":
        secure.audit("skill_disabled", {"skill": name})
        return f"{name} is disabled in settings."
    given = set((args or {}).keys())
    required = {p for p, (_, _, req) in s["params"].items() if req}
    if not required <= given or (given and not given & set(s["params"])):
        expected = ", ".join(f"{p}{'' if req else ' (optional)'}" for p, (_, _, req) in s["params"].items())
        return (f"Wrong arguments for {name}: it takes {expected or 'no arguments'}. "
                f"You may have picked the wrong tool; check the tool list and try again.")
    if s["internet"] and not ctx.cfg.get("allow_internet_tools"):
        return "Internet tools are turned off (offline mode)."
    if s["available"] and not s["available"](ctx.cfg):
        return f"{name} isn't set up yet. Run 'Jarvis.bat setup'."
    allowed = set(s["params"])
    clean = {k: v for k, v in (args or {}).items() if k in allowed}
    harmless = name == "power" and clean.get("action") == "cancel"
    needs_confirm = (s["risky"] or level == "ask") and not harmless
    if needs_confirm and not confirmed:
        try:
            what = s["preview"](ctx, **clean) if s["preview"] else f"{name} {clean}"
        except Exception as e:
            return f"Can't prepare {name}: {e}"
        ctx.pending = {"name": name, "args": clean, "preview": what, "id": secrets.token_urlsafe(12)}
        ctx.on_pending(ctx.pending)
        return (f"NOT DONE YET. Waiting for the user's confirmation. Tell the user exactly what "
                f"will happen: {what}. Then ask them to say yes or no.")
    if name in RATE_LIMITED_SKILLS:
        limit = int(ctx.cfg.get("comms_rate_limit_max", 5))
        window = float(ctx.cfg.get("comms_rate_limit_window_seconds", 300))
        if not ctx.rate_limiter.allow("comms", limit, window):
            secure.audit("rate_limited", {"skill": name, "limit": limit, "window": window})
            return f"Rate limit reached: at most {limit} calls, texts, or emails are allowed per {int(window)} seconds."
    try:
        result = str(s["fn"](ctx, **clean))
    except TypeError as e:
        return f"Bad arguments for {name}: {e}"
    except Exception as e:  # a broken skill must never crash Jarvis
        result = f"{name} failed: {e}"
    if s["risky"] or s["internet"]:
        secure.audit(name, {"args": clean, "result": result[:300]})
    if s["untrusted"]:
        if secure.looks_like_injection(result):
            ctx.injection_seen = True
            secure.audit("injection_blocked", {"source": name, "sample": result[:200]})
        result = secure.fence(result)
    return result


def _ps(command: str, timeout=20) -> str:
    out = subprocess.run(["powershell", "-NoProfile", "-Command", command],
                         capture_output=True, text=True, timeout=timeout,
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (out.stdout or out.stderr).strip()


# ---------------------------------------------------------------- time & reminders
@skill("Get the current local date and time.")
def get_time_date(ctx):
    return dt.datetime.now().strftime("It is %I:%M %p on %A, %B %d, %Y.")


def _parse_when(minutes=None, at=None) -> float:
    if at:
        at = at.strip().lower().replace(".", "")
        for fmt in ("%I:%M %p", "%I %p", "%H:%M", "%I:%M%p", "%I%p"):
            try:
                t = dt.datetime.strptime(at, fmt).time()
                due = dt.datetime.combine(dt.date.today(), t)
                if due < dt.datetime.now():
                    due += dt.timedelta(days=1)
                return due.timestamp()
            except ValueError:
                continue
        raise ValueError(f"I couldn't understand the time '{at}'. Try like '5:30 pm'.")
    return time.time() + float(minutes or 0) * 60


@skill("Set a reminder or timer. Give either minutes from now or a clock time like '5:30 pm'.",
       params={"text": ("string", "What to remind the user about", True),
               "minutes": ("number", "Minutes from now", False),
               "at": ("string", "Clock time, e.g. '7:15 am'", False)})
def set_reminder(ctx, text, minutes=None, at=None):
    if minutes is None and not at:
        return "Tell me when: a number of minutes or a time of day."
    due = _parse_when(minutes, at)
    ctx.memory.add_reminder(due, text)
    return f"Reminder set for {time.strftime('%I:%M %p, %a %b %d', time.localtime(due))}: {text}"


@skill("List the user's upcoming reminders and timers.")
def list_reminders(ctx):
    rows = ctx.memory.pending_reminders()
    if not rows:
        return "No reminders are set."
    return "; ".join(f"{time.strftime('%I:%M %p %a', time.localtime(d))}: {t}" for _, d, t in rows)


@skill("Cancel reminders whose text contains the given words.",
       params={"text": ("string", "Words from the reminder to cancel", True)})
def cancel_reminder(ctx, text):
    gone = ctx.memory.cancel_reminder(text)
    return f"Cancelled: {'; '.join(gone)}" if gone else "No matching reminder."


# ---------------------------------------------------------------- memory
@skill("Save a lasting fact about the user or their life (preferences, people, plans).",
       params={"fact": ("string", "The fact, written as a full sentence", True)})
def remember(ctx, fact):
    ctx.memory.remember(fact)
    return "Saved to memory."


@skill("Search long-term memory and past conversations.",
       params={"query": ("string", "What to look for", True)})
def recall(ctx, query):
    facts = ctx.memory.recall(query, k=6)
    diary = ctx.memory.search_diary(query, limit=6)
    parts = []
    if facts:
        parts.append("Facts: " + " | ".join(facts))
    if diary:
        parts.append("Past conversation: " + " | ".join(diary))
    return "\n".join(parts) or "Nothing found in memory."


@skill("Delete remembered facts containing the given words.",
       params={"text": ("string", "Words in the fact to forget", True)})
def forget(ctx, text):
    gone = ctx.memory.forget(text)
    return f"Forgot: {'; '.join(gone)}" if gone else "No matching memory."


# ---------------------------------------------------------------- notes
def _note_path(ctx, title):
    safe = re.sub(r"[^\w\- ]", "", title).strip()[:80] or "note"
    return Path(ctx.cfg["notes_dir"]) / f"{safe}.txt"


@skill("Write or add to a text note.",
       params={"title": ("string", "Short note title", True),
               "text": ("string", "The note content", True)})
def write_note(ctx, title, text):
    p = _note_path(ctx, title)
    with p.open("a", encoding="utf-8") as f:
        f.write(f"[{dt.datetime.now():%Y-%m-%d %H:%M}] {text}\n")
    return f"Note saved as '{p.stem}'."


@skill("List saved notes.")
def list_notes(ctx):
    notes = sorted(Path(ctx.cfg["notes_dir"]).glob("*.txt"), key=os.path.getmtime, reverse=True)
    return ", ".join(n.stem for n in notes[:30]) or "No notes yet."


@skill("Read a saved note.", params={"title": ("string", "Note title", True)})
def read_note(ctx, title):
    p = _note_path(ctx, title)
    if not p.exists():
        cands = [n for n in Path(ctx.cfg["notes_dir"]).glob("*.txt") if title.lower() in n.stem.lower()]
        if not cands:
            return "No note with that name."
        p = cands[0]
    return p.read_text(encoding="utf-8")[-3000:]


# ---------------------------------------------------------------- apps, files, websites
_APP_ALIASES = {
    "notepad": "notepad.exe", "calculator": "calc.exe", "calc": "calc.exe",
    "file explorer": "explorer.exe", "explorer": "explorer.exe", "files": "explorer.exe",
    "paint": "mspaint.exe", "task manager": "taskmgr.exe", "command prompt": "cmd.exe",
    "cmd": "cmd.exe", "powershell": "powershell.exe", "terminal": "wt.exe",
    "settings": "ms-settings:", "control panel": "control.exe", "snipping tool": "ms-screenclip:",
    "camera": "microsoft.windows.camera:", "clock": "ms-clock:", "store": "ms-windows-store:",
}


def _start_menu_shortcuts():
    roots = [Path(os.environ.get("ProgramData", r"C:\ProgramData")) / r"Microsoft\Windows\Start Menu\Programs",
             Path(os.environ.get("APPDATA", "")) / r"Microsoft\Windows\Start Menu\Programs",
             Path.home() / "Desktop"]
    for root in roots:
        if root.exists():
            yield from root.rglob("*.lnk")


@skill("Open an application on this PC by name (e.g. Spotify, Chrome, Steam, Notepad, Settings).",
       params={"name": ("string", "App name", True)})
def open_app(ctx, name):
    key = name.lower().strip()
    if key in _APP_ALIASES:
        os.startfile(_APP_ALIASES[key])
        return f"Opened {name}."
    best, best_score = None, 0
    words = set(key.split())
    for lnk in _start_menu_shortcuts():
        stem = lnk.stem.lower()
        if "uninstall" in stem:
            continue
        score = 3 if stem == key else (2 if stem.startswith(key) else len(words & set(stem.split())) / max(len(words), 1))
        if score > best_score:
            best, best_score = lnk, score
    if best and best_score >= 0.99:
        os.startfile(str(best))
        return f"Opened {best.stem}."
    return f"I couldn't find an app called {name}."


@skill("Search the user's files by name in their Documents, Desktop and Downloads.",
       params={"query": ("string", "Part of the file name", True),
               "extension": ("string", "Optional file type, e.g. pdf", False)})
def search_files(ctx, query, extension=None):
    q = query.lower()
    ext = ("." + extension.lower().lstrip(".")) if extension else None
    hits, start = [], time.time()
    for folder in ctx.cfg.get("search_folders", []):
        for root, dirs, files in os.walk(folder):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", "__pycache__")]
            for f in files:
                if q in f.lower() and (not ext or f.lower().endswith(ext)):
                    hits.append(os.path.join(root, f))
            if len(hits) >= 15 or time.time() - start > 6:
                break
    return "\n".join(hits[:15]) or "No files found."


@skill("Open a file or folder on this PC with its default program.",
       params={"path": ("string", "Full path to the file or folder", True)})
def open_file(ctx, path):
    p = Path(path).expanduser()
    if not p.exists():
        return "That path doesn't exist."
    os.startfile(str(p))
    return f"Opened {p.name}."


@skill("Open a website in the browser (needs internet to load the page).",
       params={"site": ("string", "A URL or site name like youtube", True)})
def open_website(ctx, site):
    s = site.strip()
    if not re.match(r"^https?://", s):
        s = "https://" + (s if "." in s else s.replace(" ", "") + ".com")
    webbrowser.open(s)
    return f"Opened {s}."


# ---------------------------------------------------------------- PC control
@skill("Get computer status: battery, CPU, memory and disk space.")
def system_status(ctx):
    try:
        import psutil
    except ImportError:
        return "psutil is not installed."
    parts = [f"CPU {psutil.cpu_percent(interval=0.5):.0f}%",
             f"memory {psutil.virtual_memory().percent:.0f}% used"]
    disk = psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\")
    parts.append(f"{disk.free / 1e9:.0f} GB free on the main drive")
    bat = psutil.sensors_battery()
    if bat:
        parts.append(f"battery {bat.percent:.0f}%{' and charging' if bat.power_plugged else ''}")
    return ", ".join(parts) + "."


_VK = {"volume_up": 0xAF, "volume_down": 0xAE, "mute": 0xAD, "play_pause": 0xB3,
       "next": 0xB0, "previous": 0xB1}


@skill("Control media and volume: volume_up, volume_down, mute, play_pause, next, previous.",
       params={"action": ("string", "One of volume_up, volume_down, mute, play_pause, next, previous", True),
               "times": ("number", "How many steps for volume (default 5)", False)})
def media_control(ctx, action, times=None):
    vk = _VK.get(action)
    if vk is None:
        return "Unknown media action."
    n = int(times or (5 if action.startswith("volume") else 1))
    for _ in range(max(1, min(n, 50))):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return f"Done: {action}."


@skill("Lock the computer.")
def lock_pc(ctx):
    ctypes.windll.user32.LockWorkStation()
    return "Locked."


@skill("Shut down or restart the PC in 30 seconds, or cancel a pending shutdown.",
       params={"action": ("string", "shutdown, restart, or cancel", True)}, risky=True)
def power(ctx, action):
    flags = {"shutdown": ["/s", "/t", "30"], "restart": ["/r", "/t", "30"], "cancel": ["/a"]}
    if action not in flags:
        return "Say shutdown, restart or cancel."
    subprocess.run(["shutdown", *flags[action]], capture_output=True)
    return "Cancelled." if action == "cancel" else f"{action.title()} in 30 seconds. Say 'cancel shutdown' to stop it."


@skill("Permanently empty the Windows Recycle Bin.", risky=True)
def empty_recycle_bin(ctx):
    _ps("Clear-RecycleBin -Force -ErrorAction SilentlyContinue")
    return "Recycle Bin emptied."


@skill("Read the text currently on the clipboard.")
def read_clipboard(ctx):
    text = _ps("Get-Clipboard -Raw")
    return text[:3000] or "The clipboard is empty."


# ---------------------------------------------------------------- fun & maths
_JOKES = [
    "I told my computer I needed a break. It said: no problem, I'll go to sleep.",
    "Why do programmers prefer dark mode? Because light attracts bugs.",
    "I would tell you a UDP joke, but you might not get it.",
    "There are 10 kinds of people: those who understand binary and those who don't.",
    "My memory is excellent. It's stored locally, unlike some assistants I could mention.",
    "Why did the developer go broke? Because he used up all his cache.",
    "A SQL query walks into a bar, walks up to two tables and asks: may I join you?",
    "I'm reading a book about anti-gravity. It's impossible to put down.",
    "Debugging is like being the detective in a crime movie where you are also the murderer.",
    "Why was the computer cold? It left its Windows open.",
]
_FACTS = [
    "Honey never spoils; edible honey has been found in ancient Egyptian tombs.",
    "Octopuses have three hearts and blue blood.",
    "A day on Venus is longer than its year.",
    "Bananas are berries, but strawberries are not.",
    "The Eiffel Tower can grow about 15 centimetres taller in summer heat.",
    "Sharks existed before trees.",
    "Your brain uses roughly 20 percent of your body's energy.",
    "There are more possible chess games than atoms in the observable universe.",
    "Wombat droppings are cube shaped.",
    "The first computer bug was a real moth, found in a Harvard Mark II in 1947.",
]


@skill("Tell a joke.")
def tell_joke(ctx):
    return random.choice(_JOKES)


@skill("Share a random fun fact.")
def random_fact(ctx):
    return random.choice(_FACTS)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
        ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Constant) and type(node.value) in (int, float) and math.isfinite(node.value):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and (
            abs(right) > 1000 or (
                isinstance(left, int) and right >= 0 and left.bit_length() * right > 4096
            )
        ):
            raise ValueError("power exceeds the calculator limit")
        result = _OPS[type(node.op)](left, right)
        if isinstance(result, int) and result.bit_length() > 4096:
            raise ValueError("integer exceeds the calculator limit")
        if isinstance(result, complex) or isinstance(result, float) and not math.isfinite(result):
            raise ValueError("only finite real results are supported")
        return result
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    raise ValueError("unsupported expression")


@skill("Evaluate a real arithmetic expression, e.g. '(12.5*3)/4 + 2**8'.",
       params={"expression": ("string", "The arithmetic expression", True)})
def calculate(ctx, expression):
    expression = expression.strip()
    if not expression or len(expression) > 256:
        raise ValueError("use an arithmetic expression between 1 and 256 characters")
    expr = expression.replace("^", "**").replace("x", "*").replace("×", "*").replace("÷", "/")
    result = _eval(ast.parse(expr, mode="eval").body)
    return f"{expression} = {result}"


# ---------------------------------------------------------------- briefing
@skill("Give a briefing: time, today's schedule, deadlines, anything slipping, and computer status.")
def briefing(ctx):
    from . import planner
    hour = dt.datetime.now().hour
    greet = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    who = ctx.cfg.get("honorific") or ctx.cfg.get("user_name") or ""
    parts = [f"{greet}{', ' + who if who else ''}. {get_time_date(ctx)}"]
    if planner.canvas_configured():
        try:
            planner.sync_canvas_now(ctx.memory, ctx.cfg)
        except Exception:
            pass
    sched = planner.show_schedule(ctx, "today").split(": ", 1)[-1]
    parts.append("Today: " + sched + ".")
    report = planner.behind_report(ctx.memory)
    if report["overdue"]:
        parts.append(f"{len(report['overdue'])} item(s) overdue: " + "; ".join(t for t, _ in report["overdue"]) + ".")
    if report["soon"]:
        parts.append("Due within 48 hours: " + "; ".join(f"{t} ({planner.fmt_ts(d)})" for t, d in report["soon"]) + ".")
    if report["unplanned_soon"]:
        parts.append("I'd suggest planning time for " + ", ".join(t for t, _ in report["unplanned_soon"]) + ".")
    rem = ctx.memory.pending_reminders()
    today_end = dt.datetime.combine(dt.date.today(), dt.time(23, 59)).timestamp()
    today = [t for _, d, t in rem if d <= today_end]
    if today:
        parts.append("Reminders: " + "; ".join(today) + ".")
    parts.append("Systems: " + system_status(ctx))
    return " ".join(parts)


# ---------------------------------------------------------------- optional online
@skill("Look up a short Wikipedia summary of a topic (uses the internet).",
       params={"topic": ("string", "Topic to look up", True)}, internet=True)
def wikipedia_summary(ctx, topic):
    url = "https://en.wikipedia.org/api/rest_v1/page/summary/" + urllib.parse.quote(topic.replace(" ", "_"))
    req = urllib.request.Request(url, headers={"User-Agent": "JarvisLocalAssistant/1.0"})
    with net.urlopen(req, ctx.cfg, timeout=8, purpose="wikipedia") as r:
        data = json.loads(r.read().decode())
    return data.get("extract") or "No summary found."


SKILLS["wikipedia_summary"]["untrusted"] = True
SKILLS["read_clipboard"]["untrusted"] = True
SKILLS["read_note"]["untrusted"] = True

# Load the other skill modules (they register themselves with @skill).
from . import planner, comms, coder, nomad, online, images  # noqa: E402,F401
