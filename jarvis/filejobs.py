"""Previewed workspace copy/move jobs with persistent recovery and undo."""
import hashlib
import shutil
import os
import threading
import time
import uuid

from . import coder, planner
from .skills import skill, run

_LOCK = threading.RLock()
LIMIT = 5 * 1024 * 1024


def digest(path):
    with path.open('rb') as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError('File tasks support files up to 5 MiB.')
    return hashlib.sha256(data).hexdigest()


def jobs(ctx):
    with ctx.memory._lock:
        rows = ctx.memory.db.execute("SELECT value FROM kv WHERE key LIKE 'filejob-%' ORDER BY key DESC LIMIT 100").fetchall()
    import json
    return [json.loads(row[0]) for row in rows]


def save(ctx, job):
    job['updated'] = time.time()
    planner.kv_set(ctx.memory, 'filejob-' + job['id'], job)


def prepare(ctx, operation, source, destination):
    if ctx.cfg.get('mode') == 'talk' or ctx.cfg.get('lockdown'):
        return 'File tasks are unavailable in Talk or Lockdown.'
    if operation not in ('copy', 'move'):
        raise ValueError('Choose copy or move.')
    src, dst = coder._safe_path(ctx.cfg, source), coder._safe_path(ctx.cfg, destination)
    if src == dst or dst.exists() or not dst.parent.is_dir():
        raise ValueError('Choose a new destination in an existing workspace folder.')
    job = {'id':uuid.uuid4().hex, 'operation':operation, 'source':source, 'destination':destination,
           'digest':digest(src), 'state':'preview'}
    save(ctx, job)
    return run(ctx, 'execute_file_job', {'job_id':job['id']})


def get(ctx, job_id):
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in '0123456789abcdef' for c in job_id):
        raise ValueError('Choose a file job ID from /jobs.')
    job = planner.kv_get(ctx.memory, 'filejob-' + job_id)
    if not job:
        raise ValueError('This file job does not exist.')
    return job


def preview(ctx, job_id):
    job = get(ctx, job_id)
    return f"{job['operation']} {job['source']} to {job['destination']} inside Jarvis Code. Job {job_id}"


@skill('Execute a user-selected file job.', params={'job_id':('string','Job ID',True)},
       risky=True, manual=True, preview=preview)
def execute_file_job(ctx, job_id):
    with _LOCK:
        job = get(ctx, job_id)
        if job['state'] in ('done', 'undone'):
            return f"Job {job_id} is {job['state']}."
        src = coder._safe_path(ctx.cfg, job['source'])
        dst = coder._safe_path(ctx.cfg, job['destination'])
        temporary = dst.with_name('.jarvis-' + job_id + '.partial')
        # A restart after publishing a destination can safely finish a pending move.
        if dst.exists():
            if job['state'] != 'publishing' or digest(dst) != job['digest']:
                raise ValueError('The destination already exists or changed. Review the job.')
        else:
            if digest(src) != job['digest']:
                raise ValueError('The source changed. Prepare a new file task.')
            job['state'] = 'publishing'
            save(ctx, job)
            if temporary.exists():
                if temporary.is_symlink():
                    raise ValueError('Unexpected linked temporary file.')
                temporary.unlink()
            try:
                with src.open('rb') as source, temporary.open('xb') as target:
                    data = source.read(LIMIT + 1)
                    if len(data) > LIMIT or hashlib.sha256(data).hexdigest() != job['digest']:
                        raise ValueError('The source changed while reading.')
                    target.write(data)
                    target.flush()
                    os.fsync(target.fileno())
                os.link(temporary, dst)  # Exclusive publish, never overwrite an existing path.
            finally:
                temporary.unlink(missing_ok=True)
        if ctx.cancelled is not None and ctx.cancelled.is_set():
            return f"Stopped after publication. Review /jobs and use /resume {job_id} when ready."
        if job['operation'] == 'move' and src.exists():
            if digest(src) != job['digest']:
                raise ValueError('The source changed. The destination was kept for review.')
            src.unlink()
        job['state'] = 'done'
        save(ctx, job)
        return f"Finished {job['operation']}. Job {job_id}. Use /undo-file {job_id} to reverse it."


