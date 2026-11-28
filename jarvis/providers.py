"""Unified AI provider catalog, health monitoring, complexity routing, and cost estimation.

Supports all 8+ providers (Ollama, LM Studio, OpenAI, Anthropic, Google Gemini, NVIDIA NIM,
OpenRouter, Groq, plus Custom OpenAI-compatible) while strictly enforcing Jarvis's
local-first privacy modes ('local', 'hybrid', 'cloud'), fail-closed net.py allowlist,
DPAPI secret storage, and zero silent cloud fallback.
"""
from collections import deque
import json
import re
import threading
import time
from urllib.error import URLError
from urllib.request import Request

from . import cloudprovider, net, secure

PRIVACY_MODES = ("local", "hybrid", "cloud")

LOCAL_PROVIDERS = {
    "ollama": {
        "label": "Ollama (Local)",
        "kind": "local",
        "default_url": "http://127.0.0.1:11434",
        "models_path": "/api/tags",
        "requires_key": False,
    },
    "lmstudio": {
        "label": "LM Studio (Local)",
        "kind": "local",
        "default_url": "http://127.0.0.1:1234",
        "models_path": "/v1/models",
        "requires_key": False,
    },
    "openai_local": {
        "label": "Custom Local OpenAI-Compatible",
        "kind": "local",
        "default_url": "http://127.0.0.1:8081",
        "models_path": "/v1/models",
        "requires_key": False,
    },
}

# Reference USD per 1M tokens (input, output). Local models are always $0.00.
# Unknown cloud models return None rather than fabricating a cost.
PRICING_USD_PER_1M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o3-mini": (1.10, 4.40),
    "claude-3-5-haiku-latest": (0.80, 4.00),
    "claude-3-5-sonnet-latest": (3.00, 15.00),
    "claude-sonnet-4-20250514": (3.00, 15.00),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.15, 0.60),
    "gemini-2.5-pro": (1.25, 10.00),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "meta/llama-3.3-70b-instruct": (0.40, 0.40),
    "openai/gpt-4o-mini": (0.15, 0.60),
}

_COMPLEX_RE = re.compile(
    r"\b(architect|architecture|debug|refactor|implement|compare|analyze|analyse|"
    r"security|audit|benchmark|prove|derive|algorithm|optimize|optimise|patch|"
    r"review|diff|research|verify|tradeoff|trade-off|sql|regex|concurrency|async|"
    r"rust|python|typescript|kubernetes|docker|variance|reconcile)\b",
    re.I,
)
_CODE_FENCE_RE = re.compile(r"```|`[^`]{8,}`")


def privacy_mode(cfg: dict) -> str:
    mode = str(cfg.get("privacy_mode") or "local").strip().lower()
    return mode if mode in PRIVACY_MODES else "local"


def cloud_allowed_by_privacy(cfg: dict) -> bool:
    return privacy_mode(cfg) in ("hybrid", "cloud")


def classify_complexity(text: str) -> dict:
    """Classify a user prompt into 'fast' vs 'smart' model tier deterministically."""
    clean = (text or "").strip()
    words = clean.split()
    score = 0.0
    reasons = []

    if len(words) > 22:
        score += 0.35
        reasons.append("long_prompt")
    elif len(words) > 12:
        score += 0.15
        reasons.append("medium_prompt")

    if "\n" in clean:
        score += 0.25
        reasons.append("multi_line")

    if _CODE_FENCE_RE.search(clean):
        score += 0.40
        reasons.append("code_snippet")

    matches = _COMPLEX_RE.findall(clean)
    if matches:
        score += min(0.50, 0.25 * len(set(m.lower() for m in matches)))
        reasons.append("technical_keywords")

    if clean.count("?") >= 2 or " and then " in clean.lower() or " step by step" in clean.lower():
        score += 0.25
        reasons.append("multi_step")

    score = round(min(1.0, score), 2)
    tier = "smart" if score >= 0.35 else "fast"
    return {"tier": tier, "score": score, "reasons": reasons}


def select_local_model(cfg: dict, text: str, assistant: str = "jarvis") -> tuple[str, dict]:
    """Select an appropriate local model based on assistant role, mode, and prompt complexity."""
    complexity = classify_complexity(text)
    mode = cfg.get("mode", "everyday")
    if mode == "coding":
        return cfg.get("coder_model") or cfg.get("model", "qwen3:8b"), complexity
    if assistant == "tuki" or mode in ("research", "cybersecurity") or complexity["tier"] == "smart":
        return cfg.get("model", "qwen3:8b"), complexity
    return cfg.get("everyday_model") or cfg.get("model", "qwen3:8b"), complexity


