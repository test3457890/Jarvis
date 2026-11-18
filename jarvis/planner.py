"""Planner: tasks, calendar, Canvas, and weekly planning so nothing slips.

Canvas works through your private Canvas *calendar feed* link (Canvas > Calendar >
Calendar Feed). No API key needed. Jarvis keeps a copy, so it works offline too.
Optionally, a Canvas access token lets Jarvis also see what you've already submitted.
"""
import datetime as dt
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path

from . import net, secure
from .config import APP_DIR
from .skills import skill

CANVAS_CACHE = APP_DIR / "canvas.ics"
DAY = 86400


# ================================================================ storage
def init_db(memory):
    with memory._lock:
        memory.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY, uid TEXT UNIQUE, title TEXT, course TEXT, due REAL,
                est_min INTEGER, priority INTEGER DEFAULT 2, status TEXT DEFAULT 'open',
                source TEXT, url TEXT, notes TEXT, nudged INTEGER DEFAULT 0, created REAL);
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY, uid TEXT UNIQUE, title TEXT, start REAL, end REAL,
                location TEXT, source TEXT, notes TEXT, task_id INTEGER, nudged INTEGER DEFAULT 0);
            CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
            """
        )
        memory.db.commit()


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
    if "VALUE=DATE" in params.upper() or re.fullmatch(r"\d{8}", v):
        d = dt.datetime.strptime(v[:8], "%Y%m%d")
        return d.replace(hour=23, minute=59).timestamp(), True
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
        except (KeyError, ValueError):
            continue
        end = _ics_time(*e["DTEND"])[0] if "DTEND" in e else start
        out.append({
            "uid": e.get("UID", ("", ""))[0],
            "title": _unescape(e.get("SUMMARY", ("(untitled)", ""))[0]),
            "start": start, "end": end, "all_day": all_day,
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
        return "Canvas isn't connected. Run 'Jarvis.bat setup' and paste your Canvas calendar feed link."
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
            existed = _q(memory, "SELECT id FROM tasks WHERE uid=?", (it["uid"],))
            if existed:
                _q(memory, "UPDATE tasks SET title=?, course=?, due=?, url=? WHERE uid=?",
                   (title, course, it["start"], it["url"], it["uid"]))
            else:
                _q(memory, "INSERT INTO tasks(uid,title,course,due,est_min,priority,source,url,notes,created) "
                           "VALUES (?,?,?,?,?,?,?,?,?,?)",
                   (it["uid"], title, course, it["start"], _guess_minutes(title, default_min), 2,
                    "canvas", it["url"], it["description"], time.time()))
                new_tasks += 1
        else:
            existed = _q(memory, "SELECT id FROM events WHERE uid=?", (it["uid"],))
            if existed:
                _q(memory, "UPDATE events SET title=?, start=?, end=?, location=? WHERE uid=?",
                   (it["title"], it["start"], it["end"], it["location"], it["uid"]))
            else:
                _q(memory, "INSERT INTO events(uid,title,start,end,location,source,notes) VALUES (?,?,?,?,?,?,?)",
                   (it["uid"], it["title"], it["start"], it["end"], it["location"], "canvas", it["description"]))
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
def _busy(memory, start, end):
    rows = _q(memory, "SELECT start, end FROM events WHERE end>? AND start<?", (start, end))
    return sorted((max(s, start), max(e, s + 900)) for s, e in rows)


def free_slots(memory, cfg, day: dt.date, extra_busy=(), min_minutes=25):
    ws, we = cfg.get("work_hours", [8, 22])
    lo = at(day, dt.time(int(ws)))
    hi = at(day, dt.time(min(int(we), 23), 59 if int(we) >= 24 else 0))
    lo = max(lo, time.time() + 600)
    if lo >= hi:
        return []
    busy = _busy(memory, lo, hi) + sorted((s, e) for s, e in extra_busy if e > lo and s < hi)
    busy.sort()
    slots, cursor = [], lo
    for s, e in busy:
        if s - cursor >= min_minutes * 60:
            slots.append((cursor, min(s, hi)))
        cursor = max(cursor, e + 300)  # 5 min breathing room after each thing
    if hi - cursor >= min_minutes * 60:
        slots.append((cursor, hi))
    return slots


def make_week_plan(memory, cfg) -> str:
    now = time.time()
    horizon = now + 7 * DAY
    _q(memory, "DELETE FROM events WHERE source='plan' AND start>?", (now,))
    tasks = _q(memory, "SELECT id, title, course, due, est_min, priority FROM tasks "
                       "WHERE status='open' AND (due IS NULL OR due>?) ORDER BY due IS NULL, due, priority DESC",
               (now - DAY,))
    block = int(cfg.get("study_block_minutes", 50))
    cap = int(cfg.get("max_planned_minutes_per_day", 240)) * 60
    planned, per_day, at_risk, lines = [], {}, [], []
    for tid, title, course, due, est, prio in tasks:
        remaining = (est or 60) * 60
        # Already planned or done earlier counts toward the estimate.
        latest = min((due or horizon) - 2 * 3600, horizon)
        day = dt.date.today()
        while remaining > 0 and at(day, dt.time(0)) < latest:
            for s, e in free_slots(memory, cfg, day, planned):
                if remaining <= 0 or per_day.get(day, 0) >= cap:
                    break
                e = min(e, latest)
                length = min(block * 60, remaining, e - s, cap - per_day.get(day, 0))
                if length < 25 * 60:
                    continue
                planned.append((s, s + length))
                per_day[day] = per_day.get(day, 0) + length
                remaining -= length
                label = f"Work on: {title}" + (f" ({course})" if course else "")
                _q(memory, "INSERT INTO events(uid,title,start,end,source,task_id) VALUES (?,?,?,?,?,?)",
                   (f"plan-{tid}-{int(s)}", label, s, s + length, "plan", tid))
            day += dt.timedelta(days=1)
        if remaining > 0 and due:
            at_risk.append(f"{title} (due {fmt_ts(due)}, about {remaining // 60} minutes short)")
    for i in range(7):
        d = dt.date.today() + dt.timedelta(days=i)
        rows = _q(memory, "SELECT start, title FROM events WHERE source='plan' AND start>=? AND start<? ORDER BY start",
                  (at(d, dt.time(0)), at(d, dt.time(23, 59))))
        if rows:
            lines.append(d.strftime("%A") + ": " + "; ".join(f"{fmt_ts(s, False)} {t}" for s, t in rows))
    summary = f"Planned {len(planned)} work blocks across the week."
    if at_risk:
        summary += " At risk, not enough free time before the deadline: " + "; ".join(at_risk) + "."
    return summary + ("\n" + "\n".join(lines) if lines else " Nothing needed planning.")


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
       (f"manual-{time.time()}", title, due, est, int(priority or 2), "manual", time.time()))
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
    clash = _q(ctx.memory, "SELECT title, start FROM events WHERE source!='plan' AND end>? AND start<?", (start, end))
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
        rows = _q(ctx.memory, "SELECT start, end, title, location FROM events WHERE start>=? AND start<? ORDER BY start",
                  (at(d, dt.time(0)), at(d, dt.time(23, 59, 59))))
        due = _q(ctx.memory, "SELECT title, due FROM tasks WHERE status='open' AND due>=? AND due<? ORDER BY due",
                 (at(d, dt.time(0)), at(d, dt.time(23, 59, 59))))
        items = [f"{fmt_ts(s, False)}-{fmt_ts(e, False)} {t}{' @ ' + l if l else ''}" for s, e, t, l in rows]
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
       "calendar, before each deadline. Call sync_canvas first if Canvas is connected.")
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
    rows = _q(ctx.memory, "SELECT uid, title, start, end, location FROM events WHERE end>?", (time.time() - 7 * DAY,))
    tasks = _q(ctx.memory, "SELECT uid, title, due FROM tasks WHERE status='open' AND due>?", (time.time(),))
    stamp = lambda ts: dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    esc = lambda s: (s or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Jarvis//EN"]
    for uid, title, s, e, loc in rows:
        lines += ["BEGIN:VEVENT", f"UID:{uid}@jarvis", f"DTSTAMP:{stamp(time.time())}", f"DTSTART:{stamp(s)}",
                  f"DTEND:{stamp(e)}", f"SUMMARY:{esc(title)}", f"LOCATION:{esc(loc)}", "END:VEVENT"]
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
    today = _q(memory, "SELECT start, end, title, source FROM events WHERE start>=? AND start<? ORDER BY start",
               (at(d, dt.time(0)), at(d, dt.time(23, 59, 59))))
    tasks = _q(memory, "SELECT title, course, due FROM tasks WHERE status='open' AND due IS NOT NULL AND due>? "
                       "ORDER BY due LIMIT 8", (now - 14 * DAY,))
    return {
        "today": [{"time": f"{fmt_ts(s, False)}", "title": t, "source": src, "past": e < now}
                  for s, e, t, src in today],
        "deadlines": [{"title": t, "course": c, "when": fmt_ts(due),
                       "hours": round((due - now) / 3600, 1)} for t, c, due in tasks],
        "canvas": canvas_configured(),
    }