def undo_preview(ctx, job_id):
    job = get(ctx, job_id)
    return f"undo {job['operation']} from {job['source']} to {job['destination']}. Job {job_id}"


@skill('Undo a completed user-selected file job.', params={'job_id':('string','Job ID',True)},
       risky=True, manual=True, preview=undo_preview)
def undo_file_job(ctx, job_id):
    with _LOCK:
        job = get(ctx, job_id)
        if job['state'] == 'undone':
            return 'This file job was already undone.'
        if job['state'] not in ('done', 'undoing'):
            raise ValueError('Finish or resume this job before undoing it.')
        src = coder._safe_path(ctx.cfg, job['source'])
        dst = coder._safe_path(ctx.cfg, job['destination'])
        if not dst.exists():
            if job['state'] == 'undoing' and (job['operation'] == 'copy' or src.exists() and digest(src) == job['digest']):
                job['state'] = 'undone'
                save(ctx, job)
                return 'File job undone.'
            raise ValueError('The destination is missing. Review the files.')
        if digest(dst) != job['digest']:
            raise ValueError('The destination changed. Undo was blocked.')
        if job['operation'] == 'move':
            if src.exists():
                if job['state'] != 'undoing' or digest(src) != job['digest']:
                    raise ValueError('The original source path is occupied.')
            else:
                job['state'] = 'undoing'
                save(ctx, job)
                os.link(dst, src)
        job['state'] = 'undoing'
        save(ctx, job)
        dst.unlink()
        job['state'] = 'undone'
        save(ctx, job)
        return 'File job undone.'


# ======================================================================
# Selected-folder file tasks
#
# These work only inside folders the user explicitly selected in setup (file_folders).
# They are separate from the Jarvis Code workspace above. Every change is previewed as an
# exact list of steps, journaled step by step so an interrupted task can resume, and can be
# undone while the affected files are unchanged. Deletion moves items into a recoverable
# ".Jarvis Recycle" folder inside the same selected folder.
# ======================================================================
import stat
from pathlib import Path, PureWindowsPath

