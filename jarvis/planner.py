"""Planner: tasks, calendar, Canvas, and weekly planning so nothing slips.

Canvas works through your private Canvas *calendar feed* link (Canvas > Calendar >
Calendar Feed). No API key needed. Jarvis keeps a copy, so it works offline too.
Optionally, a Canvas access token lets Jarvis also see what you've already submitted.
"""
import datetime as dt
import json
import math
import re
import time
import urllib.parse
import urllib.request
import uuid
from collections import defaultdict, deque
from pathlib import Path

from . import net, secure
from .config import APP_DIR
from .skills import skill

CANVAS_CACHE = APP_DIR / "canvas.ics"
DAY = 86400


# ================================================================ storage
def init_db(memory):
    with memory._lock, memory.db as db:
        db.executescript(
            """
            BEGIN IMMEDIATE;
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY, uid TEXT UNIQUE, title TEXT, course TEXT, due REAL,
                est_min INTEGER, priority INTEGER DEFAULT 2, status TEXT DEFAULT 'open',
                source TEXT, url TEXT, notes TEXT, nudged INTEGER DEFAULT 0, created REAL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, uid TEXT UNIQUE, title TEXT, start REAL, end REAL,
                location TEXT, source TEXT, notes TEXT, task_id INTEGER, nudged INTEGER DEFAULT 0,
                blocks_time INTEGER NOT NULL DEFAULT 1);
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        if "blocks_time" not in {row[1] for row in db.execute("PRAGMA table_info(events)")}:
            db.execute("ALTER TABLE events ADD COLUMN blocks_time INTEGER NOT NULL DEFAULT 1")


def kv_get(memory, key, default=None):
    with memory._lock:
        row = memory.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
    return json.loads(row[0]) if row else default


def kv_set(memory, key, value):
    with memory._lock:
        memory.db.execute("INSERT OR REPLACE INTO kv(key, value) VALUES (?,?)", (key, json.dumps(value)))
        memory.db.commit()


def _q(memory, sql, args=()):
    with memory._lock:
        cur = memory.db.execute(sql, args)
        memory.db.commit()
        return cur.fetchall()


# ================================================================ date helpers
_WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


def parse_date(text) -> dt.date:
    t = (text or "today").strip().lower()
    today = dt.date.today()
    if t in ("today", "tonight", "now"):
        return today
    if t == "tomorrow":
        return today + dt.timedelta(days=1)
    m = re.match(r"in (\d+) days?", t)
    if m:
        return today + dt.timedelta(days=int(m.group(1)))
    nxt = t.startswith("next ")
    t2 = t.replace("next ", "").replace("this ", "")
    if t2 in _WEEKDAYS:
        delta = (_WEEKDAYS.index(t2) - today.weekday()) % 7
        if delta == 0 or nxt:
            delta = delta or 7
        return today + dt.timedelta(days=delta)
    t3 = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", t.replace(",", ""))
    t3 = re.sub(r"^(on|the)\s+", "", t3).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m/%d", "%b %d", "%B %d", "%b %d %Y", "%B %d %Y",
                "%d %b", "%d %B"):
        try:
            d = dt.datetime.strptime(t3, fmt).date()
            if "%Y" not in fmt and "%y" not in fmt:
                d = d.replace(year=today.year)
                if d < today - dt.timedelta(days=60):
                    d = d.replace(year=today.year + 1)
            return d
        except ValueError:
            continue
    raise ValueError(f"I couldn't understand the date '{text}'.")


def parse_time(text, default=None) -> dt.time:
    if not text:
        if default is None:
            raise ValueError("A time is needed.")
        return default
    t = text.strip().lower().replace(".", "").replace(" ", "")
    if t in ("noon", "midday"):
        return dt.time(12, 0)
    if t == "midnight":
        return dt.time(23, 59)
    for fmt in ("%I:%M%p", "%I%p", "%H:%M", "%H"):
        try:
            return dt.datetime.strptime(t, fmt).time()
        except ValueError:
            continue
    raise ValueError(f"I couldn't understand the time '{text}'.")


def at(date: dt.date, tm: dt.time) -> float:
    return dt.datetime.combine(date, tm).timestamp()


def fmt_ts(ts, with_day=True) -> str:
    d = dt.datetime.fromtimestamp(ts)
    tm = d.strftime("%I:%M %p").lstrip("0")
    if not with_day:
        return tm
    today = dt.date.today()
    if d.date() == today:
        day = "today"
    elif d.date() == today + dt.timedelta(days=1):
        day = "tomorrow"
    elif 0 < (d.date() - today).days < 7:
        day = d.strftime("%A")
    else:
        day = d.strftime("%a %b %d")
    return f"{day} {tm}"


def _guess_minutes(title: str, default: int) -> int:
    t = title.lower()
    if re.search(r"\b(exam|final|midterm)\b", t):
        return 240
    if re.search(r"\b(test|quiz)\b", t):
        return 120
    if re.search(r"\b(essay|paper|project|report|lab)\b", t):
        return 180
    if re.search(r"\b(discussion|reply|post|reading|response)\b", t):
        return 45
    return default


# ================================================================ Canvas (iCal feed)
def _unescape(v):
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _ics_time(value: str, params: str):
    """Returns (timestamp, all_day)."""
    v = value.strip()
    if "VALUE=DATE" in params.upper().split(";") or re.fullmatch(r"\d{8}", v):
        d = dt.datetime.strptime(v, "%Y%m%d")
        return d.timestamp(), True
    if v.endswith("Z"):
        d = dt.datetime.strptime(v, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        return d.timestamp(), False
    d = dt.datetime.strptime(v[:15], "%Y%m%dT%H%M%S")  # local / TZID: treat as local time
    return d.timestamp(), False


def parse_ics(text: str) -> list:
    lines = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    items, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            items.append(cur)
            cur = None
        elif cur is not None and ":" in line:
            key, value = line.split(":", 1)
            name, _, params = key.partition(";")
            cur[name.upper()] = (value, params)
    out = []
    for e in items:
        try:
            start, all_day = _ics_time(*e["DTSTART"])
            if "DTEND" in e:
                end = _ics_time(*e["DTEND"])[0]
            elif all_day:
                # DATE ranges end at local midnight, including across clock changes.
                duration = e.get("DURATION", ("P1D", ""))[0]
                match = re.fullmatch(r"\+?P(\d+)([DW])", duration, re.I)
                if not match:
                    continue
                days = int(match[1]) * (7 if match[2].upper() == "W" else 1)
                end = at(dt.datetime.fromtimestamp(start).date() + dt.timedelta(days=days), dt.time.min)
            else:
                end = start
        except (KeyError, ValueError, OverflowError):
            continue
        out.append({
            "uid": e.get("UID", ("", ""))[0],
            "title": _unescape(e.get("SUMMARY", ("(untitled)", ""))[0]),
            "start": start, "end": end, "all_day": all_day,
            "blocks_time": e.get("TRANSP", ("", ""))[0].strip().upper() != "TRANSPARENT",
            "description": _unescape(e.get("DESCRIPTION", ("", ""))[0])[:500],
            "url": e.get("URL", ("", ""))[0],
            "location": _unescape(e.get("LOCATION", ("", ""))[0]),
        })
    return out


def canvas_configured(cfg=None) -> bool:
    return secure.has_secret("canvas_feed_url")


def sync_canvas_now(memory, cfg, force=False) -> str:
    url = secure.get_secret("canvas_feed_url")
    if not url:
        return "Canvas isn't connected. Run 'python -m jarvis setup' and paste your Canvas calendar feed link."
    last = kv_get(memory, "canvas_last_sync", 0)
    note = ""
    if force or time.time() - last > 3 * 3600 or not CANVAS_CACHE.exists():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "JarvisLocalAssistant/1.0"})
            with net.urlopen(req, cfg, timeout=20, purpose="canvas_ics") as r:
                data = r.read(5_000_000).decode("utf-8", errors="replace")
            if "BEGIN:VCALENDAR" not in data:
                raise ValueError("that link didn't return a calendar")
            CANVAS_CACHE.write_text(data, encoding="utf-8")
            kv_set(memory, "canvas_last_sync", time.time())
            secure.audit("canvas_sync", {"host": urllib.parse.urlparse(url).hostname})
        except Exception as e:
            if not CANVAS_CACHE.exists():
                return f"Couldn't reach Canvas ({e}) and there's no saved copy yet."
            note = f" (Offline: using the copy from {fmt_ts(last)}.)"
    items = parse_ics(CANVAS_CACHE.read_text(encoding="utf-8"))
    new_tasks = new_events = 0
    default_min = cfg.get("default_task_minutes", 60)
    for it in items:
        m = re.search(r"\[([^\]]+)\]\s*$", it["title"])
        course = m.group(1) if m else ""
        title = it["title"][:m.start()].strip() if m else it["title"]
        if "assignment" in it["uid"].lower() or "assignment" in it["url"].lower():
            due = it["start"]
            if it["all_day"]:
                due = at(dt.datetime.fromtimestamp(due).date(), dt.time(23, 59))
            existed = _q(memory, "SELECT id FROM tasks WHERE uid=?", (it["uid"],))
            if existed:
                _q(memory, "UPDATE tasks SET title=?, course=?, due=?, url=? WHERE uid=?",
                   (title, course, due, it["url"], it["uid"]))
            else:
                _q(memory, "INSERT INTO tasks(uid,title,course,due,est_min,priority,source,url,notes,created) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (it["uid"], title, course, due, _guess_minutes(title, default_min), 2,
                    "canvas", it["url"], it["description"], time.time()))
                new_tasks += 1
        else:
            existed = _q(memory, "SELECT id FROM events WHERE uid=?", (it["uid"],))
            if existed:
                _q(memory, "UPDATE events SET title=?, start=?, end=?, location=?, blocks_time=? WHERE uid=?",
                   (it["title"], it["start"], it["end"], it["location"], it["blocks_time"], it["uid"]))
            else:
                _q(memory, "INSERT INTO events(uid,title,start,end,location,source,notes,blocks_time) "
                           "VALUES (?,?,?,?,?,?,?,?)", (it["uid"], it["title"], it["start"], it["end"],
                           it["location"], "canvas", it["description"], it["blocks_time"]))
                new_events += 1
    extra = _sync_canvas_api(memory, cfg)
    return (f"Canvas synced: {new_tasks} new assignments, {new_events} new calendar items"
            f"{', ' + extra if extra else ''}.{note}")


def _sync_canvas_api(memory, cfg) -> str:
    """Optional: with a Canvas token, mark assignments you've already submitted as done."""
    token = secure.get_secret("canvas_token")
    feed = secure.get_secret("canvas_feed_url")
    if not token or not feed:
        return ""
    base = "https://" + urllib.parse.urlparse(feed).hostname
    start = (dt.date.today() - dt.timedelta(days=21)).isoformat()
    end = (dt.date.today() + dt.timedelta(days=45)).isoformat()
    url = f"{base}/api/v1/planner/items?start_date={start}&end_date={end}&per_page=100"
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}",
                                                   "User-Agent": "JarvisLocalAssistant/1.0"})
        with net.urlopen(req, cfg, timeout=20, purpose="canvas_api") as r:
            items = json.loads(r.read().decode())
    except Exception as e:
        return f"submission check failed ({e})"
    done = 0
    for it in items:
        subs = it.get("submissions") or {}
        if it.get("plannable_type") == "assignment" and (subs.get("submitted") or subs.get("excused")):
            uid = f"event-assignment-{it.get('plannable_id')}"
            rows = _q(memory, "SELECT id FROM tasks WHERE uid=? AND status='open'", (uid,))
            if rows:
                _q(memory, "UPDATE tasks SET status='done' WHERE uid=?", (uid,))
                done += 1
    return f"{done} marked as already submitted"