def estimate_cost(provider: str, model: str, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """Estimate USD cost for a completion. Local providers always return 0.0; unknown cloud models return None."""
    if provider in LOCAL_PROVIDERS:
        return 0.0
    if input_tokens is None and output_tokens is None:
        return None
    key = (model or "").strip().lower()
    rates = PRICING_USD_PER_1M.get(key)
    if rates is None:
        return None
    in_tok = max(0, int(input_tokens or 0))
    out_tok = max(0, int(output_tokens or 0))
    usd = (in_tok / 1_000_000.0) * rates[0] + (out_tok / 1_000_000.0) * rates[1]
    return round(usd, 6)


class UsageTracker:
    """Thread-safe session usage, latency, and estimated cost tracker."""

    def __init__(self, maxlen: int = 200):
        self._lock = threading.Lock()
        self._events: deque[dict] = deque(maxlen=maxlen)

    def record(
        self,
        provider: str,
        model: str,
        *,
        input_tokens: int | None = None,
        output_tokens: int | None = None,
        latency_s: float | None = None,
        tier: str = "",
        fast_path: bool = False,
    ) -> dict:
        cost = estimate_cost(provider, model, input_tokens, output_tokens)
        entry = {
            "ts": round(time.time(), 2),
            "provider": str(provider or "unknown"),
            "model": str(model or "unknown"),
            "input_tokens": int(input_tokens) if isinstance(input_tokens, int) else None,
            "output_tokens": int(output_tokens) if isinstance(output_tokens, int) else None,
            "cost_usd": cost,
            "latency_s": round(float(latency_s), 3) if latency_s is not None else None,
            "tier": tier,
            "fast_path": bool(fast_path),
        }
        with self._lock:
            self._events.append(entry)
        return entry

    def summary(self) -> dict:
        with self._lock:
            events = list(self._events)
        total_in = sum(e["input_tokens"] or 0 for e in events)
        total_out = sum(e["output_tokens"] or 0 for e in events)
        known_costs = [e["cost_usd"] for e in events if e["cost_usd"] is not None]
        total_cost = round(sum(known_costs), 6) if known_costs else 0.0
        by_provider: dict[str, int] = {}
        fast_hits = 0
        for e in events:
            by_provider[e["provider"]] = by_provider.get(e["provider"], 0) + 1
            if e["fast_path"]:
                fast_hits += 1
        return {
            "requests": len(events),
            "fast_path_hits": fast_hits,
            "input_tokens": total_in,
            "output_tokens": total_out,
            "estimated_cost_usd": total_cost,
            "by_provider": by_provider,
            "recent": events[-15:],
        }

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


USAGE = UsageTracker()


def _probe_loopback(url: str, path: str, cfg: dict, timeout: float = 1.5) -> dict:
    """Non-blocking loopback probe for local model discovery (strictly 127.0.0.1)."""
    clean_base = net.local_image_endpoint(url)
    if not clean_base:
        return {"reachable": False, "models": [], "detail": "Not a numeric 127.0.0.1 endpoint"}
    target = clean_base + path
    try:
        req = Request(target, headers={"Accept": "application/json"})
        with net.urlopen(req, cfg, timeout=timeout, purpose="provider_probe", allow_redirects=False, bypass_proxy=True) as resp:
            raw = resp.read(250_000)
        data = json.loads(raw)
        names = []
        if isinstance(data, dict):
            if isinstance(data.get("models"), list):
                names = [str(m.get("name", "")) for m in data["models"][:50] if isinstance(m, dict) and m.get("name")]
            elif isinstance(data.get("data"), list):
                names = [str(m.get("id", "")) for m in data["data"][:50] if isinstance(m, dict) and m.get("id")]
        return {"reachable": True, "models": names, "detail": f"Reachable ({len(names)} model(s))"}
    except (URLError, OSError, ValueError, net.NetworkBlockedError) as exc:
        return {"reachable": False, "models": [], "detail": str(exc)[:120]}


def health_summary(cfg: dict, *, probe_local: bool = False) -> dict:
    """Return unified status for all local and cloud providers without exposing secrets."""
    pmode = privacy_mode(cfg)
    active_local = cfg.get("chat_provider", "ollama")
    rows = []

    ollama_url = cfg.get("ollama_url", "http://127.0.0.1:11434")
    lmstudio_url = cfg.get("lmstudio_url", "http://127.0.0.1:1234")
    local_chat_url = cfg.get("local_chat_url", "http://127.0.0.1:8081")

    local_urls = {
        "ollama": ollama_url,
        "lmstudio": lmstudio_url,
        "openai_local": local_chat_url,
    }
    for pid, spec in LOCAL_PROVIDERS.items():
        url = local_urls[pid]
        probe = _probe_loopback(url, spec["models_path"], cfg) if probe_local else None
        rows.append({
            "id": pid,
            "name": spec["label"],
            "kind": "local",
            "endpoint": url,
            "active": active_local == pid,
            "configured": bool(net.local_image_endpoint(url)),
            "state": (
                probe["detail"] if probe is not None
                else ("Active local provider" if active_local == pid else "Available (local)")
            ),
            "reachable": probe["reachable"] if probe is not None else None,
            "models": probe["models"] if probe is not None else [],
        })

    for row in cloudprovider.status(cfg):
        blocked_by_privacy = pmode == "local"
        state = "Blocked by Local-Only privacy mode" if blocked_by_privacy else row["state"]
        rows.append({
            "id": row["id"],
            "name": row["name"],
            "kind": "cloud",
            "endpoint": f"https://{row['host']}",
            "active": row["active"] and not blocked_by_privacy,
            "configured": row["configured"],
            "state": state,
            "reachable": None,
            "models": [row["default_model"]] if row.get("default_model") else [],
        })

    return {
        "privacy_mode": pmode,
        "internet_enabled": bool(cfg.get("allow_internet_tools")),
        "cloud_opt_in": bool(cfg.get("allow_cloud_provider")),
        "lockdown": bool(cfg.get("lockdown")),
        "active_local_provider": active_local,
        "active_cloud_provider": cfg.get("cloud_provider") or "",
        "providers": rows,
        "usage": USAGE.summary(),
    }


_NON_CHAT_RE = re.compile(r"(embed|embedding|whisper|tts|dall-e|imagen|moderation|rerank|bge-|nomic-embed)", re.I)
_VISION_RE = re.compile(r"(vision|vl|4o|gemini-2|claude-3|claude-sonnet-4|gemma3|llava|pixtral)", re.I)
_REASONING_RE = re.compile(r"(o1|o3|o4|deepseek-r1|qwen3|qwq|thinking)", re.I)


def model_capabilities(model_id: str) -> dict:
    """Infer deterministic chat/tool/vision/reasoning capabilities for a discovered model ID."""
    mid = str(model_id or "").strip()
    is_non_chat = bool(_NON_CHAT_RE.search(mid))
    return {
        "model": mid,
        "chat_capable": bool(mid) and not is_non_chat,
        "supports_vision": bool(_VISION_RE.search(mid)) and not is_non_chat,
        "supports_reasoning": bool(_REASONING_RE.search(mid)) and not is_non_chat,
        "supports_tools": bool(mid) and not is_non_chat,
    }


def select_healthy_local_provider(cfg: dict) -> dict:
    """Controlled local-only failover across Ollama, LM Studio, and local OpenAI-compat.

    NEVER falls back silently to any cloud provider.
    """
    preferred = cfg.get("chat_provider", "ollama")
    order = [preferred] + [p for p in ("ollama", "lmstudio", "openai_local") if p != preferred]
    urls = {
        "ollama": cfg.get("ollama_url", "http://127.0.0.1:11434"),
        "lmstudio": cfg.get("lmstudio_url", "http://127.0.0.1:1234"),
        "openai_local": cfg.get("local_chat_url", "http://127.0.0.1:8081"),
    }
    checked = []
    for pid in order:
        if pid not in LOCAL_PROVIDERS:
            continue
        probe = _probe_loopback(urls[pid], LOCAL_PROVIDERS[pid]["models_path"], cfg)
        chat_models = [m for m in probe["models"] if model_capabilities(m)["chat_capable"]]
        checked.append({"id": pid, "reachable": probe["reachable"], "chat_models": chat_models})
        if probe["reachable"]:
            return {
                "ok": True,
                "selected": pid,
                "failover_used": pid != preferred,
                "endpoint": urls[pid],
                "chat_models": chat_models,
                "checked": checked,
                "cloud_fallback": False,
            }
    return {
        "ok": False,
        "selected": None,
        "failover_used": False,
        "chat_models": [],
        "checked": checked,
        "cloud_fallback": False,
    }
