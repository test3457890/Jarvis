"""Extensions: small local add-ons that declare what they need before they can run.

An extension is a folder in %APPDATA%\\Jarvis\\extensions\\<id> with an extension.json manifest
and a Python file. Nothing loads by default. The user enables each extension and approves the
exact permissions it declares. If the manifest later asks for more, the extension is disabled
until the user approves again.

Each tool runs in a separate Python process with a reduced environment, a time limit, JSON in and
out, and network functions blocked unless the extension declared and was granted "network" and
the Internet toggle is on. This is a boundary against mistakes, not a sandbox against hostile
code: an extension still runs as the Windows user. Only install extensions you trust.

Manifest example (see docs/Extensions.md):
{
  "id": "word-count", "name": "Word count", "version": "1.0.0",
  "description": "Count words in text.",
  "entry": "main.py",
  "permissions": [],
  "tools": [{"name": "count_words", "description": "Count words in a piece of text.",
             "inputs": {"text": {"type": "string", "description": "Text to count", "required": true}},
             "outputs": {"words": "integer"}, "risky": false}],
  "tests": [{"tool": "count_words", "input": {"text": "one two three"}, "expect": {"words": 3}}]
}
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

from . import config, secure, skills

PERMISSIONS = {
    "network": "Allow network use while Internet is on; network_hosts are declared for review, not enforced",
    "read_selected_folders": "Read files inside your selected file-task folders",
    "write_selected_folders": "Create or change files inside your selected file-task folders",
}
TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}
TIMEOUT = 30
MAX_OUTPUT = 100_000
_ID = re.compile(r"[a-z0-9][a-z0-9-]{1,40}")
_TOOL = re.compile(r"[a-z][a-z0-9_]{1,40}")
_HOST = re.compile(r"[a-z0-9.-]{3,253}")

_RUNNER = r"""
import json, socket, sys, runpy
granted = set(json.loads(sys.argv[3]))
if "network" not in granted:
    def _blocked(*a, **k):
        raise PermissionError("This extension was not granted network access.")
    for _name in ("socket", "create_connection", "getaddrinfo", "gethostbyname"):
        setattr(socket, _name, _blocked)