TRASH = ".Jarvis Recycle"
MAX_FILE_BYTES = 512 * 1024 * 1024
MAX_TASK_BYTES = 2 * 1024 * 1024 * 1024
MAX_STEPS = 500
MAX_LIST = 500
MAX_SCAN = 20000
HASH_LIMIT = 64 * 1024 * 1024
CATEGORIES = {
    "Images": {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic", ".bmp", ".tif", ".tiff", ".svg"},
    "Documents": {".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg"},
    "Video": {".mp4", ".mov", ".mkv", ".avi", ".webm", ".wmv"},
    "Archives": {".zip", ".7z", ".rar", ".tar", ".gz"},
    "Code": {".py", ".js", ".ts", ".html", ".css", ".json", ".java", ".c", ".cpp", ".cs", ".go", ".rs", ".ps1"},
}
LIMITS_TEXT = (f"File tasks work only inside your selected folders, up to {MAX_STEPS} steps, "
               f"{MAX_FILE_BYTES // 1024 ** 2} MiB per copied file and {MAX_TASK_BYTES // 1024 ** 3} GiB per task. "
               "Links and junctions are not followed. Existing files are never overwritten. "
               f"Deleted items go to the {TRASH} folder inside the same selected folder.")
_REPARSE = 0x400


def _reserved_name(part):
    """True for Windows device names such as CON or NUL, on every platform."""
    import ntpath
    if hasattr(ntpath, "isreserved"):
        return ntpath.isreserved(part)
    return PureWindowsPath(part).is_reserved()


def folder_roots(cfg):
    """The user's selected file-task folders, excluding anything overlapping Jarvis Code."""
    code = Path(cfg.get("code_dir") or "").expanduser().resolve()
    roots = []
    for value in cfg.get("file_folders") or []:
        root = Path(value).expanduser().resolve()
        if root == code or code in root.parents or root in code.parents or not root.is_dir():
            continue
        roots.append(root)
    return roots


def _is_link(path):
    try:
        info = os.lstat(path)
    except FileNotFoundError:
        return False
    if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & _REPARSE:
        return True
    return bool(getattr(os.path, "isjunction", lambda p: False)(path))


def _root(cfg, index):
    roots = folder_roots(cfg)
    if type(index) is not int or not 0 <= index < len(roots):
        raise ValueError("Choose one of your selected file-task folders in Setup.")
    return roots[index]


def _clean_relative(value, allow_root=False):
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if not text:
        if allow_root:
            return ()
        raise ValueError("Choose a file or folder.")
    parts = PureWindowsPath(text).parts
    if PureWindowsPath(text).anchor or any(
        part in ("..", ".") or ":" in part or part.endswith((" ", ".")) or
        os.path.basename(part) != part or _reserved_name(part) or part == TRASH
        for part in parts
    ):
        raise ValueError(f"Use a path inside the selected folder: {value}")
    return parts


def resolve(cfg, index, relative, allow_root=False):
    """Return (root, path) for a relative path, refusing traversal and any linked component."""
    root = _root(cfg, index)
    parts = _clean_relative(relative, allow_root)
    path = root
    for part in parts:
        path = path / part
        if _is_link(path):
            raise ValueError(f"{'/'.join(parts)} goes through a link or junction. Jarvis does not follow links.")
    if path != root and root not in path.parents:
        raise ValueError("That path is outside the selected folder.")
    return root, path


def _rel(root, path):
    return path.relative_to(root).as_posix()


def _file_digest(path, limit=MAX_FILE_BYTES):
    hasher = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(block)
            if size > limit:
                raise ValueError(f"{path.name} is larger than the {limit // 1024 ** 2} MiB limit for this action.")
            hasher.update(block)
    return hasher.hexdigest()


def _fingerprint(path):
    """Identify a file by content or a folder by its names and sizes, to detect later changes."""
    if path.is_dir() and not _is_link(path):
        entries = []
        for count, item in enumerate(sorted(path.rglob("*"))):
            if count >= MAX_SCAN:
                raise ValueError(f"{path.name} contains too many items for one task.")
            if _is_link(item):
                raise ValueError(f"{path.name} contains a link or junction. Jarvis will not move it.")
            info = item.stat()
            entries.append(f"{item.relative_to(path).as_posix()}|{info.st_size if item.is_file() else 'dir'}")
        return "dir:" + hashlib.sha256("\n".join(entries).encode()).hexdigest()
    info = path.stat()
    if info.st_size > HASH_LIMIT:
        # Very large files are identified by size and modification time to keep previews fast.
        return f"meta:{info.st_size}:{info.st_mtime_ns}"
    return "file:" + _file_digest(path, limit=float("inf"))


def browse(cfg, index, relative=""):
    root, folder = resolve(cfg, index, relative, allow_root=True)
    if not folder.is_dir():
        raise ValueError("That folder does not exist.")
    items = []
    with os.scandir(folder) as entries:
        for entry in sorted(entries, key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold())):
            if entry.name == TRASH and folder == root:
                continue
            if len(items) >= MAX_LIST:
                break
            link = _is_link(entry.path)
            info = entry.stat(follow_symlinks=False)
            items.append({"name": entry.name, "path": _rel(root, Path(entry.path)),
                          "type": "link" if link else "folder" if entry.is_dir(follow_symlinks=False) else "file",
                          "size": info.st_size, "modified": info.st_mtime})
    return {"root": str(root), "path": _rel(root, folder) if folder != root else "", "items": items,
            "truncated": len(items) >= MAX_LIST, "limits": LIMITS_TEXT}


