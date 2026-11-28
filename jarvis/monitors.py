"""Condition Monitoring Sentinels: local threshold alerts backed by real telemetry.

Evaluates user-configured thresholds against authentic telemetry.snapshot() readings
(CPU %, Memory %, Disk %, GPU %, GPU temp °C, Battery %). Never fabricates sensor data.
"""
import secrets
import time

from . import secure, telemetry

METRICS = {
    "cpu_percent": "CPU utilization (%)",
    "mem_percent": "Memory utilization (%)",
    "disk_percent": "Disk utilization (%)",
    "gpu_percent": "GPU utilization (%)",
    "gpu_temp_c": "GPU temperature (°C)",
    "battery_percent": "Battery level (%)",
}
OPERATORS = (">", ">=", "<", "<=")


def init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS condition_monitors (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                metric TEXT NOT NULL,
                operator TEXT NOT NULL,
                threshold REAL NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_value REAL,
                last_checked REAL,
                last_triggered REAL,
                trigger_count INTEGER NOT NULL DEFAULT 0
            )"""
        )
        mem.db.commit()


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "name": row[1],
        "metric": row[2],
        "metric_label": METRICS.get(row[2], row[2]),
        "operator": row[3],
        "threshold": row[4],
        "enabled": bool(row[5]),
        "last_value": row[6],
        "last_checked": row[7],
        "last_triggered": row[8],
        "trigger_count": row[9],
    }


def list_monitors(mem) -> list[dict]:
    init_db(mem)
    with mem._lock:
        rows = mem.db.execute(
            "SELECT id, name, metric, operator, threshold, enabled, last_value, last_checked, last_triggered, trigger_count FROM condition_monitors ORDER BY name"
        ).fetchall()
    return [_row_to_dict(r) for r in rows]


def create_monitor(mem, *, name: str, metric: str, operator: str, threshold: float) -> dict:
    init_db(mem)
    clean_name = str(name or "").strip()[:80]
    if not clean_name:
        raise ValueError("Monitor name is required.")
    if metric not in METRICS:
        raise ValueError(f"Choose a supported metric: {', '.join(sorted(METRICS))}.")
    if operator not in OPERATORS:
        raise ValueError(f"Choose an operator: {', '.join(OPERATORS)}.")
    try:
        val = float(threshold)
    except (TypeError, ValueError):
        raise ValueError("Threshold must be a number.") from None
    mid = f"mon-{secrets.token_hex(4)}"
    with mem._lock:
        mem.db.execute(
            "INSERT INTO condition_monitors (id, name, metric, operator, threshold, enabled) VALUES (?, ?, ?, ?, ?, 1)",
            (mid, clean_name, metric, operator, val),
        )
        mem.db.commit()
    secure.audit("monitor_created", {"id": mid, "metric": metric, "operator": operator, "threshold": val})
    return next(m for m in list_monitors(mem) if m["id"] == mid)


def set_enabled(mem, monitor_id: str, enabled: bool) -> list[dict]:
    init_db(mem)
    with mem._lock:
        mem.db.execute("UPDATE condition_monitors SET enabled=? WHERE id=?", (1 if enabled else 0, monitor_id))
        mem.db.commit()
    return list_monitors(mem)


def delete_monitor(mem, monitor_id: str) -> list[dict]:
    init_db(mem)
    with mem._lock:
        mem.db.execute("DELETE FROM condition_monitors WHERE id=?", (monitor_id,))
        mem.db.commit()
    return list_monitors(mem)


def _extract_metric(snap: dict, metric: str) -> float | None:
    if metric == "cpu_percent":
        return (snap.get("cpu") or {}).get("percent")
    if metric == "mem_percent":
        return (snap.get("memory") or {}).get("percent")
    if metric == "disk_percent":
        return (snap.get("disk") or {}).get("percent")
    if metric == "battery_percent":
        bat = snap.get("battery")
        return bat.get("percent") if isinstance(bat, dict) else None
    gpus = snap.get("gpus") or []
    if not gpus:
        return None
    if metric == "gpu_percent":
        return gpus[0].get("utilization_percent")
    if metric == "gpu_temp_c":
        return gpus[0].get("temperature_c")
    return None


def _compare(value: float, op: str, threshold: float) -> bool:
    if op == ">":
        return value > threshold
    if op == ">=":
        return value >= threshold
    if op == "<":
        return value < threshold
    if op == "<=":
        return value <= threshold
    return False


def evaluate_all(mem, snap: dict | None = None) -> list[dict]:
    """Evaluate all enabled condition monitors against real telemetry and return triggered alerts."""
    init_db(mem)
    monitors = list_monitors(mem)
    enabled = [m for m in monitors if m["enabled"]]
    if not enabled:
        return []
    reading = snap if snap is not None else telemetry.snapshot(include_processes=False, record_history=False)
    now = time.time()
    alerts = []
    for m in enabled:
        val = _extract_metric(reading, m["metric"])
        if val is None:
            with mem._lock:
                mem.db.execute("UPDATE condition_monitors SET last_checked=? WHERE id=?", (now, m["id"]))
                mem.db.commit()
            continue
        triggered = _compare(float(val), m["operator"], float(m["threshold"]))
        with mem._lock:
            if triggered:
                mem.db.execute(
                    "UPDATE condition_monitors SET last_value=?, last_checked=?, last_triggered=?, trigger_count=trigger_count+1 WHERE id=?",
                    (float(val), now, now, m["id"]),
                )
            else:
                mem.db.execute(
                    "UPDATE condition_monitors SET last_value=?, last_checked=? WHERE id=?",
                    (float(val), now, m["id"]),
                )
            mem.db.commit()
        if triggered:
            msg = f"Monitor '{m['name']}': {m['metric_label']} is {val} ({m['operator']} {m['threshold']})."
            alerts.append({"id": m["id"], "name": m["name"], "metric": m["metric"], "value": val, "message": msg})
            secure.audit("monitor_triggered", {"id": m["id"], "metric": m["metric"], "value": val, "threshold": m["threshold"]})
    return alerts
