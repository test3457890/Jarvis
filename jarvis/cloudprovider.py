"""Optional, explicitly consented cloud AI provider adapter (M03).

Rules:
- Disabled by default. Never used as a silent fallback when Ollama or a local server fails.
- Requires Internet ON, Lockdown OFF, an explicitly configured provider + model, and an API
  key stored in Windows DPAPI (never in config.json).
- Every request requires explicit per-request user confirmation showing the exact destination
  host, model name, and payload size before anything leaves this computer.
- Local document excerpts and room transcripts are excluded by default unless the user
  explicitly includes them in the confirmed prompt.
"""
import json
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request

from . import net, secure
from .skills import skill

MAX_BYTES = 1_000_000
MAX_PROMPT_CHARS = 8000

PROVIDERS = {
    "openai": {
        "label": "OpenAI API",
        "host": "api.openai.com",
        "endpoint": "https://api.openai.com/v1/chat/completions",
        "secret_key": "cloud_openai_key",
        "default_model": "gpt-4o-mini",
    },
    "anthropic": {
        "label": "Anthropic API",
        "host": "api.anthropic.com",
        "endpoint": "https://api.anthropic.com/v1/messages",
        "secret_key": "cloud_anthropic_key",
        "default_model": "claude-3-5-haiku-latest",
    },
    "gemini": {
        "label": "Google Gemini API",
        "host": "generativelanguage.googleapis.com",
        "endpoint": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "secret_key": "cloud_gemini_key",
        "default_model": "gemini-2.0-flash",
    },
    "nvidia": {
        "label": "NVIDIA NIM API",
        "host": "integrate.api.nvidia.com",
        "endpoint": "https://integrate.api.nvidia.com/v1/chat/completions",
        "secret_key": "cloud_nvidia_key",
        "default_model": "meta/llama-3.3-70b-instruct",
    },
    "openrouter": {
        "label": "OpenRouter API",
        "host": "openrouter.ai",
        "endpoint": "https://openrouter.ai/api/v1/chat/completions",
        "secret_key": "cloud_openrouter_key",
        "default_model": "openai/gpt-4o-mini",
    },
    "groq": {
        "label": "Groq API",
        "host": "api.groq.com",
        "endpoint": "https://api.groq.com/openai/v1/chat/completions",
        "secret_key": "cloud_groq_key",
        "default_model": "llama-3.3-70b-versatile",
    },
}


def configured_provider(cfg: dict) -> tuple[str, dict] | None:
    name = str(cfg.get("cloud_provider") or "").strip().lower()
    if name == "custom_openai":
        raw_url = str(cfg.get("custom_cloud_url") or "").strip()
        ep = net._parse_endpoint(raw_url)
        if not ep or ep[0] != "https" or not secure.has_secret("cloud_custom_openai_key"):
            return None
        return name, {
            "label": "Custom OpenAI-Compatible API",
            "host": ep[1],
            "endpoint": raw_url,
            "secret_key": "cloud_custom_openai_key",
            "default_model": str(cfg.get("cloud_model") or "custom-model"),
        }
    if name not in PROVIDERS:
        return None
    spec = PROVIDERS[name]
    if not secure.has_secret(spec["secret_key"]):
        return None
    return name, spec


def ready(cfg: dict) -> bool:
    privacy = str(cfg.get("privacy_mode") or "hybrid").strip().lower()
    if privacy == "local" and "privacy_mode" in cfg:
        return False
    return bool(
        cfg.get("allow_internet_tools")
        and cfg.get("allow_cloud_provider")
        and not cfg.get("lockdown")
        and configured_provider(cfg) is not None
    )


def status(cfg: dict) -> list:
    internet = bool(cfg.get("allow_internet_tools"))
    enabled = bool(cfg.get("allow_cloud_provider"))
    rows = []
    for key, spec in PROVIDERS.items():
        has_key = secure.has_secret(spec["secret_key"])
        state = ("Ready (per-request approval)" if internet and enabled else "Paused") if has_key else "Needs API key"
        rows.append({
            "id": key,
            "name": spec["label"],
            "host": spec["host"],
            "state": state,
            "configured": has_key,
            "active": cfg.get("cloud_provider") == key,
            "default_model": spec["default_model"],
        })
    return rows