def search(cfg, index, query, relative=""):
    query = str(query or "").strip().casefold()
    if not query or len(query) > 200:
        raise ValueError("Enter part of a file name to find.")
    root, folder = resolve(cfg, index, relative, allow_root=True)
    found, scanned = [], 0
    for current, dirs, files in os.walk(folder, followlinks=False):
        dirs[:] = sorted(d for d in dirs if d != TRASH and not _is_link(os.path.join(current, d)))
        for name in sorted(dirs + files):
            scanned += 1
            if query in name.casefold():
                path = Path(current) / name
                found.append({"name": name, "path": _rel(root, path), "type": "folder" if path.is_dir() else "file"})
            if len(found) >= MAX_LIST or scanned >= MAX_SCAN:
                return {"results": found, "truncated": True, "limits": LIMITS_TEXT}
    return {"results": found, "truncated": False, "limits": LIMITS_TEXT}


def _category(name):
    suffix = Path(name).suffix.lower()
    return next((label for label, suffixes in CATEGORIES.items() if suffix in suffixes), "Other")


def plan_task(cfg, index, action, spec):
    """Turn a request into exact steps. Nothing on disk changes here."""
    root = _root(cfg, index)
    steps = []
    if action == "mkdir":
        _, path = resolve(cfg, index, spec.get("path"))
        steps.append({"op": "mkdir", "dst": _rel(root, path)})
    elif action == "rename":
        _, source = resolve(cfg, index, spec.get("path"))
        new_name = str(spec.get("new_name") or "").strip()
        _clean_relative(new_name)
        if "/" in new_name or "\\" in new_name:
            raise ValueError("A new name cannot contain a folder separator. Use Move instead.")
        steps.append({"op": "move", "src": _rel(root, source), "dst": _rel(root, source.parent / new_name)})
    elif action in ("copy", "move"):
        paths = spec.get("paths") or ([spec["path"]] if spec.get("path") else [])
        _, target = resolve(cfg, index, spec.get("destination"), allow_root=True)
        for value in paths:
            _, source = resolve(cfg, index, value)
            steps.append({"op": action, "src": _rel(root, source), "dst": _rel(root, target / source.name)})
    elif action == "delete":
        job_hint = uuid.uuid4().hex[:8]
        for value in spec.get("paths") or ([spec["path"]] if spec.get("path") else []):
            _, path = resolve(cfg, index, value)
            steps.append({"op": "delete", "src": _rel(root, path),
                          "dst": f"{TRASH}/{time.strftime('%Y-%m-%d')} {job_hint}/{_rel(root, path)}"})
    elif action == "organize":
        _, folder = resolve(cfg, index, spec.get("path"), allow_root=True)
        if not folder.is_dir():
            raise ValueError("Choose a folder to organise.")
        created = set()
        for entry in sorted(folder.iterdir(), key=lambda p: p.name.casefold()):
            if not entry.is_file() or _is_link(entry) or entry.name.startswith("."):
                continue
            label = _category(entry.name)
            target = folder / label
            if label not in created and not target.exists():
                steps.append({"op": "mkdir", "dst": _rel(root, target)})
            created.add(label)
            steps.append({"op": "move", "src": _rel(root, entry), "dst": _rel(root, target / entry.name)})
    else:
        raise ValueError("Choose browse, search, create folder, rename, copy, move, delete or organise.")
    if not steps:
        raise ValueError("There is nothing to change.")
    return _validate(cfg, root, steps)


