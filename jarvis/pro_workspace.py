"""Professional, Research & Private Finance Workspace (Phase 7).

Provides:
- CSV spreadsheet reconciliation & variance reports (stdlib csv, bounded size)
- Document revision comparison (unified diff + change counts)
- Requirements & UAT evidence tracker (SQLite)
- Case management (SQLite, redacted)
- Private local financial/budget summary strictly gated by domains.check_domain_access('finance')
"""
import csv
import difflib
import io
import json
import secrets
import time

from . import domains, secure

MAX_TEXT_BYTES = 500_000


def init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS uat_items (
                id TEXT PRIMARY KEY,
                req_id TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                evidence TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            )"""
        )
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                status TEXT NOT NULL DEFAULT 'open',
                notes_json TEXT NOT NULL DEFAULT '[]',
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


# ------------------------------------------------------------------ CSV Variance
def compare_csv_tables(csv_baseline: str, csv_actual: str, *, key_col: str, value_col: str) -> dict:
    """Reconcile two CSV tables by key_col and compute numeric variances on value_col."""
    if len(csv_baseline or "") > MAX_TEXT_BYTES or len(csv_actual or "") > MAX_TEXT_BYTES:
        raise ValueError("CSV input exceeds the 500 KB safety limit.")

    def _parse(raw: str) -> dict[str, float]:
        reader = csv.DictReader(io.StringIO((raw or "").strip()))
        if not reader.fieldnames or key_col not in reader.fieldnames or value_col not in reader.fieldnames:
            raise ValueError(f"CSV must include '{key_col}' and '{value_col}' columns.")
        out: dict[str, float] = {}
        for row in reader:
            k = str(row.get(key_col) or "").strip()
            if not k:
                continue
            try:
                v = float(str(row.get(value_col) or "0").replace(",", "").replace("$", "").strip())
            except ValueError:
                raise ValueError(f"Non-numeric value for key '{k}' in column '{value_col}'.") from None
            out[k] = round(out.get(k, 0.0) + v, 4)
        return out

    base = _parse(csv_baseline)
    act = _parse(csv_actual)
    all_keys = sorted(set(base) | set(act))
    variances = []
    added, removed = [], []
    for k in all_keys:
        if k not in base:
            added.append({"key": k, "actual": act[k]})
            variances.append({"key": k, "baseline": 0.0, "actual": act[k], "delta": round(act[k], 4), "status": "added"})
        elif k not in act:
            removed.append({"key": k, "baseline": base[k]})
            variances.append({"key": k, "baseline": base[k], "actual": 0.0, "delta": round(-base[k], 4), "status": "removed"})
        else:
            delta = round(act[k] - base[k], 4)
            pct = round((delta / base[k]) * 100.0, 2) if base[k] != 0 else None
            variances.append({
                "key": k, "baseline": base[k], "actual": act[k], "delta": delta,
                "pct_change": pct, "status": "changed" if delta != 0 else "matched",
            })

    total_base = round(sum(base.values()), 4)
    total_act = round(sum(act.values()), 4)
    total_delta = round(total_act - total_base, 4)

    md_lines = [
        f"# Variance Report ({key_col} / {value_col})",
        f"- Baseline Total: {total_base}",
        f"- Actual Total: {total_act}",
        f"- Net Variance: {total_delta:+}",
        "",
        "| Key | Baseline | Actual | Delta | Status |",
        "|---|---:|---:|---:|---|",
    ]
    for v in variances:
        md_lines.append(f"| {v['key']} | {v['baseline']} | {v['actual']} | {v['delta']:+} | {v['status']} |")

    return {
        "total_baseline": total_base,
        "total_actual": total_act,
        "total_delta": total_delta,
        "added_count": len(added),
        "removed_count": len(removed),
        "variances": variances,
        "markdown_report": "\n".join(md_lines),
    }


# ------------------------------------------------------------------ Document Revision Diff
def compare_revisions(text_a: str, text_b: str, *, label_a: str = "Revision A", label_b: str = "Revision B") -> dict:
    if len(text_a or "") > MAX_TEXT_BYTES or len(text_b or "") > MAX_TEXT_BYTES:
        raise ValueError("Document exceeds the 500 KB comparison limit.")
    lines_a = (text_a or "").splitlines()
    lines_b = (text_b or "").splitlines()
    diff_lines = list(difflib.unified_diff(lines_a, lines_b, fromfile=label_a[:60], tofile=label_b[:60], lineterm=""))
    added = sum(1 for ln in diff_lines if ln.startswith("+") and not ln.startswith("+++"))
    removed = sum(1 for ln in diff_lines if ln.startswith("-") and not ln.startswith("---"))
    return {
        "label_a": label_a[:60],
        "label_b": label_b[:60],
        "lines_added": added,
        "lines_removed": removed,
        "changed": bool(added or removed),
        "unified_diff": "\n".join(diff_lines)[:50_000],
    }


# ------------------------------------------------------------------ Requirements & UAT Evidence
UAT_STATUSES = ("pending", "passed", "failed", "blocked")


def uat_add(mem, *, req_id: str, title: str, status: str = "pending", evidence: str = "") -> dict:
    init_db(mem)
    rid = str(req_id or "").strip()[:40]
    ttl = str(title or "").strip()[:160]
    st = str(status or "pending").strip().lower()
    if not rid or not ttl:
        raise ValueError("Requirement ID and title are required.")
    if st not in UAT_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(UAT_STATUSES)}.")
    uid = f"uat-{secrets.token_hex(4)}"
    now = time.time()
    ev = secure.redact(str(evidence or "").strip())[:1000]
    with mem._lock:
        mem.db.execute(
            "INSERT INTO uat_items (id, req_id, title, status, evidence, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (uid, rid, ttl, st, ev, now),
        )
        mem.db.commit()
    return {"id": uid, "req_id": rid, "title": ttl, "status": st, "evidence": ev, "updated_at": now}


def uat_list(mem) -> list[dict]:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, req_id, title, status, evidence, updated_at FROM uat_items ORDER BY updated_at DESC"
        ).fetchall()
    return [{"id": r[0], "req_id": r[1], "title": r[2], "status": r[3], "evidence": r[4], "updated_at": r[5]} for r in rows]


def uat_update(mem, uat_id: str, *, status: str, evidence: str = "") -> list[dict]:
    init_db(mem)
    st = str(status or "").strip().lower()
    if st not in UAT_STATUSES:
        raise ValueError(f"Status must be one of: {', '.join(UAT_STATUSES)}.")
    ev = secure.redact(str(evidence or "").strip())[:1000]
    with mem._lock:
        mem.db.execute("UPDATE uat_items SET status=?, evidence=?, updated_at=? WHERE id=?", (st, ev, time.time(), uat_id))
        mem.db.commit()
    return uat_list(mem)


# ------------------------------------------------------------------ Case Management
def case_create(mem, *, title: str, category: str = "general", note: str = "") -> dict:
    init_db(mem)
    ttl = str(title or "").strip()[:140]
    if not ttl:
        raise ValueError("Case title is required.")
    cid = f"case-{secrets.token_hex(4)}"
    now = time.time()
    notes = [{"ts": round(now, 2), "text": secure.redact(note.strip())[:1000]}] if note and note.strip() else []
    with mem._lock:
        mem.db.execute(
            "INSERT INTO cases (id, title, category, status, notes_json, created_at, updated_at) VALUES (?, ?, ?, 'open', ?, ?, ?)",
            (cid, ttl, str(category or "general")[:40], json.dumps(notes), now, now),
        )
        mem.db.commit()
    return {"id": cid, "title": ttl, "category": str(category or "general")[:40], "status": "open", "notes": notes, "created_at": now, "updated_at": now}


def case_list(mem) -> list[dict]:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, title, category, status, notes_json, created_at, updated_at FROM cases ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {"id": r[0], "title": r[1], "category": r[2], "status": r[3], "notes": json.loads(r[4]), "created_at": r[5], "updated_at": r[6]}
        for r in rows
    ]


# ------------------------------------------------------------------ Private Local Finance Summary
def finance_budget_summary(cfg: dict, transactions: list[dict]) -> dict:
    """Summarize user-provided local budget/portfolio transactions strictly behind domains.check_domain_access('finance')."""
    domains.check_domain_access(cfg, "finance", write=False)
    if not isinstance(transactions, list) or len(transactions) > 10_000:
        raise ValueError("Provide a list of up to 10,000 transaction records.")
    income = 0.0
    expenses = 0.0
    by_category: dict[str, float] = {}
    for row in transactions:
        if not isinstance(row, dict):
            continue
        cat = str(row.get("category") or "Uncategorized").strip()[:40]
        amt = float(row.get("amount") or 0.0)
        if amt >= 0:
            income += amt
        else:
            expenses += abs(amt)
        by_category[cat] = round(by_category.get(cat, 0.0) + amt, 2)
    secure.audit("finance_local_summary", {"rows": len(transactions)})
    return {
        "transactions": len(transactions),
        "total_income": round(income, 2),
        "total_expenses": round(expenses, 2),
        "net_cashflow": round(income - expenses, 2),
        "by_category": by_category,
    }
