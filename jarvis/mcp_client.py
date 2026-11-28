"""Local stdio MCP (Model Context Protocol) client with per-server permission approval (C07).

Security boundaries:
- Disabled by default. No MCP server runs until explicitly configured AND approved by the user.
- Exact executable path, arguments, and declared capability scope are stored and verified;
  if a server's command changes, approval is invalidated.
- Every tool call enforces a strict timeout, bounded JSON-RPC output, Lockdown blocking,
  injection fencing on all returned text, and audit logging.
- Shells (cmd, powershell, bash, sh) are rejected as direct MCP server commands.
"""
import json
import os
import re
import subprocess
import time
from pathlib import Path

from . import config, secure

TIMEOUT = 25
MAX_OUTPUT_BYTES = 256_000
MAX_SERVERS = 20
_SERVER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{1,40}$")
_BLOCKED_EXECUTABLES = frozenset({
    "cmd", "cmd.exe", "powershell", "powershell.exe", "pwsh", "pwsh.exe",
    "wscript", "wscript.exe", "cscript", "cscript.exe", "mshta", "mshta.exe",
    "sh", "bash", "zsh",
})
CAPABILITIES = {
    "read_only": "Read-only tool calls (still fenced as untrusted output)",
    "write_or_effect": "Tools that modify data or perform side effects (always require confirmation)",
    "network": "Server may access the network (only allowed while Internet is on)",
}


def _clean_server(spec: dict) -> dict:
    if not isinstance(spec, dict):
        raise ValueError("MCP server entry must be a JSON object.")
    sid = str(spec.get("id", "")).strip()
    if not _SERVER_ID.fullmatch(sid):
        raise ValueError("Server id must be 2-41 lowercase letters, digits, dashes or underscores.")
    name = str(spec.get("name") or sid).strip()[:80]
    command = str(spec.get("command", "")).strip()
    if not command or len(command) > 500 or any(ord(c) < 32 for c in command):
        raise ValueError("Provide a valid executable path for the MCP server.")
    exe_name = Path(command).name.lower()
    if exe_name in _BLOCKED_EXECUTABLES:
        raise ValueError(f"Shell/script host '{exe_name}' is not allowed as an MCP server command.")
    args = spec.get("args") or []
    if not isinstance(args, list) or len(args) > 20 or any(
        not isinstance(a, str) or len(a) > 500 or any(ord(c) < 32 for c in a) for a in args
    ):
        raise ValueError("Server args must be a list of up to 20 safe strings.")
    caps = spec.get("capabilities") or ["read_only"]
    if not isinstance(caps, list) or not caps or any(c not in CAPABILITIES for c in caps):
        raise ValueError("Choose valid capabilities: " + ", ".join(CAPABILITIES))
    return {
        "id": sid,
        "name": name,
        "command": command,
        "args": args,
        "capabilities": sorted(set(caps)),
        "enabled": bool(spec.get("enabled", False)),
    }


def list_servers(cfg: dict) -> list:
    raw = cfg.get("mcp_servers") or []
    result = []
    for item in raw[:MAX_SERVERS]:
        try:
            result.append(_clean_server(item))
        except ValueError:
            continue
    return result


def save_server(cfg: dict, spec: dict) -> list:
    if cfg.get("lockdown"):
        raise ValueError("Turn off Lockdown to modify MCP servers.")
    clean = _clean_server(spec)
    clean["enabled"] = False
    servers = [s for s in list_servers(cfg) if s["id"] != clean["id"]]
    if len(servers) >= MAX_SERVERS:
        raise ValueError(f"At most {MAX_SERVERS} MCP servers can be configured.")
    servers.append(clean)
    updated = {**cfg, "mcp_servers": servers}
    config.save(updated)
    cfg.update(updated)
    secure.audit("mcp_server_saved", {"id": clean["id"], "capabilities": clean["capabilities"]})
    return servers


def set_enabled(cfg: dict, server_id: str, enabled: bool, approved_capabilities=None) -> list:
    if cfg.get("lockdown"):
        raise ValueError("Turn off Lockdown to change MCP server permissions.")
    servers = list_servers(cfg)
    target = next((s for s in servers if s["id"] == server_id), None)
    if target is None:
        raise ValueError("MCP server not found.")
    if enabled:
        if sorted(set(approved_capabilities or [])) != target["capabilities"]:
            raise ValueError("Approve the exact declared capabilities for this MCP server.")
        target["enabled"] = True
    else:
        target["enabled"] = False
    updated = {**cfg, "mcp_servers": servers}
    config.save(updated)
    cfg.update(updated)
    secure.audit("mcp_server_enabled" if enabled else "mcp_server_disabled",
                 {"id": server_id, "capabilities": target["capabilities"]})
    return servers