def _validate(cfg, root, steps):
    if len(steps) > MAX_STEPS:
        raise ValueError(f"This task has {len(steps)} steps. The limit is {MAX_STEPS}. Choose fewer items.")
    created, claimed, removed, total = set(), set(), set(), 0
    for step in steps:
        dst = root / step["dst"]
        key = step["dst"].casefold()
        if key in claimed or (dst.exists() or _is_link(dst)) and key not in removed:
            raise ValueError(f"{step['dst']} already exists. Jarvis never overwrites. Choose another name.")
        parent = step["dst"].rpartition("/")[0]
        if step["op"] != "delete" and not ((root / parent).is_dir() or parent.casefold() in created):
            raise ValueError(f"The folder for {step['dst']} does not exist. Create it first.")
        claimed.add(key)
        if step["op"] == "mkdir":
            created.add(key)
            continue
        src = root / step["src"]
        if not src.exists() or _is_link(src):
            raise ValueError(f"{step['src']} does not exist or is a link.")
        if src.is_dir() and (dst == src or src in dst.parents):
            raise ValueError("A folder cannot be moved into itself.")
        if step["op"] == "copy":
            if src.is_dir():
                raise ValueError("Copy supports files. Create a folder and copy the files into it.")
            size = src.stat().st_size
            if size > MAX_FILE_BYTES:
                raise ValueError(f"{step['src']} is larger than {MAX_FILE_BYTES // 1024 ** 2} MiB.")
            total += size
        step["fingerprint"] = _fingerprint(src)
        step["kind"] = "folder" if src.is_dir() else "file"
        removed.add(step["src"].casefold())
        step["state"] = "pending"
    if total > MAX_TASK_BYTES:
        raise ValueError(f"This task copies more than {MAX_TASK_BYTES // 1024 ** 3} GiB.")
    for step in steps:
        step.setdefault("state", "pending")
    return steps


_VERBS = {"mkdir": "Create folder", "copy": "Copy", "move": "Move", "delete": "Move to Jarvis Recycle"}


def describe_steps(steps, limit=None):
    lines = []
    for number, step in enumerate(steps, 1):
        verb = _VERBS[step["op"]]
        if step["op"] == "move" and step["src"].rpartition("/")[0] == step["dst"].rpartition("/")[0]:
            verb = "Rename"
        lines.append(f"{number}. {verb} {step['dst']}" if step["op"] == "mkdir" else
                     f"{number}. {verb} {step['src']} to {step['dst']}")
    if limit and len(lines) > limit:
        lines = lines[:limit] + [f"... and {len(lines) - limit} more steps shown in File tasks"]
    return "\n".join(lines)


def prepare_folder_task(ctx, index, action, spec):
    if ctx.cfg.get("mode") == "talk" or ctx.cfg.get("lockdown"):
        raise ValueError("File tasks are unavailable in Talk or Lockdown.")
    steps = plan_task(ctx.cfg, index, action, spec or {})
    root = _root(ctx.cfg, index)
    job = {"id": uuid.uuid4().hex, "kind": "folder", "root": str(root), "root_index": index,
           "action": action, "steps": steps, "state": "preview", "created": time.time()}
    _save_folder_job(ctx, job)
    message = run(ctx, "execute_folder_job", {"job_id": job["id"]})
    return {"job_id": job["id"], "preview": describe_steps(steps), "steps": steps, "message": message,
            "limits": LIMITS_TEXT, "pending": ctx.pending}


def _save_folder_job(ctx, job):
    job["updated"] = time.time()
    planner.kv_set(ctx.memory, "folderjob-" + job["id"], job)


def folder_jobs(ctx):
    import json
    with ctx.memory._lock:
        rows = ctx.memory.db.execute(
            "SELECT value FROM kv WHERE key LIKE 'folderjob-%'").fetchall()
    jobs = [json.loads(row[0]) for row in rows]
    return sorted(jobs, key=lambda job: job.get("created", 0), reverse=True)[:50]


def _get_folder_job(ctx, job_id):
    if not isinstance(job_id, str) or len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
        raise ValueError("Choose a file task from the history.")
    job = planner.kv_get(ctx.memory, "folderjob-" + job_id)
    if not job:
        raise ValueError("This file task does not exist.")
    return job


def _job_root(ctx, job):
    root = Path(job["root"])
    if root not in folder_roots(ctx.cfg):
        raise ValueError("This task's folder is no longer selected for file tasks.")
    return root