def preview_request(cfg: dict, prompt: str) -> str:
    found = configured_provider(cfg)
    if not found:
        raise ValueError("Configure a cloud provider and API key in Setup first.")
    name, spec = found
    model = str(cfg.get("cloud_model") or spec["default_model"]).strip()[:120]
    clean = str(prompt or "").strip()
    if not clean or len(clean) > MAX_PROMPT_CHARS:
        raise ValueError(f"Cloud prompt must be 1 to {MAX_PROMPT_CHARS} characters.")
    snippet = clean[:240] + ("..." if len(clean) > 240 else "")
    return (
        f"send this single prompt ({len(clean)} chars) to {spec['label']} ({spec['host']}) "
        f"using model '{model}'. No conversation history or local files are attached. "
        f"Prompt: \"{snippet}\""
    )


def ask(cfg: dict, prompt: str, timeout: int = 60) -> dict:
    """Execute one explicitly approved cloud chat completion. Never called without confirmation."""
    if not cfg.get("allow_internet_tools") or not cfg.get("allow_cloud_provider") or cfg.get("lockdown"):
        raise ValueError("Cloud provider requires Internet on, cloud opt-in enabled, and Lockdown off.")
    if str(cfg.get("privacy_mode") or "hybrid").strip().lower() == "local" and "privacy_mode" in cfg:
        raise ValueError("Cloud provider is blocked while privacy_mode is set to 'local'.")
    found = configured_provider(cfg)
    if not found:
        raise ValueError("Cloud provider is not configured.")
    name, spec = found
    model = str(cfg.get("cloud_model") or spec["default_model"]).strip()[:120]
    api_key = secure.get_secret(spec["secret_key"])
    clean = str(prompt or "").strip()
    if not clean or len(clean) > MAX_PROMPT_CHARS:
        raise ValueError(f"Cloud prompt must be 1 to {MAX_PROMPT_CHARS} characters.")

    started = time.perf_counter()
    if name == "anthropic":
        body = {
            "model": model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": clean}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        }
    else:
        body = {
            "model": model,
            "messages": [{"role": "user", "content": clean}],
            "temperature": 0.3,
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

    req = Request(spec["endpoint"], data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
    try:
        with net.urlopen(req, cfg, timeout=timeout, purpose=f"cloud_{name}", allow_redirects=False) as resp:
            raw = resp.read(MAX_BYTES + 1)
    except HTTPError as error:
        raise ValueError(f"{spec['label']} returned HTTP {error.code}. Check your API key and model name.") from None
    except URLError:
        raise ValueError(f"Could not reach {spec['host']}.") from None

    if len(raw) > MAX_BYTES:
        raise ValueError("Cloud response exceeded the 1 MB safety limit.")
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError("Cloud provider returned invalid JSON.") from None

    if name == "anthropic":
        blocks = data.get("content") or []
        text = "".join(b.get("text", "") for b in blocks if isinstance(b, dict) and b.get("type") == "text").strip()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        in_tok = usage.get("input_tokens")
        out_tok = usage.get("output_tokens")
    else:
        choices = data.get("choices") or []
        text = (choices[0].get("message", {}).get("content", "") if choices and isinstance(choices[0], dict) else "").strip()
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        in_tok = usage.get("prompt_tokens")
        out_tok = usage.get("completion_tokens")

    if not text:
        raise ValueError("Cloud provider returned an empty response.")
    elapsed = round(time.perf_counter() - started, 3)
    from . import providers
    entry = providers.USAGE.record(name, model, input_tokens=in_tok, output_tokens=out_tok, latency_s=elapsed, tier="cloud")
    secure.audit("cloud_chat", {"provider": name, "model": model, "chars_sent": len(clean), "seconds": elapsed, "cost_usd": entry["cost_usd"]})
    return {
        "provider": spec["label"],
        "model": model,
        "text": text[:100_000],
        "seconds": elapsed,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "cost_usd": entry["cost_usd"],
    }


@skill(
    "Send a single explicitly approved prompt to a configured optional cloud AI provider.",
    params={"prompt": ("string", "Single prompt to send after approval", True)},
    risky=True,
    internet=True,
    untrusted=True,
    manual=True,
    available=ready,
    preview=lambda ctx, prompt: preview_request(ctx.cfg, prompt),
)
def cloud_ask(ctx, prompt):
    result = ask(ctx.cfg, prompt)
    return f"{result['provider']} ({result['model']}, {result['seconds']}s):\n{result['text']}"