# ================================================================ weekly planning
BREAK_SECONDS = 5 * 60


def _busy(db, start, end):
    # Feeds sometimes supply only a start time. Reserve 15 minutes for those entries.
    return db.execute(
        "WITH busy AS (SELECT start, CASE WHEN end > start THEN end ELSE start + 900 END AS finish "
        "FROM events WHERE blocks_time=1) "
        "SELECT start, finish FROM busy WHERE start < ? AND finish + ? > ? ORDER BY start",
        (end, BREAK_SECONDS, start),
    ).fetchall()


def _day_slots(cfg, day, busy, now, min_minutes):
    ws, we = map(int, cfg.get("work_hours", [8, 22]))
    end = at(day + dt.timedelta(days=1), dt.time.min) if we == 24 else at(day, dt.time(we))
    cursor = max(at(day, dt.time(ws)), math.ceil((now + 600) / 60) * 60)
    slots = []
    for s, e in busy:
        if s >= end or cursor >= end:
            break
        if s - cursor >= min_minutes * 60:
            slots.append((cursor, s))
        cursor = max(cursor, math.ceil((e + BREAK_SECONDS) / 60) * 60)
    if end - cursor >= min_minutes * 60:
        slots.append((cursor, end))
    return slots


def free_slots(memory, cfg, day: dt.date, extra_busy=(), min_minutes=25):
    midnight = at(day, dt.time.min)
    next_midnight = at(day + dt.timedelta(days=1), dt.time.min)
    with memory._lock:
        busy = _busy(memory.db, midnight, next_midnight)
    return _day_slots(cfg, day, sorted([*busy, *extra_busy]), time.time(), max(1, min_minutes))