module = runpy.run_path(sys.argv[1])
request = json.loads(sys.stdin.read())
result = module[sys.argv[2]](**request)
sys.stdout.write(json.dumps({"result": result}))
"""


def folder():
    return config.APP_DIR / "extensions"


def validate_manifest(data, base):
    """Return a cleaned manifest or raise ValueError naming the problem."""
    if not isinstance(data, dict):
        raise ValueError("extension.json must be a JSON object.")
    ext_id = str(data.get("id", ""))
    if not _ID.fullmatch(ext_id) or ext_id != base.name:
        raise ValueError("id must be lowercase letters, digits and dashes, and match the folder name.")
    entry = str(data.get("entry", "main.py"))
    entry_path = (base / entry).resolve()
    if base.resolve() not in entry_path.parents or entry_path.suffix != ".py" or not entry_path.is_file():
        raise ValueError("entry must be a .py file inside the extension folder.")
    permissions = data.get("permissions", [])
    if not isinstance(permissions, list) or any(p not in PERMISSIONS for p in permissions):
        raise ValueError("Unknown permission. Allowed: " + ", ".join(PERMISSIONS))
    hosts = data.get("network_hosts", [])
    if hosts and "network" not in permissions:
        raise ValueError("network_hosts needs the network permission.")
    if not isinstance(hosts, list) or any(not _HOST.fullmatch(str(h)) for h in hosts):
        raise ValueError("network_hosts must be plain host names.")
    tools = data.get("tools")
    if not isinstance(tools, list) or not 1 <= len(tools) <= 10:
        raise ValueError("Declare between 1 and 10 tools.")
    clean_tools = []
    for tool in tools:
        name = str(tool.get("name", ""))
        if not _TOOL.fullmatch(name):
            raise ValueError(f"Tool name {name!r} must be lowercase letters, digits and underscores.")
        inputs = tool.get("inputs", {})
        if not isinstance(inputs, dict) or any(
                not isinstance(spec, dict) or spec.get("type") not in TYPES for spec in inputs.values()):
            raise ValueError(f"{name}: each input needs a type of {', '.join(TYPES)}.")
        outputs = tool.get("outputs", {})
        if not isinstance(outputs, dict) or any(kind not in TYPES for kind in outputs.values()):
            raise ValueError(f"{name}: outputs must map names to {', '.join(TYPES)}.")
        clean_tools.append({"name": name, "description": str(tool.get("description", ""))[:300],
                            "inputs": inputs, "outputs": outputs,
                            # Anything that can write or reach the network always needs confirmation.
                            "risky": bool(tool.get("risky")) or bool(
                                {"network", "write_selected_folders"} & set(permissions))})
    tests = data.get("tests", [])
    if not isinstance(tests, list):
        raise ValueError("tests must be a list.")
    return {"id": ext_id, "name": str(data.get("name", ext_id))[:60], "version": str(data.get("version", "0"))[:20],
            "description": str(data.get("description", ""))[:300], "entry": str(entry_path),
            "permissions": sorted(set(permissions)), "network_hosts": sorted(set(hosts)),
            "tools": clean_tools, "tests": tests, "path": str(base)}


def discover():
    """All extensions on disk, valid or not. Nothing is loaded or run here."""
    found = []
    if not folder().is_dir():
        return found
    for base in sorted(folder().iterdir()):
        if not base.is_dir() or base.is_symlink():
            continue
        try:
            data = json.loads((base / "extension.json").read_text(encoding="utf-8"))
            found.append({"ok": True, "manifest": validate_manifest(data, base)})
        except (OSError, ValueError) as error:
            found.append({"ok": False, "id": base.name, "error": str(error)})
    return found


def granted(cfg, manifest):
    """Permissions the user approved for this extension, or None if it is not enabled or asks for more."""
    approval = (cfg.get("enabled_extensions") or {}).get(manifest["id"])
    if not isinstance(approval, dict):
        return None
    approved = set(approval.get("permissions", []))
    if not set(manifest["permissions"]) <= approved or set(manifest["network_hosts"]) - set(approval.get("hosts", [])):
        return None  # The manifest changed to ask for more. Ask the user again.
    return approved


def status(cfg):
    rows = []
    for item in discover():
        if not item["ok"]:
            rows.append({"id": item["id"], "valid": False, "error": item["error"], "enabled": False})
            continue
        manifest = item["manifest"]
        enabled = granted(cfg, manifest) is not None
        needs_approval = manifest["id"] in (cfg.get("enabled_extensions") or {}) and not enabled
        rows.append({"id": manifest["id"], "name": manifest["name"], "version": manifest["version"],
                     "description": manifest["description"], "valid": True, "enabled": enabled,
                     "needs_new_approval": needs_approval,
                     "permissions": [{"name": p, "meaning": PERMISSIONS[p]} for p in manifest["permissions"]],
                     "network_hosts": manifest["network_hosts"],
                     "tools": [{"name": t["name"], "description": t["description"], "risky": t["risky"]}
                               for t in manifest["tools"]]})
    return rows


def set_enabled(cfg, ext_id, enabled, approved_permissions=None):
    manifest = next((i["manifest"] for i in discover() if i["ok"] and i["manifest"]["id"] == ext_id), None)
    if not manifest:
        raise ValueError("That extension is missing or its manifest is invalid.")
    approvals = dict(cfg.get("enabled_extensions") or {})
    if enabled:
        if sorted(approved_permissions or []) != manifest["permissions"]:
            raise ValueError("Approve exactly the permissions this extension declares.")
        approvals[ext_id] = {"permissions": manifest["permissions"], "hosts": manifest["network_hosts"],
                             "version": manifest["version"]}
    else:
        approvals.pop(ext_id, None)
    updated = {**cfg, "enabled_extensions": approvals}
    config.save(updated)
    cfg.update(updated)
    secure.audit("extension_enabled" if enabled else "extension_disabled",
                 {"id": ext_id, "permissions": manifest["permissions"]})
    register(cfg)
    return status(cfg)


def _check_inputs(tool, args):
    clean = {}
    for name, spec in tool["inputs"].items():
        if name not in args:
            if spec.get("required"):
                raise ValueError(f"Missing input {name}.")
            continue
        if not isinstance(args[name], TYPES[spec["type"]]) or isinstance(args[name], bool) != (spec["type"] == "boolean"):
            raise ValueError(f"Input {name} must be {spec['type']}.")
        clean[name] = args[name]
    unknown = set(args) - set(tool["inputs"])
    if unknown:
        raise ValueError("Unknown inputs: " + ", ".join(sorted(unknown)))
    return clean


def _check_outputs(tool, result):
    if not isinstance(result, dict):
        raise ValueError("The extension returned something other than an object.")
    for name, kind in tool["outputs"].items():
        if name not in result or not isinstance(result[name], TYPES[kind]):
            raise ValueError(f"The extension's output {name} is missing or not {kind}.")
    return result


def call(cfg, manifest, tool_name, args, permissions):
    tool = next(t for t in manifest["tools"] if t["name"] == tool_name)
    clean = _check_inputs(tool, args)
    network = "network" in permissions and cfg.get("allow_internet_tools")
    effective = sorted(permissions - ({"network"} if not network else set()))
    env = {k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP") if k in os.environ}
    if "read_selected_folders" in permissions or "write_selected_folders" in permissions:
        env["JARVIS_SELECTED_FOLDERS"] = os.pathsep.join(cfg.get("file_folders") or [])
    try:
        result = subprocess.run([sys.executable, "-I", "-c", _RUNNER, manifest["entry"], tool_name, json.dumps(effective)],
                                input=json.dumps(clean), capture_output=True, text=True, timeout=TIMEOUT,
                                cwd=manifest["path"], env=env,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise ValueError(f"{manifest['name']} took longer than {TIMEOUT} seconds and was stopped.") from None
    if result.returncode:
        raise ValueError(f"{manifest['name']} failed: " + (result.stderr.strip().splitlines() or ["no details"])[-1][:300])
    if len(result.stdout) > MAX_OUTPUT:
        raise ValueError("The extension returned too much output.")
    try:
        payload = json.loads(result.stdout)["result"]
    except (ValueError, KeyError, TypeError):
        raise ValueError(f"{manifest['name']} did not return valid JSON.") from None
    return _check_outputs(tool, payload)


def _skill_name(ext_id, tool_name):
    return "ext_" + ext_id.replace("-", "_") + "__" + tool_name


def register(cfg):
    """Expose enabled extensions' tools as Jarvis skills. Disabled ones are removed."""
    for name in [n for n in skills.SKILLS if n.startswith("ext_")]:
        del skills.SKILLS[name]
    for item in discover():
        if not item["ok"]:
            continue
        manifest = item["manifest"]
        permissions = granted(cfg, manifest)
        if permissions is None:
            continue
        for tool in manifest["tools"]:
            def run(ctx, _m=manifest, _t=tool["name"], _p=permissions, **args):
                secure.audit("extension_tool", {"id": _m["id"], "tool": _t})
                return json.dumps(call(ctx.cfg, _m, _t, args, _p))

            run.__name__ = _skill_name(manifest["id"], tool["name"])
            params = {key: (spec["type"], str(spec.get("description", key))[:200], bool(spec.get("required")))
                      for key, spec in tool["inputs"].items()}
            preview = (lambda ctx, _m=manifest, _t=tool["name"], **a:
                       f"run extension {_m['name']} tool {_t} with {json.dumps(a)[:300]}")
            skills.skill(f"[Extension {manifest['name']}] {tool['description']}", params=params,
                         risky=tool["risky"], untrusted=True, preview=preview,
                         internet="network" in permissions)(run)


