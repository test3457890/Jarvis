"""Optional loopback-only chat-completions adapter. No cloud fallback or redirects."""
import json
import time
from urllib.error import HTTPError
from urllib.request import Request

from . import net

MAX_BYTES = 1_000_000


def endpoint(cfg):
    # Reuse the strict numeric-loopback validator; paths and embedded credentials are refused.
    result = net.local_image_endpoint(cfg.get("local_chat_url"))
    if result is None:
        raise ValueError("Use a local HTTP address such as http://127.0.0.1:8081, without a path or credentials.")
    return result


def model_name(value):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= 200 or any(ord(c) < 32 for c in value):
        raise ValueError("Enter the exact local model ID, up to 200 characters.")
    return value.strip()


def _json(req, cfg, timeout):
    try:
        with net.urlopen(req, cfg, timeout=timeout, purpose="local_chat_provider",
                         allow_redirects=False, bypass_proxy=True) as response:
            raw = response.read(MAX_BYTES + 1)
        if len(raw) > MAX_BYTES:
            raise ValueError("The local model response exceeded its size limit.")
        try:
            data = json.loads(raw)
        except (ValueError, RecursionError):
            raise ValueError("The local model returned invalid JSON.") from None
        if not isinstance(data, dict):
            raise ValueError("The local model returned an invalid response.")
        return data
    except HTTPError as error:
        # Server error bodies can echo prompts. Never return those bodies to logs or the HUD.
        raise ValueError(f"Local model HTTP {error.code}. Check the model ID and server configuration.") from None


def models(cfg):
    data = _json(Request(endpoint(cfg) + "/v1/models", headers={"Accept":"application/json"}), cfg, 5)
    rows = data.get("data")
    if not isinstance(rows, list):
        raise ValueError("The local server did not return a model list.")
    names = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            raise ValueError("The local server returned an invalid model record.")
        names.append(model_name(row.get("id")))
    return list(dict.fromkeys(names))


def messages_for_api(messages):
    result = []
    for message in messages:
        role = message.get("role")
        if role not in ("system", "user", "assistant", "tool"):
            raise ValueError("Unsupported local chat message role.")
        item = {"role":role, "content":message.get("content") or ""}
        if role == "assistant" and message.get("tool_calls"):
            calls = []
            for call in message["tool_calls"]:
                fn = call["function"]
                calls.append({"id":call["id"], "type":"function", "function":{
                    "name":fn["name"], "arguments":json.dumps(fn["arguments"]) if isinstance(fn["arguments"], dict) else fn["arguments"]}})
            item["tool_calls"] = calls
        if role == "tool":
            if not isinstance(message.get("tool_call_id"), str):
                raise ValueError("A local tool result has no matching call ID.")
            item["tool_call_id"] = message["tool_call_id"]
        result.append(item)
    return result


def normalise(data):
    choices = data.get("choices")
    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
        raise ValueError("The local server must return one completed choice.")
    choice = choices[0]
    reason, message = choice.get("finish_reason"), choice.get("message")
    if reason not in ("stop", "tool_calls", "length") or not isinstance(message, dict) or message.get("role") != "assistant":
        raise ValueError("The local model response is incomplete or unsupported. No tools were run.")
    content = message.get("content") or ""
    if not isinstance(content, str) or len(content) > 250_000:
        raise ValueError("The local response content is invalid or too large.")
    calls = message.get("tool_calls") or []
    if not isinstance(calls, list) or len(calls) > 16 or calls and reason != "tool_calls":
        raise ValueError("The local tool response is incomplete or too large. No tools were run.")
    output, ids = [], set()
    for call in calls:
        if not isinstance(call, dict) or call.get("type") != "function":
            raise ValueError("Unsupported local model tool call.")
        key, fn = call.get("id"), call.get("function")
        if not isinstance(key, str) or not 1 <= len(key) <= 160 or key in ids or not isinstance(fn, dict):
            raise ValueError("Invalid or repeated local tool call ID.")
        name, args = fn.get("name"), fn.get("arguments")
        if not isinstance(name, str) or not 1 <= len(name) <= 120 or not isinstance(args, str) or len(args) > 32000:
            raise ValueError("Invalid local model tool arguments.")
        try:
            args = json.loads(args)
        except (ValueError, RecursionError):
            raise ValueError("The local model returned malformed tool arguments. No tools were run.") from None
        if not isinstance(args, dict):
            raise ValueError("Local tool arguments must be a JSON object.")
        ids.add(key)
        output.append({"id":key, "type":"function", "function":{"name":name, "arguments":args}})
    if reason == "tool_calls" and not output:
        raise ValueError("The local server omitted the completed tool calls.")
    return {"done":True, "done_reason":reason, "message":{"role":"assistant", "content":content, "tool_calls":output}}


def chat(cfg, payload, cancelled, metrics, timeout):
    if cancelled.is_set():
        raise ValueError("Stopped by the user.")
    model = model_name(cfg.get("local_chat_model"))
    body = {"model":model, "messages":messages_for_api(payload["messages"]), "stream":False,
            "temperature":payload.get("options", {}).get("temperature", 0.3)}
    if payload.get("tools"):
        body["tools"] = payload["tools"]
    started = time.perf_counter()
    data = _json(Request(endpoint(cfg) + "/v1/chat/completions", method="POST",
                         data=json.dumps(body).encode(), headers={"Content-Type":"application/json"}), cfg, timeout)
    if cancelled.is_set():
        raise ValueError("Stopped by the user.")
    result = normalise(data)
    metrics({"model":model, "first_token_seconds":None, "response_seconds":round(time.perf_counter()-started, 3),
             "output_tokens":None})
    return result
