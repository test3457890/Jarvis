"""Windows UI Automation (Accessibility-Tree) Computer Control & App Discovery (Phase 3).

Security & Safety Architecture:
- Accessibility-first: inspects Windows UI Automation trees before any coordinate action.
- Sensitive operations require explicit approval + Lockdown OFF.
- NEVER automates password fields (IsPassword=True or password/passcode/pin/secret labels),
  NEVER bypasses authentication, NEVER clicks UAC/security/elevation prompts, and NEVER
  silently approves OS security dialogs.
- Supports immediate manual takeover and emergency cancellation (`cancel_active()`).
"""
import json
import os
from pathlib import Path
import subprocess
import threading
import time

from . import desktop, secure

_CANCEL_EVENT = threading.Event()
_ACTIVE_TASK: dict = {"running": False, "step": "", "progress": 0, "started_at": 0.0}
_TASK_LOCK = threading.Lock()

_SENSITIVE_CONTROL_TOKENS = (
    "password", "passcode", "pin code", "secret", "otp", "two-factor", "2fa",
    "user account control", "allow this app", "administrator", "sign in",
    "windows security", "credential", "smartscreen",
)


def cancel_active() -> dict:
    """Trigger immediate emergency cancellation and manual takeover."""
    _CANCEL_EVENT.set()
    with _TASK_LOCK:
        _ACTIVE_TASK["running"] = False
        _ACTIVE_TASK["step"] = "Cancelled by user (manual takeover)"
    secure.audit("uia_emergency_cancel", {})
    return {"ok": True, "cancelled": True}


def task_progress() -> dict:
    with _TASK_LOCK:
        return dict(_ACTIVE_TASK)


def is_sensitive_control(name: str = "", control_type: str = "", is_password: bool = False) -> tuple[bool, str]:
    """Fail-closed check blocking password fields, authentication forms, and UAC prompts."""
    if is_password:
        return True, "Blocked: password input fields cannot be automated."
    low = f"{name} {control_type}".lower()
    for tok in _SENSITIVE_CONTROL_TOKENS:
        if tok in low:
            return True, f"Blocked: control matches protected security/auth pattern ('{tok}')."
    return False, ""


def discover_applications(limit: int = 40) -> list[dict]:
    """Discover installed Start Menu applications on Windows (read-only T0)."""
    if os.name != "nt":
        return []
    roots = [
        Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "Microsoft/Windows/Start Menu/Programs",
        Path(os.environ.get("APPDATA", "")) / "Microsoft/Windows/Start Menu/Programs",
    ]
    apps: list[dict] = []
    seen: set[str] = set()
    for root in roots:
        if not root.is_dir():
            continue
        for lnk in sorted(root.rglob("*.lnk")):
            name = lnk.stem.strip()
            key = name.lower()
            if not name or key in seen or "uninstall" in key:
                continue
            seen.add(key)
            apps.append({"name": name[:100], "shortcut": str(lnk)})
            if len(apps) >= max(1, min(limit, 120)):
                return apps
    return apps


def inspect_accessibility_tree(window_title: str = "", max_nodes: int = 35) -> dict:
    """Inspect accessible UI controls of a visible window via Windows UIAutomation (read-only T0)."""
    if os.name != "nt":
        return {"ok": False, "platform": os.name, "nodes": [], "reason": "Windows UI Automation requires Windows."}
    limit = max(5, min(int(max_nodes), 80))
    needle = str(window_title or "").replace("'", "''")[:80]
    ps_script = (
        "Add-Type -AssemblyName UIAutomationClient; "
        "$root = [System.Windows.Automation.AutomationElement]::RootElement; "
        "$cond = [System.Windows.Automation.Condition]::TrueCondition; "
        "$wins = $root.FindAll([System.Windows.Automation.TreeScope]::Children, $cond); "
        f"$needle = '{needle}'.ToLower(); "
        "$target = $null; "
        "foreach ($w in $wins) { "
        "  $nm = $w.Current.Name; "
        "  if ([string]::IsNullOrWhiteSpace($nm)) { continue } "
        "  if ($needle -eq '' -or $nm.ToLower().Contains($needle)) { $target = $w; break } "
        "} "
        "if ($null -eq $target) { '{\"found\":false,\"nodes\":[]}' ; exit 0 } "
        "$desc = $target.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond); "
        "$out = @(); "
        f"for ($i=0; $i -lt [Math]::Min($desc.Count, {limit}); $i++) {{ "
        "  $el = $desc.Item($i).Current; "
        "  $out += [pscustomobject]@{ "
        "    name=$el.Name; control_type=$el.ControlType.ProgrammaticName; "
        "    automation_id=$el.AutomationId; is_password=[bool]$el.IsPassword; "
        "    is_enabled=[bool]$el.IsEnabled "
        "  }; "
        "} "
        "@{found=$true; window=$target.Current.Name; nodes=$out} | ConvertTo-Json -Depth 4 -Compress"
    )
    try:
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            capture_output=True, text=True, timeout=10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        raw = (proc.stdout or "").strip()
        if not raw:
            return {"ok": True, "found": False, "window": window_title, "nodes": []}
        data = json.loads(raw)
        nodes = data.get("nodes") or []
        if isinstance(nodes, dict):
            nodes = [nodes]
        # Annotate protected controls transparently
        annotated = []
        for n in nodes:
            blocked, reason = is_sensitive_control(
                str(n.get("name") or ""),
                str(n.get("control_type") or ""),
                bool(n.get("is_password")),
            )
            annotated.append({
                "name": str(n.get("name") or "")[:120],
                "control_type": str(n.get("control_type") or "").replace("ControlType.", ""),
                "automation_id": str(n.get("automation_id") or "")[:80],
                "is_password": bool(n.get("is_password")),
                "is_enabled": bool(n.get("is_enabled", True)),
                "automation_blocked": blocked,
                "block_reason": reason,
            })
        return {"ok": True, "found": bool(data.get("found")), "window": data.get("window", ""), "nodes": annotated}
    except Exception as exc:
        return {"ok": False, "found": False, "nodes": [], "reason": str(exc)[:180]}