def run_tests(cfg, ext_id):
    """Run the tests an extension declares. Returns (passed, failed, details)."""
    manifest = next((i["manifest"] for i in discover() if i["ok"] and i["manifest"]["id"] == ext_id), None)
    if not manifest:
        raise ValueError("That extension is missing or its manifest is invalid.")
    if granted(cfg, manifest) is None:
        raise ValueError("Enable and approve this extension before running its tests.")
    permissions = set(manifest["permissions"]) - {"network"}  # Tests never use the network.
    passed, details = 0, []
    for number, test in enumerate(manifest["tests"], 1):
        try:
            result = call({**cfg, "allow_internet_tools": False}, manifest, test["tool"], test.get("input", {}), permissions)
            expected = test.get("expect", {})
            if all(result.get(key) == value for key, value in expected.items()):
                passed += 1
                details.append(f"test {number}: passed")
            else:
                details.append(f"test {number}: expected {expected}, got {result}")
        except (ValueError, StopIteration, KeyError) as error:
            details.append(f"test {number}: {error}")
    return passed, len(manifest["tests"]) - passed, details


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(prog="python -m jarvis.extensions")
    parser.add_argument("command", choices=["list", "test"])
    parser.add_argument("id", nargs="?")
    args = parser.parse_args(argv)
    cfg = config.load()
    if args.command == "list":
        print(json.dumps(status(cfg), indent=2))
        return 0
    passed, failed, details = run_tests(cfg, args.id)
    print("\n".join(details))
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