def _safe_child(root, relative):
    path = root
    for part in PureWindowsPath(relative).parts:
        if part in ("..", ".") or ":" in part:
            raise ValueError("Invalid path in the task journal.")
        path = path / part
        if _is_link(path):
            raise ValueError(f"{relative} now goes through a link. Review the files.")
    return path


def _publish_copy(src, dst, fingerprint, job_id):
    temporary = dst.with_name(f".jarvis-{job_id[:12]}.partial")
    if _is_link(temporary):
        raise ValueError("Unexpected linked temporary file.")
    temporary.unlink(missing_ok=True)
    try:
        hasher = hashlib.sha256()
        with src.open("rb") as source, temporary.open("xb") as target:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                hasher.update(block)
                target.write(block)
            target.flush()
            os.fsync(target.fileno())
        if fingerprint.startswith("file:") and "file:" + hasher.hexdigest() != fingerprint:
            raise ValueError(f"{src.name} changed while it was being copied.")
        shutil.copystat(src, temporary)
        _rename_no_replace(temporary, dst)
    finally:
        temporary.unlink(missing_ok=True)


def _rename_no_replace(src, dst):
    """Rename without replacing an existing destination."""
    if os.name == "nt":
        os.rename(src, dst)  # Windows refuses to replace an existing path.
        return
    if src.is_dir():
        if dst.exists() or _is_link(dst):
            raise FileExistsError(f"{dst.name} already exists.")
        os.rename(src, dst)
        return
    try:
        os.link(src, dst)  # Fails if the destination exists.
    except OSError as error:
        if isinstance(error, FileExistsError):
            raise
        if dst.exists() or _is_link(dst):
            raise FileExistsError(f"{dst.name} already exists.") from None
        os.rename(src, dst)
        return
    os.unlink(src)


def _move(src, dst):
    try:
        _rename_no_replace(src, dst)
    except OSError as error:
        if getattr(error, "errno", None) != 18 or src.is_dir():  # 18 = EXDEV, another drive
            raise
        shutil.copy2(src, dst.with_name(dst.name + ".jarvis-partial"))
        _rename_no_replace(dst.with_name(dst.name + ".jarvis-partial"), dst)
        src.unlink()


def _do_step(root, step, job_id):
    dst = _safe_child(root, step["dst"])
    if step["op"] == "mkdir":
        if dst.is_dir() and step["state"] == "running":
            return
        dst.mkdir()
        return
    src = _safe_child(root, step["src"])
    if step["state"] == "running" and dst.exists() and _fingerprint(dst) == step["fingerprint"]:
        # Resume after an interruption that happened after publishing.
        if step["op"] != "copy" and src.exists() and _fingerprint(src) == step["fingerprint"] and step["kind"] == "file":
            src.unlink()
        return
    if not src.exists() or _fingerprint(src) != step["fingerprint"]:
        raise ValueError(f"{step['src']} changed or is missing since the preview. Prepare a new task.")
    if dst.exists() or _is_link(dst):
        raise ValueError(f"{step['dst']} now exists. Jarvis will not overwrite it.")
    if step["op"] == "copy":
        _publish_copy(src, dst, step["fingerprint"], job_id)
    else:
        if step["op"] == "delete":
            dst.parent.mkdir(parents=True, exist_ok=True)
        _move(src, dst)


def _folder_preview(ctx, job_id):
    job = _get_folder_job(ctx, job_id)
    verb = "resume" if job["state"] != "preview" else "run"
    return f"{verb} file task in {job['root']}:\n{describe_steps(job['steps'], limit=25)}"


@skill("Run a previewed file task in a selected folder.", params={"job_id": ("string", "Task ID", True)},
       risky=True, manual=True, preview=_folder_preview)