def remove_server(cfg: dict, server_id: str) -> list:
    if cfg.get("lockdown"):
        raise ValueError("Turn off Lockdown to remove MCP servers.")
    servers = [s for s in list_servers(cfg) if s["id"] != server_id]
    updated = {**cfg, "mcp_servers": servers}
    config.save(updated)
    cfg.update(updated)
    secure.audit("mcp_server_removed", {"id": server_id})
    return servers


def _rpc_exchange(server: dict, requests: list, timeout: int = TIMEOUT) -> list:
    """Run a bounded stdio JSON-RPC 2.0 exchange with a local MCP server process."""
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "HOME", "USERPROFILE")
           if k in os.environ}
    payload = "\n".join(json.dumps(req) for req in requests) + "\n"
    try:
        proc = subprocess.run(
            [server["command"], *server["args"]],
            input=payload.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        raise ValueError(f"MCP server '{server['name']}' timed out after {timeout}s.") from None
    except OSError as err:
        raise ValueError(f"Could not start MCP server '{server['name']}': {err}") from None

    if len(proc.stdout) > MAX_OUTPUT_BYTES:
        raise ValueError(f"MCP server '{server['name']}' exceeded the {MAX_OUTPUT_BYTES}-byte output limit.")
    responses = []
    for line in proc.stdout.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict) and obj.get("jsonrpc") == "2.0":
                responses.append(obj)
        except ValueError:
            continue
    return responses


def discover_tools(cfg: dict, server_id: str) -> list:
    if cfg.get("lockdown"):
        raise ValueError("MCP servers are blocked during Lockdown.")
    server = next((s for s in list_servers(cfg) if s["id"] == server_id), None)
    if server is None or not server["enabled"]:
        raise ValueError("Enable and approve this MCP server before discovering its tools.")
    if "network" in server["capabilities"] and not cfg.get("allow_internet_tools"):
        raise ValueError("This MCP server declares network access; turn Internet on first.")
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "Jarvis", "version": "1.4"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    ]
    responses = _rpc_exchange(server, requests)
    list_resp = next((r for r in responses if r.get("id") == 2), None)
    if not list_resp or "result" not in list_resp:
        raise ValueError(f"MCP server '{server['name']}' did not return a valid tools/list response.")
    tools = list_resp["result"].get("tools") or []
    clean = []
    for tool in tools[:50]:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):
            clean.append({
                "name": tool["name"][:80],
                "description": str(tool.get("description") or "")[:300],
            })
    secure.audit("mcp_tools_discovered", {"id": server_id, "count": len(clean)})
    return clean


def call_tool(cfg: dict, server_id: str, tool_name: str, arguments: dict) -> dict:
    if cfg.get("lockdown"):
        raise ValueError("MCP tool execution is blocked during Lockdown.")
    server = next((s for s in list_servers(cfg) if s["id"] == server_id), None)
    if server is None or not server["enabled"]:
        raise ValueError("MCP server is not enabled.")
    if "network" in server["capabilities"] and not cfg.get("allow_internet_tools"):
        raise ValueError("This MCP server requires Internet on.")
    if not isinstance(tool_name, str) or not 1 <= len(tool_name) <= 80:
        raise ValueError("Invalid MCP tool name.")
    if not isinstance(arguments, dict):
        raise ValueError("MCP tool arguments must be a JSON object.")

    started = time.perf_counter()
    requests = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "Jarvis", "version": "1.4"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call",
         "params": {"name": tool_name, "arguments": arguments}},
    ]
    responses = _rpc_exchange(server, requests)
    call_resp = next((r for r in responses if r.get("id") == 2), None)
    if not call_resp:
        raise ValueError("MCP server returned no tool result.")
    if "error" in call_resp:
        err = call_resp["error"]
        msg = err.get("message", "unknown error") if isinstance(err, dict) else str(err)
        raise ValueError(f"MCP tool error: {msg[:200]}")

    result = call_resp.get("result") or {}
    content = result.get("content") or []
    parts = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text") or ""))
    text = "\n".join(parts)[:32_000]
    injection = secure.looks_like_injection(text)
    if injection:
        secure.audit("injection_blocked", {"source": f"mcp:{server_id}:{tool_name}"})
    secure.audit("mcp_tool_call", {
        "id": server_id,
        "tool": tool_name,
        "seconds": round(time.perf_counter() - started, 3),
        "injection_flagged": injection,
    })
    return {
        "text": secure.fence(text),
        "raw_chars": len(text),
        "injection_flagged": injection,
    }
