"""Approved app actions: start a program the user approved, optionally with one file.

Scope is deliberately small. An action names one program by absolute path and, optionally,
a file chosen from the user's selected file-task folders. Every run shows the exact command and
needs confirmation. Programs that run scripts or arbitrary commands are refused, because their
arguments would be code. Jarvis tracks what it started so Stop can close it, and reports a quick
failure (missing program, immediate non-zero exit) instead of claiming success.
"""
import os
import re
import subprocess
import threading
import time
from pathlib import Path

from . import config, filejobs, secure
from .skills import skill

MAX_ACTIONS = 20
STARTUP_CHECK_SECONDS = 2.0
# Script hosts and shells: approving them would approve any command.
BLOCKED_PROGRAMS = {
    "cmd", "powershell", "pwsh", "wscript", "cscript", "mshta", "rundll32", "regsvr32", "reg", "regedit",
    "schtasks", "msiexec", "wmic", "bash", "sh", "zsh", "dash", "fish", "python", "pythonw", "py", "node",
    "perl", "ruby", "php", "java", "javaw", "osascript", "bitsadmin", "certutil", "curl", "wget", "ssh",
    "scp", "ftp", "sudo", "runas", "taskkill", "format", "diskpart", "del", "rm", "shutdown",
}
_NAME = re.compile(r"[\w .,'()-]{1,60}")
_LOCK = threading.Lock()
_STARTED = []  # (action name, Popen)


def _stem(program):
    return re.sub(r"\d+(\.\d+)*$", "", Path(program).name.lower().rsplit(".", 1)[0])


def validate(action):
    """Return a clean action definition or raise ValueError with the reason."""
    if not isinstance(action, dict):
        raise ValueError("An app action needs a name and a program.")
    name = str(action.get("name", "")).strip()
    if not _NAME.fullmatch(name):
        raise ValueError("Use a short name with letters, numbers and simple punctuation.")
    program = Path(str(action.get("program", "")).strip().strip('"')).expanduser()
    if not program.is_absolute() or not program.is_file():
        raise ValueError(f"{program} is not an existing program. Use its full path.")
    program = program.resolve()
    if os.name == "nt" and program.suffix.lower() != ".exe":
        raise ValueError("On Windows, choose an .exe program. Shortcuts, scripts and batch files are not allowed.")
    if _stem(program) in BLOCKED_PROGRAMS:
        raise ValueError(f"{program.name} can run any command, so it cannot be an approved app action.")
    takes_file = bool(action.get("takes_file"))
    return {"name": name, "program": str(program), "takes_file": takes_file}


def actions(cfg):
    clean = []
    for item in cfg.get("app_actions") or []:
        try:
            clean.append(validate(item))
        except ValueError:
            continue
    return clean[:MAX_ACTIONS]


def _find(cfg, name):
    for item in actions(cfg):
        if item["name"] == name:
            return item
    raise ValueError("Choose one of your approved app actions.")


def _command(cfg, name, file=""):
    item = _find(cfg, name)
    command = [item["program"]]
    if item["takes_file"]:
        root_index, _, relative = str(file or "").partition(":")
        if not relative:
            raise ValueError("Choose a file from a selected folder, as folder number:path.")
        _, path = filejobs.resolve(cfg, int(root_index), relative)
        if not path.is_file():
            raise ValueError("That file does not exist.")
        command.append(str(path))
    elif file:
        raise ValueError("This app action does not take a file.")
    return item, command


def _preview(ctx, name, file=""):
    _, command = _command(ctx.cfg, name, file)
    return "start " + " ".join(f'"{part}"' for part in command) + ". Use Stop app actions to close it"


@skill("Run one of the user's approved app actions.",
       params={"name": ("string", "Approved action name", True),
               "file": ("string", "File as folder number:path, if the action takes a file", False)},
       risky=True, manual=True, preview=_preview)
def run_app_action(ctx, name, file=""):
    item, command = _command(ctx.cfg, name, file)
    try:
        # No shell and a fixed argument list: the file path is passed as one argument.
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.PIPE, close_fds=True)
    except OSError as error:
        return f"{item['name']} could not start: {error.strerror or error}."
    secure.audit("app_action_started", {"name": item["name"], "program": Path(item["program"]).name,
                                        "file": Path(command[1]).name if len(command) > 1 else ""})
    deadline = time.monotonic() + STARTUP_CHECK_SECONDS
    while time.monotonic() < deadline and process.poll() is None:
        if ctx.cancelled is not None and ctx.cancelled.is_set():
            break
        time.sleep(0.05)
    code = process.poll()
    if code not in (None, 0):
        error = (process.stderr.read(400) if process.stderr else b"").decode(errors="replace").strip()
        return f"{item['name']} stopped right away with exit code {code}." + (f" {error}" if error else "")
    with _LOCK:
        _STARTED.append((item["name"], process))
    return (f"Started {item['name']}." if code is None else f"{item['name']} ran and finished.")


def running():
    with _LOCK:
        _STARTED[:] = [(name, process) for name, process in _STARTED if process.poll() is None]
        return [{"name": name, "pid": process.pid} for name, process in _STARTED]


def stop_all():
    """Close programs that Jarvis started. Programs the user opened themselves are not touched."""
    with _LOCK:
        started = list(_STARTED)
        _STARTED.clear()
    stopped = []
    for name, process in started:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(5)
            except subprocess.TimeoutExpired:
                process.kill()
            stopped.append(name)
    if stopped:
        secure.audit("app_actions_stopped", {"names": stopped})
    return stopped


def save_actions(cfg, items):
    clean = [validate(item) for item in items]
    if len(clean) > MAX_ACTIONS:
        raise ValueError(f"Approve at most {MAX_ACTIONS} app actions.")
    if len({item["name"] for item in clean}) != len(clean):
        raise ValueError("Each app action needs a different name.")
    updated = {**cfg, "app_actions": clean}
    config.save(updated)
    cfg.update(updated)
    return clean