def execute_folder_job(ctx, job_id):
    with _LOCK:
        job = _get_folder_job(ctx, job_id)
        if job["state"] in ("done", "undone", "undoing"):
            return f"This file task is {job['state']}."
        root = _job_root(ctx, job)
        job["state"] = "running"
        _save_folder_job(ctx, job)
        for number, step in enumerate(job["steps"], 1):
            if step["state"] == "done":
                continue
            if ctx.cancelled is not None and ctx.cancelled.is_set():
                job["state"] = "interrupted"
                _save_folder_job(ctx, job)
                return f"Stopped after {number - 1} steps. Resume or undo it from File tasks."
            step["state"] = "running"
            _save_folder_job(ctx, job)
            try:
                _do_step(root, step, job["id"])
            except (OSError, ValueError) as error:
                step["error"] = str(error)[:300]
                job["state"] = "failed"
                _save_folder_job(ctx, job)
                done = sum(s["state"] == "done" for s in job["steps"])
                return (f"Step {number} failed: {error}. {done} steps finished. "
                        "Fix the problem and resume, or undo the finished steps.")
            step["state"] = "done"
            step.pop("error", None)
            _save_folder_job(ctx, job)
        job["state"] = "done"
        _save_folder_job(ctx, job)
        return f"Finished {len(job['steps'])} steps. Undo is available in File tasks while the files are unchanged."


def _undo_preview(ctx, job_id):
    job = _get_folder_job(ctx, job_id)
    finished = [s for s in job["steps"] if s["state"] in ("done", "undoing")]
    lines = []
    for step in reversed(finished):
        if step["op"] == "mkdir":
            lines.append(f"Remove empty folder {step['dst']}")
        elif step["op"] == "copy":
            lines.append(f"Delete the copy at {step['dst']}")
        else:
            lines.append(f"Move {step['dst']} back to {step['src']}")
    return "undo this file task:\n" + "\n".join(lines[:25]) + ("" if len(lines) <= 25 else f"\n... and {len(lines) - 25} more")


@skill("Undo a finished or partly finished file task.", params={"job_id": ("string", "Task ID", True)},
       risky=True, manual=True, preview=_undo_preview)
def undo_folder_job(ctx, job_id):
    with _LOCK:
        job = _get_folder_job(ctx, job_id)
        if job["state"] == "undone":
            return "This file task was already undone."
        root = _job_root(ctx, job)
        finished = [s for s in job["steps"] if s["state"] in ("done", "undoing")]
        if not finished:
            return "No steps of this task have run. Nothing to undo."
        problems = []
        for step in finished:  # Check everything before changing anything.
            if step["state"] == "undoing":
                continue
            dst = _safe_child(root, step["dst"])
            if step["op"] == "mkdir":
                continue
            src = _safe_child(root, step["src"])
            if not dst.exists() or _fingerprint(dst) != step["fingerprint"]:
                problems.append(f"{step['dst']} changed or is missing")
            elif step["op"] != "copy" and (src.exists() or _is_link(src)):
                problems.append(f"{step['src']} is occupied")
        if problems:
            return "Undo was blocked so nothing is half restored: " + "; ".join(problems[:10]) + "."
        job["state"] = "undoing"
        _save_folder_job(ctx, job)
        kept = []
        for step in reversed(finished):
            step["state"] = "undoing"
            _save_folder_job(ctx, job)
            dst = _safe_child(root, step["dst"])
            if step["op"] == "mkdir":
                try:
                    dst.rmdir()
                except FileNotFoundError:
                    pass
                except OSError:
                    kept.append(step["dst"])
            elif step["op"] == "copy":
                if dst.exists():
                    dst.unlink()
            else:
                src = _safe_child(root, step["src"])
                if dst.exists() and not src.exists():
                    src.parent.mkdir(parents=True, exist_ok=True)
                    _move(dst, src)
                if step["op"] == "delete":
                    _prune_empty(root / TRASH, dst.parent)
            step["state"] = "undone"
            _save_folder_job(ctx, job)
        job["state"] = "undone"
        _save_folder_job(ctx, job)
        note = f" Kept non-empty folders: {', '.join(kept)}." if kept else ""
        return "File task undone." + note


def _prune_empty(stop, folder):
    while folder != stop and stop in folder.parents:
        try:
            folder.rmdir()
        except OSError:
            return
        folder = folder.parent