def make_week_plan(memory, cfg) -> str:
    now = time.time()
    today = dt.datetime.fromtimestamp(now).date()
    days = [today + dt.timedelta(days=i) for i in range(7)]
    horizon = at(today + dt.timedelta(days=7), dt.time.min)
    block = int(cfg.get("study_block_minutes", 50))
    if block < 1:
        raise ValueError("Study blocks must be at least one minute.")
    cap = max(0, int(cfg.get("max_planned_minutes_per_day", 240)))
    lead_hours = max(0, int(cfg.get("study_lead_hours", 24)))
    slots = deque()
    budget = {}
    schedule = defaultdict(list)
    inserts, shortages, later, inside_buffer = [], [], [], []

    # A retry replaces only future study blocks in this week. Readers see a complete plan.
    with memory._lock, memory.db as db:
        db.execute("DELETE FROM events WHERE source='plan' AND start>? AND start<?", (now, horizon))
        busy = _busy(db, at(today, dt.time.min), horizon)
        booked = dict(db.execute(
            "SELECT e.task_id, ROUND(SUM(e.end-e.start)/60) FROM events e JOIN tasks t ON t.id=e.task_id "
            "WHERE e.source='plan' AND (e.start<=? OR t.due IS NULL OR e.end<=t.due) GROUP BY e.task_id", (now,)
        ))
        for day in days:
            midnight = at(day, dt.time.min)
            next_midnight = at(day + dt.timedelta(days=1), dt.time.min)
            used, = db.execute(
                "SELECT COALESCE(SUM(MIN(end, ?)-MAX(start, ?)), 0) FROM events "
                "WHERE source='plan' AND start<? AND end>?",
                (next_midnight, midnight, next_midnight, midnight),
            ).fetchone()
            budget[day] = cap - round(used / 60)
            slots.extend((day, s, e) for s, e in _day_slots(cfg, day, busy, now, 1))

        tasks = db.execute(
            "SELECT id, title, course, due, est_min FROM tasks WHERE status='open' "
            "AND (due IS NULL OR due>?) ORDER BY due IS NULL, due, priority DESC, id", (now - DAY,)
        )
        for tid, title, course, due, estimate in tasks:
            remaining = (estimate or 60) - int(booked.get(tid, 0))
            deadline = min(due or horizon, horizon)
            label = f"Work on: {title}" + (f" ({course})" if course else "")
            finish = None
            while remaining > 0 and slots:
                day, start, end = slots[0]
                if budget[day] <= 0 or end - start < 60:
                    slots.popleft()
                    continue
                if deadline - start < 60:
                    break  # A later task can still use this gap.
                minutes = min(block, remaining, budget[day], int((min(end, deadline) - start) // 60))
                finish = start + minutes * 60
                inserts.append((f"plan-{tid}-{int(start)}", label, start, finish, tid))
                schedule[day].append(f"{fmt_ts(start, False)} to {fmt_ts(finish, False)}  {label}")
                budget[day] -= minutes
                remaining -= minutes
                slots[0] = (day, finish + BREAK_SECONDS, end)
            if remaining > 0:
                if due is not None and due <= horizon:
                    shortages.append(f"{title} (due {fmt_ts(due)}, {remaining} min short)")
                else:
                    later.append(f"{title} ({remaining} min left)")
            elif finish is not None and due and finish > due - lead_hours * 3600:
                inside_buffer.append(title)
        db.executemany(
            "INSERT INTO events(uid,title,start,end,source,task_id) VALUES (?,?,?,?,'plan',?)", inserts
        )

    count = len(inserts)
    lines = [f"Planned {count} work block{'s' if count != 1 else ''} for the next seven days."]
    if shortages:
        lines.append("Time missing before the deadline: " + ", ".join(shortages))
    if inside_buffer:
        lines.append(f"Scheduled within {lead_hours}h of the deadline: " + ", ".join(inside_buffer))
    if later:
        lines.append("Work beyond this week's capacity: " + ", ".join(later))
    for day, blocks in schedule.items():
        lines.append(day.strftime("%A") + "\n" + "\n".join(blocks))
    return "\n\n".join(lines)


def behind_report(memory) -> dict:
    now = time.time()
    overdue = _q(memory, "SELECT title, due FROM tasks WHERE status='open' AND due<? AND due>? ORDER BY due",
                 (now, now - 14 * DAY))
    soon = _q(memory, "SELECT id, title, due FROM tasks WHERE status='open' AND due>=? AND due<? ORDER BY due",
              (now, now + 2 * DAY))
    unplanned = [(t, d) for i, t, d in soon
                 if not _q(memory, "SELECT 1 FROM events WHERE task_id=? AND start>?", (i, now - 3600))]
    return {"overdue": overdue, "soon": [(t, d) for _, t, d in soon], "unplanned_soon": unplanned}


# ================================================================ skills
def task_command_args(value):
    fields = [part.strip() for part in value.rsplit("|", 2)]
    if not fields[0]:
        raise ValueError("Use /task title | optional due date | optional minutes.")
    args = {"title": fields[0]}
    if len(fields) > 1 and fields[1]:
        date, separator, clock = fields[1].partition("@")
        if not date.strip() or (separator and not clock.strip()):
            raise ValueError("Enter a date such as Friday or a date and time such as Friday @ 5 pm.")
        args["due_date"] = date.strip()
        if clock:
            args["due_time"] = clock.strip()
    if len(fields) == 3 and fields[2]:
        if not fields[2].isascii() or not fields[2].isdigit() or int(fields[2]) < 1:
            raise ValueError("Enter a positive whole number of minutes.")
        args["minutes"] = int(fields[2])
    return args


@skill("Sync assignments and events from Canvas (uses the saved copy when offline).",
       available=canvas_configured)
def sync_canvas(ctx):
    return sync_canvas_now(ctx.memory, ctx.cfg, force=True)


@skill("Add a to-do task or homework with an optional due date.",
       params={"title": ("string", "What needs doing", True),
               "due_date": ("string", "e.g. 'friday', 'tomorrow', '2026-11-20'", False),
               "due_time": ("string", "e.g. '11:59 pm'", False),
               "minutes": ("number", "Estimated minutes of work", False),
               "priority": ("number", "1 low, 2 normal, 3 high", False)})
def add_task(ctx, title, due_date=None, due_time=None, minutes=None, priority=None):
    due = at(parse_date(due_date), parse_time(due_time, dt.time(23, 59))) if due_date else None
    est = int(minutes or _guess_minutes(title, ctx.cfg.get("default_task_minutes", 60)))
    _q(ctx.memory, "INSERT INTO tasks(uid,title,due,est_min,priority,source,created) VALUES (?,?,?,?,?,?,?)",
       (f"manual-{uuid.uuid4().hex}", title, due, est, int(priority or 2), "manual", time.time()))
    return f"Task added: {title}" + (f", due {fmt_ts(due)}" if due else "") + f", about {est} minutes."


@skill("Mark a task or assignment as done.",
       params={"title": ("string", "Words from the task title", True)})
def complete_task(ctx, title):
    rows = _q(ctx.memory, "SELECT id, title FROM tasks WHERE status='open' AND title LIKE ? ORDER BY due",
              (f"%{title}%",))
    if not rows:
        return "No open task matches that."
    tid, name = rows[0]
    _q(ctx.memory, "UPDATE tasks SET status='done' WHERE id=?", (tid,))
    _q(ctx.memory, "DELETE FROM events WHERE task_id=? AND start>?", (tid, time.time()))
    return f"Marked done: {name}." + (f" ({len(rows) - 1} other matches left open.)" if len(rows) > 1 else "")


@skill("List open tasks and assignments, soonest due first.",
       params={"days": ("number", "Only tasks due within this many days (optional)", False)},
       untrusted=True)
def list_tasks(ctx, days=None):
    sql = "SELECT title, course, due, est_min FROM tasks WHERE status='open'"
    args = []
    if days:
        sql += " AND due IS NOT NULL AND due<?"
        args.append(time.time() + float(days) * DAY)
    rows = _q(ctx.memory, sql + " ORDER BY due IS NULL, due LIMIT 25", args)
    if not rows:
        return "No open tasks."
    return "\n".join(f"- {t}{' [' + c + ']' if c else ''}: "
                     f"{('due ' + fmt_ts(d)) if d else 'no due date'}, ~{m} min" for t, c, d, m in rows)


@skill("Add an event or appointment to the calendar.",
       params={"title": ("string", "Event name", True),
               "date": ("string", "e.g. 'tomorrow', 'friday', 'Nov 21'", True),
               "start_time": ("string", "e.g. '3 pm'", True),
               "duration_minutes": ("number", "Length in minutes (default 60)", False),
               "location": ("string", "Where (optional)", False)})
def add_event(ctx, title, date, start_time, duration_minutes=None, location=None):
    start = at(parse_date(date), parse_time(start_time))
    end = start + float(duration_minutes or 60) * 60
    clash = _q(ctx.memory, "SELECT title, start FROM events WHERE source!='plan' AND blocks_time=1 AND end>? AND start<?",
               (start, end))
    _q(ctx.memory, "INSERT INTO events(uid,title,start,end,location,source) VALUES (?,?,?,?,?,?)",
       (f"manual-{time.time()}", title, start, end, location or "", "manual"))
    msg = f"Added {title} on {fmt_ts(start)} until {fmt_ts(end, False)}."
    if clash:
        msg += " Heads up, it overlaps with: " + "; ".join(f"{t} at {fmt_ts(s, False)}" for t, s in clash)
    return msg


@skill("Remove an event from the calendar.",
       params={"title": ("string", "Words from the event name", True),
               "date": ("string", "Which day (optional)", False)})
def remove_event(ctx, title, date=None):
    sql, args = "SELECT id, title, start FROM events WHERE title LIKE ?", [f"%{title}%"]
    if date:
        d = parse_date(date)
        sql += " AND start>=? AND start<?"
        args += [at(d, dt.time(0)), at(d, dt.time(23, 59))]
    else:
        sql += " AND start>?"
        args.append(time.time() - 3600)
    rows = _q(ctx.memory, sql + " ORDER BY start LIMIT 1", args)
    if not rows:
        return "No matching event."
    _q(ctx.memory, "DELETE FROM events WHERE id=?", (rows[0][0],))
    return f"Removed {rows[0][1]} ({fmt_ts(rows[0][2])})."


def _day_events(memory, start, end):
    return _q(memory, "SELECT start, COALESCE(end,start), title, location, source, blocks_time FROM events "
                      "WHERE start<? AND (end>? OR start>=?) ORDER BY start, id", (end, start, start))


def _event_time(start, end, midnight, next_midnight, show_end=False):
    if start <= midnight and end >= next_midnight:
        return "All day"
    if start < midnight:
        return "Until " + fmt_ts(end, False)
    if show_end and end >= next_midnight:
        return "From " + fmt_ts(start, False)
    if show_end and end > start:
        return f"{fmt_ts(start, False)}-{fmt_ts(end, False)}"
    return fmt_ts(start, False)


@skill("Show the schedule for a day or the whole week (events, classes and planned work).",
       params={"when": ("string", "'today', 'tomorrow', a weekday, a date, or 'week'", False)},
       untrusted=True)
def show_schedule(ctx, when="today"):
    if (when or "").lower() in ("week", "this week", "the week"):
        days = [dt.date.today() + dt.timedelta(days=i) for i in range(7)]
    else:
        days = [parse_date(when)]
    out = []
    for d in days:
        midnight = at(d, dt.time.min)
        next_midnight = at(d + dt.timedelta(days=1), dt.time.min)
        rows = _day_events(ctx.memory, midnight, next_midnight)
        due = _q(ctx.memory, "SELECT title, due FROM tasks WHERE status='open' AND due>=? AND due<? ORDER BY due",
                 (midnight, next_midnight))
        items = [f"{_event_time(s, e, midnight, next_midnight, show_end=True)} {title}"
                 + (f" @ {location}" if location else "") + ("" if busy else " (free)")
                 for s, e, title, location, _, busy in rows]
        items += [f"DUE {fmt_ts(dd, False)}: {t}" for t, dd in due]
        out.append(f"{d:%A %b %d}: " + ("; ".join(items) if items else "free"))
    return "\n".join(out)


@skill("Find free time slots on a day.",
       params={"date": ("string", "Which day", False),
               "minutes": ("number", "How long the slot must be", False)})
def find_free_time(ctx, date="today", minutes=None):
    d = parse_date(date)
    slots = free_slots(ctx.memory, ctx.cfg, d, min_minutes=int(minutes or 30))
    if not slots:
        return f"No free slots on {d:%A}."
    return f"Free on {d:%A}: " + ", ".join(f"{fmt_ts(s, False)}-{fmt_ts(e, False)}" for s, e in slots)


@skill("Plan the week: schedule work blocks for every open task and assignment around the "
       "calendar, before each deadline. Call sync_canvas first if Canvas is connected.", untrusted=True)
def plan_week(ctx):
    return make_week_plan(ctx.memory, ctx.cfg)


@skill("Check what is overdue, due soon, or not planned yet, so nothing slips through the cracks.",
       untrusted=True)
def whats_falling_behind(ctx):
    r = behind_report(ctx.memory)
    parts = []
    if r["overdue"]:
        parts.append("Overdue: " + "; ".join(f"{t} (was due {fmt_ts(d)})" for t, d in r["overdue"]))
    if r["soon"]:
        parts.append("Due in the next 48 hours: " + "; ".join(f"{t} ({fmt_ts(d)})" for t, d in r["soon"]))
    if r["unplanned_soon"]:
        parts.append("No time planned yet for: " + "; ".join(t for t, _ in r["unplanned_soon"]))
    return "\n".join(parts) or "Nothing is overdue or at risk. You're on top of things."


@skill("Export the calendar and deadlines to an .ics file you can import into Google or Outlook calendar.")
def export_calendar(ctx):
    rows = _q(ctx.memory, "SELECT uid, title, start, end, location, blocks_time FROM events WHERE end>?",
              (time.time() - 7 * DAY,))
    tasks = _q(ctx.memory, "SELECT uid, title, due FROM tasks WHERE status='open' AND due>?", (time.time(),))
    stamp = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda s: (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Jarvis//EN"]
    for uid, title, s, e, loc, busy in rows:
        lines += ["BEGIN:VEVENT", f"UID:{uid}@jarvis", f"DTSTAMP:{stamp(time.time())}", f"DTSTART:{stamp(s)}",
                  f"DTEND:{stamp(e)}", f"SUMMARY:{esc(title)}", f"LOCATION:{esc(loc)}"]
        if not busy:
            lines.append("TRANSP:TRANSPARENT")
        lines.append("END:VEVENT")
    for uid, title, due in tasks:
        lines += ["BEGIN:VEVENT", f"UID:{uid}-due@jarvis", f"DTSTAMP:{stamp(time.time())}", f"DTSTART:{stamp(due - 900)}",
                  f"DTEND:{stamp(due)}", f"SUMMARY:{esc('DUE: ' + title)}", "END:VEVENT"]
    lines.append("END:VCALENDAR")
    path = Path.home() / "Documents" / "Jarvis Calendar.ics"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(("\r\n".join(lines) + "\r\n").encode("utf-8"))
    return f"Exported {len(rows) + len(tasks)} items to {path}. Open it to add them to your calendar."


def dashboard(memory):
    now = time.time()
    d = dt.date.today()
    midnight = at(d, dt.time.min)
    next_midnight = at(d + dt.timedelta(days=1), dt.time.min)
    today = _day_events(memory, midnight, next_midnight)
    tasks = _q(memory, "SELECT title, course, due FROM tasks WHERE status='open' AND due IS NOT NULL AND due>? "
                       "ORDER BY due LIMIT 8", (now - 14 * DAY,))
    return {
        "today": [{"time": _event_time(s, e, midnight, next_midnight), "title": t if busy else f"{t} (free)",
                   "source": src, "past": e < now} for s, e, t, _, src, busy in today],
        "deadlines": [{"title": t, "course": c, "when": fmt_ts(due),
                       "hours": round((due - now) / 3600, 1)} for t, c, due in tasks],
        "canvas": canvas_configured(),
    }
