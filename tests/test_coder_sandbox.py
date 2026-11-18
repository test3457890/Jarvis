"""Tests for coder.py path confinement and no-network sandbox."""
from pathlib import Path

import pytest

from jarvis import coder, skills


def test_path_traversal_blocked(isolated_app):
    cfg, _, _, _ = isolated_app
    for bad in ("../outside.py", "..\\outside.py", "C:\\Windows\\system32\\evil.py"):
        with pytest.raises(ValueError):
            coder._safe_path(cfg, bad)


def test_run_code_requires_confirmation_and_blocks_network(isolated_app):
    cfg, _, ctx, _ = isolated_app
    script = Path(cfg["code_dir"]) / "net_probe.py"
    script.write_text(
        "import os, socket\n"
        "print('APPDATA_PRESENT=' + str('APPDATA' in os.environ))\n"
        "try:\n"
        "    socket.create_connection(('127.0.0.1', 80), timeout=1)\n"
        "    print('NET_ALLOWED')\n"
        "except PermissionError as e:\n"
        "    print('NET_BLOCKED:' + str(e))\n",
        encoding="utf-8",
    )

    # Must ask first
    pending_msg = skills.run(ctx, "run_code", {"filename": "net_probe.py"})
    assert "NOT DONE YET" in pending_msg
    assert ctx.pending is not None

    # Confirmed execution runs in sandbox with no network and stripped env
    res = skills.run(ctx, "run_code", {"filename": "net_probe.py"}, confirmed=True)
    assert "Exit code 0" in res
    assert "APPDATA_PRESENT=False" in res
    assert "NET_BLOCKED:" in res
    assert "NET_ALLOWED" not in res


def test_fix_preview_and_backup(isolated_app, monkeypatch):
    cfg, _, ctx, _ = isolated_app
    path = Path(cfg["code_dir"]) / "budget.py"
    original = b"total = 1\r\n"
    path.write_bytes(original)

    class FakeCoder:
        def raw_chat(self, messages, model):
            import json
            request = json.loads(messages[1]["content"])
            assert request["source"].encode() == original
            assert request["task"] == "Use two"
            assert model == cfg["coder_model"]
            return "```python\ntotal = 2\n```"

    monkeypatch.setattr(coder, "_brain", FakeCoder())
    args = {"filename": path.name, "change": "Use two"}
    backup = path.with_suffix(".py.bak")
    preview = skills.run(ctx, "fix_code", {**args, "preview_only": True})
    assert "-total = 1" in preview and "+total = 2" in preview
    assert path.read_bytes() == original
    assert not backup.exists()

    assert "Updated budget.py" in skills.run(ctx, "fix_code", args)
    assert path.read_bytes() == b"total = 2\r\n"
    assert backup.read_bytes() == original


@pytest.mark.parametrize("reply", [
    "Here is the Python file but I forgot to include it.",
    "```python\nif True print('broken')\n```",
    "```python\nprint('truncated')",
    "```python\nx = 1\n```\n```python\nx = 2\n```",
])
def test_fix_rejects_bad_output_without_touching_files(isolated_app, monkeypatch, reply):
    cfg, _, ctx, _ = isolated_app
    path = Path(cfg["code_dir"]) / "budget.py"
    path.write_bytes(b"total = 1\n")

    class FakeCoder:
        def raw_chat(self, messages, model):
            return reply

    monkeypatch.setattr(coder, "_brain", FakeCoder())
    result = skills.run(ctx, "fix_code", {"filename": path.name, "change": "Use two"})
    assert "Nothing was saved" in result
    assert path.read_bytes() == b"total = 1\n"
    assert not path.with_suffix(".py.bak").exists()
