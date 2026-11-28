"""Voice Enrollment (Non-Authentication), Custom Wake Words, Multilingual & Standing Instructions.

CRITICAL SECURITY BOUNDARY:
- Voice enrollment is strictly for speaker personalization and noise filtering.
- Voice recognition MUST NEVER be treated as sufficient authentication for sensitive or
  risky actions. `can_authorize_sensitive_action()` unconditionally returns False.
- Raw microphone audio is NEVER written to disk; only numeric feature summaries are stored.
"""
import json
import math
import re
import time

from . import secure

RESPONSE_STYLES = {
    "concise": "Keep replies brief and direct (1-2 sentences unless code or tables are needed).",
    "balanced": "Balance clarity and brevity; give structured details when helpful.",
    "detailed": "Provide thorough explanations, reasoning steps, and examples.",
    "executive": "Lead with the bottom-line recommendation, then key facts and next actions.",
}

SUPPORTED_LANGUAGES = (
    "en-GB", "en-US", "es", "fr", "de", "it", "pt", "hi", "ja", "zh",
)


def can_authorize_sensitive_action(_voice_match_score: float = 1.0) -> bool:
    """Voice recognition is NEVER sufficient authentication for sensitive actions."""
    return False


def validate_wake_words(words: list[str]) -> list[str]:
    if not isinstance(words, list) or not 1 <= len(words) <= 12:
        raise ValueError("Provide between 1 and 12 wake words.")
    clean = []
    for w in words:
        s = re.sub(r"[^A-Za-z0-9 '\-]", "", str(w or "")).strip().lower()
        if not 2 <= len(s) <= 32:
            raise ValueError(f"Invalid wake word '{w}'. Must be 2-32 characters.")
        if s not in clean:
            clean.append(s)
    return clean


def validate_standing_instructions(text: str) -> str:
    clean = secure.redact(str(text or "").strip())
    if len(clean) > 1500:
        raise ValueError("Standing instructions must be 1,500 characters or fewer.")
    if secure.looks_like_injection(clean):
        raise ValueError("Standing instructions cannot contain tool-bypass or pre-approval directives.")
    return clean


def extract_voice_features(samples: list[float]) -> dict:
    """Compute lightweight in-memory numeric summary features without persisting raw audio."""
    if not samples or len(samples) < 16:
        raise ValueError("Need at least 16 audio samples to compute voice features.")
    vals = [float(x) for x in samples[:48000]]
    rms = math.sqrt(sum(v * v for v in vals) / len(vals))
    peak = max(abs(v) for v in vals)
    zcr = sum(1 for i in range(1, len(vals)) if (vals[i - 1] >= 0) != (vals[i] >= 0)) / max(1, len(vals) - 1)
    return {
        "rms": round(rms, 6),
        "peak": round(peak, 6),
        "zero_crossing_rate": round(zcr, 6),
        "sample_count": len(vals),
    }


def _init_db(mem) -> None:
    with mem._lock:
        mem.db.execute(
            """CREATE TABLE IF NOT EXISTS voice_profiles (
                speaker TEXT PRIMARY KEY,
                features_json TEXT NOT NULL,
                samples_enrolled INTEGER NOT NULL,
                updated_at REAL NOT NULL
            )"""
        )
        mem.db.commit()


def enroll_speaker(mem, speaker: str, samples: list[float]) -> dict:
    """Store numeric voice features for personalization (never raw audio, never auth)."""
    _init_db(mem)
    name = re.sub(r"[^\w\- ]", "", str(speaker or "")).strip()[:40]
    if not name:
        raise ValueError("Speaker name is required.")
    feats = extract_voice_features(samples)
    now = time.time()
    with mem._lock:
        mem.db.execute(
            "INSERT OR REPLACE INTO voice_profiles (speaker, features_json, samples_enrolled, updated_at) VALUES (?, ?, 1, ?)",
            (name, json.dumps(feats), now),
        )
        mem.db.commit()
    secure.audit("voice_enrolled_non_auth", {"speaker": name})
    return {"speaker": name, "features": feats, "auth_capable": False, "updated_at": now}


def list_profiles(mem) -> list[dict]:
    _init_db(mem)
    with mem._lock:
        rows = mem.db.execute("SELECT speaker, features_json, samples_enrolled, updated_at FROM voice_profiles ORDER BY speaker").fetchall()
    return [
        {"speaker": r[0], "features": json.loads(r[1]), "samples_enrolled": r[2], "auth_capable": False, "updated_at": r[3]}
        for r in rows
    ]


def prompt_additions(cfg: dict) -> list[str]:
    """Return system-prompt directives for response style, language, and standing instructions."""
    out = []
    style = str(cfg.get("response_style") or "balanced").strip().lower()
    if style in RESPONSE_STYLES:
        out.append(f"Response style ({style}): {RESPONSE_STYLES[style]}")
    lang = str(cfg.get("language") or "en-GB").strip()
    if lang and lang not in ("en", "en-GB", "en-US"):
        out.append(f"Preferred response language: {lang}.")
    standing = str(cfg.get("standing_instructions") or "").strip()
    if standing and not secure.looks_like_injection(standing):
        out.append(f"User standing instructions: {standing}")
    return out
