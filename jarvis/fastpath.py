"""Policy-enforced, audited fast-path commands that do not require an LLM round-trip.

Unlike naive fast-paths that call handlers directly, every matched command here executes
strictly through `skills.run(ctx, tool_name, args)` so Lockdown, per-skill permissions,
confirmation previews, and audit logging are ALWAYS enforced.
"""
import re

from . import providers, secure, skills

_TIME_RE = re.compile(
    r"^(?:what(?:'s| is) the (?:current )?(?:time|date|day|time and date)|what (?:time|day|date) is it|current (?:time|date))\??$",
    re.I,
)
_STATUS_RE = re.compile(r"^(?:system status|show system status|vitals|system vitals|cpu usage|ram usage|gpu status)\??$", re.I)
_REMINDERS_RE = re.compile(r"^(?:list |show |my )?reminders\??$", re.I)
_LOCK_RE = re.compile(r"^lock (?:my )?(?:pc|computer|screen|workstation)$", re.I)
_MEDIA_MAP = {
    "pause music": "play_pause",
    "resume music": "play_pause",
    "play pause": "play_pause",
    "next track": "next",
    "skip track": "next",
    "previous track": "previous",
    "mute audio": "mute",
    "unmute audio": "mute",
    "volume up": "volume_up",
    "volume down": "volume_down",
}
_CALC_RE = re.compile(r"^(?:calculate|calc|what is)\s+([0-9\s\.\+\-\*\/\(\)\%\^]+)\??$", re.I)


def match(text: str) -> tuple[str, dict] | None:
    """Return (skill_name, args) for a safe deterministic fast-path command, or None."""
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if not clean or len(clean) > 120:
        return None
    lower = clean.lower().rstrip(".!")
    if _TIME_RE.match(lower):
        return "get_time_date", {}
    if _STATUS_RE.match(lower):
        return "system_status", {}
    if _REMINDERS_RE.match(lower):
        return "list_reminders", {}
    if _LOCK_RE.match(lower):
        return "lock_pc", {}
    if lower in _MEDIA_MAP:
        return "media_control", {"action": _MEDIA_MAP[lower]}
    m = _CALC_RE.match(clean)
    if m:
        expr = m.group(1).strip().replace("^", "**")
        if any(ch.isdigit() for ch in expr):
            return "calculate", {"expression": expr}
    return None


def try_execute(ctx: skills.Context, text: str) -> tuple[bool, str, str | None]:
    """Attempt fast-path execution through skills.run().

    Returns (handled, reply_text, tool_name).
    Never bypasses Lockdown, skill_permissions, confirmations, or audit logs.
    """
    if not ctx.cfg.get("fast_path_enabled", True):
        return False, "", None
    if ctx.cfg.get("mode") == "talk" or ctx.pending is not None:
        return False, "", None
    matched = match(text)
    if matched is None:
        return False, "", None
    tool_name, args = matched
    if tool_name not in skills.SKILLS:
        return False, "", None
    result = skills.run(ctx, tool_name, args)
    secure.audit("fast_path", {"skill": tool_name, "pending": bool(ctx.pending)})
    providers.USAGE.record("fast_path", tool_name, input_tokens=0, output_tokens=0, latency_s=0.0, tier="fast", fast_path=True)
    if ctx.pending:
        return True, f"Please confirm: {ctx.pending['preview']}. Say yes or no.", tool_name
    return True, result, tool_name