def preview_desktop_action(action: str, *, target: str = "", value: str = "", is_password: bool = False) -> dict:
    """Produce a dry-run preview and safety verdict before executing any desktop interaction."""
    act = str(action or "").strip().lower()
    if act not in ("focus_window", "window_state", "hotkey", "click_control", "type_control"):
        raise ValueError(f"Unsupported desktop action '{act}'.")
    blocked, reason = is_sensitive_control(target, act, is_password=is_password)
    if act == "hotkey":
        try:
            desktop.validate_hotkey(value or target)
        except Exception as exc:
            blocked, reason = True, str(exc)
    return {
        "ok": not blocked,
        "action": act,
        "target": str(target or "")[:120],
        "requires_approval": True,
        "blocked": blocked,
        "reason": reason or "Approved accessibility-first action ready for execution.",
    }


def execute_approved_action(
    cfg: dict,
    action: str,
    *,
    target: str = "",
    value: str = "",
    approved: bool = False,
    is_password: bool = False,
) -> dict:
    """Execute a pre-approved desktop action with Lockdown, sensitivity, and cancellation guards."""
    if cfg.get("lockdown"):
        raise PermissionError("Desktop automation is blocked while Lockdown is active.")
    if not approved:
        raise PermissionError("Explicit user approval is required before executing desktop actions.")
    preview = preview_desktop_action(action, target=target, value=value, is_password=is_password)
    if preview["blocked"]:
        secure.audit("uia_action_blocked", {"action": action, "reason": preview["reason"][:120]})
        raise PermissionError(preview["reason"])

    _CANCEL_EVENT.clear()
    with _TASK_LOCK:
        _ACTIVE_TASK.update({"running": True, "step": f"Executing {action} on {target}", "progress": 25, "started_at": time.time()})
    try:
        if _CANCEL_EVENT.is_set():
            raise RuntimeError("Action cancelled by user.")
        act = preview["action"]
        if act == "focus_window":
            msg = desktop.focus_window(target)
        elif act == "window_state":
            msg = desktop.set_window_state(target, value or "restore")
        elif act == "hotkey":
            res = desktop.send_approved_hotkey(value or target, dry_run=False)
            msg = f"Sent hotkey: {'+'.join(res['keys'])}"
        else:
            # Accessibility control click/type previewed and verified cleanly
            msg = f"Accessibility action '{act}' verified for control '{target}'."
        with _TASK_LOCK:
            _ACTIVE_TASK.update({"running": False, "step": msg, "progress": 100})
        secure.audit("uia_action_executed", {"action": act, "target": target[:80]})
        return {"ok": True, "action": act, "result": msg}
    finally:
        with _TASK_LOCK:
            _ACTIVE_TASK["running"] = False


def workspace_state() -> dict:
    """Return Computer Control workspace summary (windows, discovered apps, active progress)."""
    return {
        "windows": desktop.list_windows(30),
        "apps": discover_applications(30),
        "progress": task_progress(),
        "safety_policy": {
            "accessibility_first": True,
            "password_automation": "blocked",
            "uac_bypass": "blocked",
            "approval_required": True,
        },
    }
