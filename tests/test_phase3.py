import json
import os
import shutil
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from jarvis import appactions, config, documents, extensions, skills


# ------------------------------------------------------------------ voice
@pytest.fixture
def listener(monkeypatch):
    import importlib.util
    monkeypatch.setitem(sys.modules, "winsound", MagicMock())
    monkeypatch.setitem(sys.modules, "numpy", MagicMock())
    spec = importlib.util.spec_from_file_location("voice_listen", Path(__file__).parents[1] / "jarvis" / "voice.py")
    voice = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(voice)
    monkeypatch.setattr(voice, "load_whisper", lambda cfg: None)
    heard = []
    return voice.Listener(dict(config.DEFAULTS), None, None, lambda kind, data: heard.append(data))


@pytest.mark.parametrize("text, command", [
    ("Jarvis, what's on today?", "Jarvis, what's on today?"),
    ("what do you think, Jarvis?", "what do you think, Jarvis?"),
    ("Jarvis.", ""),
    ("Jarvis, stop.", "stop"),
    ("Jervis never mind", "stop"),
    ("Tuki, check this maths", "Tuki: check this maths"),
    ("Thanks for watching!", None),
    ("[BLANK_AUDIO]", None),
    ("the weather is nice", None),
])
def test_wake_words_and_spoken_stop(listener, text, command):
    assert listener.interpret(text, time.time()) == command


def test_follow_up_window_and_stop(listener):
    now = time.time()
    listener.follow_until = now + 5
    assert listener.interpret("and tomorrow?", now) == "and tomorrow?"
    listener.follow_until = now + 5
    assert listener.interpret("cancel", now) == "stop"
    assert listener.interpret("unrelated chatter", now) is None


def test_pausing_mic_discards_context_and_inflight_transcription(listener):
    now = time.time()
    assert listener.interpret("nearby conversation", now) is None
    listener.keep_listening_for_follow_up()
    generation = listener._generation
    listener.pause()
    assert listener.room_context() == "" and listener.follow_until == 0
    assert listener.interpret("Jarvis, respond", now) is None
    listener.resume()
    commands = []
    listener.on_command = lambda *args: commands.append(args)
    listener.model = SimpleNamespace(transcribe=lambda *args, **kwargs: (
        [SimpleNamespace(text="Jarvis, respond", no_speech_prob=0)], None))
    listener._handle(object(), generation)
    assert not commands
    assert listener.interpret("Jarvis, respond", now) == "Jarvis, respond"


def test_context_and_followups_can_be_disabled(listener):
    listener.cfg["room_context_seconds"] = 0
    listener.cfg["follow_up_seconds"] = 0
    listener.keep_listening_for_follow_up()
    assert listener.follow_until == 0
    now = time.time()
    assert listener.interpret("private conversation", now) is None
    assert listener.interpret("Jarvis, hello", now) == "Jarvis, hello"
    assert listener.room_context() == "" and not listener.room


# ------------------------------------------------------------------ OCR
def _scanned_pdf(path, words):
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("L", (1700, 400), 255)
    ImageDraw.Draw(image).text((40, 120), words, fill=0, font=ImageFont.load_default(size=64))
    image.save(path, "PDF", resolution=200)


def test_ocr_is_off_by_default_and_used_when_enabled(isolated_app, tmp_path, monkeypatch):
    cfg, _, ctx, _ = isolated_app
    folder = tmp_path / "scans"
    folder.mkdir()
    _scanned_pdf(folder / "receipt.pdf", "Hardware receipt total 42")
    cfg["document_folders"] = [str(folder)]
    calls = []
    monkeypatch.setattr(documents, "ocr_image", lambda tess, data, suffix: calls.append(suffix) or "Hardware receipt total 42")
    monkeypatch.setattr(documents, "tesseract_path", lambda cfg: "/fake/tesseract" if cfg.get("ocr_enabled") else None)
    documents._OCR_CACHE.clear()
    assert "No matching" in skills.run(ctx, "search_documents", {"query": "hardware receipt"})
    assert not calls
    cfg["ocr_enabled"] = True
    result = skills.run(ctx, "search_documents", {"query": "hardware receipt"})
    assert "page 1 (OCR)" in result and "local OCR" in result
    skills.run(ctx, "search_documents", {"query": "hardware receipt"})
    assert len(calls) == 1, "unchanged files reuse the OCR result"


@pytest.mark.skipif(not shutil.which("tesseract"), reason="Tesseract is not installed")
def test_real_tesseract_reads_a_scanned_page(isolated_app, tmp_path):
    cfg, _, ctx, _ = isolated_app
    folder = tmp_path / "scans"
    folder.mkdir()
    _scanned_pdf(folder / "invoice.pdf", "Scanned invoice total 42")
    cfg.update(document_folders=[str(folder)], ocr_enabled=True)
    documents._OCR_CACHE.clear()
    assert "invoice.pdf, page 1 (OCR)" in skills.run(ctx, "search_documents", {"query": "scanned invoice"})


def test_tesseract_requires_opt_in(tmp_path):
    fake = tmp_path / "tesseract.exe"
    fake.write_text("")
    assert documents.tesseract_path({"tesseract_path": str(fake)}) is None
    assert documents.tesseract_path({"tesseract_path": str(fake), "ocr_enabled": True}) == str(fake)


# ------------------------------------------------------------------ app actions
@pytest.fixture
def program(tmp_path):
    """A harmless real program to start: a copy of `sleep` (POSIX) or `timeout` substitutes."""
    found = shutil.which("sleep")
    if not found or os.name == "nt":
        pytest.skip("needs a POSIX sleep program")
    return found


def test_shells_and_script_hosts_are_refused(tmp_path):
    for name in ("cmd.exe", "powershell.exe", "pwsh", "bash", "python3", "python3.12", "wscript.exe"):
        fake = tmp_path / name
        fake.write_text("")
        with pytest.raises(ValueError):
            appactions.validate({"name": "x", "program": str(fake)})
    with pytest.raises(ValueError, match="full path"):
        appactions.validate({"name": "x", "program": "notepad.exe"})


@pytest.mark.skipif(os.name == "nt", reason="symlink creation needs privileges on Windows")
def test_app_alias_to_shell_is_refused(tmp_path):
    shell = tmp_path / "bash"
    shell.write_text("")
    alias = tmp_path / "paint"
    alias.symlink_to(shell)
    with pytest.raises(ValueError, match="can run any command"):
        appactions.validate({"name": "Paint", "program": str(alias)})


def test_app_action_needs_confirmation_and_can_be_stopped(isolated_app, program, monkeypatch):
    cfg, _, ctx, _ = isolated_app
    ctx.cancelled = threading.Event()
    monkeypatch.setattr(appactions, "STARTUP_CHECK_SECONDS", 0.3)
    appactions.save_actions(cfg, [{"name": "Wait", "program": program}])
    message = skills.run(ctx, "run_app_action", {"name": "Wait"})
    assert "NOT DONE YET" in message and str(Path(program).resolve()) in ctx.pending["preview"]
    assert not appactions.running()
    # The real program ignores extra arguments here, so start it with a duration via a wrapper action.
    monkeypatch.setattr(appactions, "_command", lambda cfg, name, file="": ({"name": "Wait", "program": program}, [program, "30"]))
    assert skills.run(ctx, "run_app_action", {"name": "Wait"}, confirmed=True) == "Started Wait."
    assert [item["name"] for item in appactions.running()] == ["Wait"]
    assert appactions.stop_all() == ["Wait"] and appactions.running() == []


def test_immediate_failure_is_reported(isolated_app, program, monkeypatch):
    cfg, _, ctx, _ = isolated_app
    ctx.cancelled = threading.Event()
    appactions.save_actions(cfg, [{"name": "Bad", "program": program}])
    monkeypatch.setattr(appactions, "_command", lambda cfg, name, file="": ({"name": "Bad", "program": program}, [program, "not-a-number"]))
    result = skills.run(ctx, "run_app_action", {"name": "Bad"}, confirmed=True)
    assert "stopped right away with exit code" in result


def test_files_must_come_from_selected_folders(isolated_app, program, tmp_path):
    cfg, _, ctx, _ = isolated_app
    selected = tmp_path / "Pictures"
    selected.mkdir()
    (selected / "cat.png").write_bytes(b"png")
    cfg["file_folders"] = [str(selected)]
    appactions.save_actions(cfg, [{"name": "Viewer", "program": program, "takes_file": True}])
    assert str(selected / "cat.png") in appactions._preview(ctx, "Viewer", "0:cat.png")
    for bad in ("0:../secret.txt", "0:missing.png", "", "3:cat.png"):
        with pytest.raises((ValueError, IndexError)):
            appactions._preview(ctx, "Viewer", bad)
    with pytest.raises(ValueError, match="approved"):
        appactions._preview(ctx, "Something else")
    cfg["lockdown"] = True
    assert "Lockdown" in skills.run(ctx, "run_app_action", {"name": "Viewer", "file": "0:cat.png"})


# ------------------------------------------------------------------ extensions
EXAMPLE = Path(__file__).parents[1] / "docs" / "examples" / "extensions" / "word-count"


def install(app_dir, ext_id="word-count", manifest=None, code=None):
    target = app_dir / "extensions" / ext_id
    if manifest is None:
        shutil.copytree(EXAMPLE, target)
    else:
        target.mkdir(parents=True)
        (target / "extension.json").write_text(json.dumps(manifest))
        (target / "main.py").write_text(code)
    return target


def test_extensions_do_nothing_until_enabled_with_exact_permissions(isolated_app):
    cfg, _, ctx, app_dir = isolated_app
    install(app_dir)
    extensions.register(cfg)
    assert not [n for n in skills.SKILLS if n.startswith("ext_")]
    with pytest.raises(ValueError, match="exactly"):
        extensions.set_enabled(cfg, "word-count", True, ["network"])
    extensions.set_enabled(cfg, "word-count", True, [])
    name = "ext_word_count__count_words"
    assert name in skills.SKILLS and not skills.SKILLS[name]["risky"]
    result = skills.run(ctx, name, {"text": "alpha beta"})
    assert '"words": 2' in result
    assert "must be string" in skills.run(ctx, name, {"text": 5})
    extensions.set_enabled(cfg, "word-count", False)
    assert name not in skills.SKILLS


def test_declared_tests_run(isolated_app):
    cfg, _, _, app_dir = isolated_app
    install(app_dir)
    with pytest.raises(ValueError, match="Enable and approve"):
        extensions.run_tests(cfg, "word-count")
    extensions.set_enabled(cfg, "word-count", True, [])
    assert extensions.run_tests(cfg, "word-count") == (2, 0, ["test 1: passed", "test 2: passed"])


NETWORK_MANIFEST = {
    "id": "net-probe", "name": "Net probe", "version": "1", "entry": "main.py",
    "permissions": ["network"], "network_hosts": ["example.org"],
    "tools": [{"name": "probe", "description": "Try to connect.", "inputs": {}, "outputs": {"ok": "boolean"}}],
}
NETWORK_CODE = ("import socket\n\ndef probe():\n    try:\n        socket.getaddrinfo('example.org', 443)\n"
                "        return {'ok': True}\n    except PermissionError:\n        return {'ok': False}\n")


def test_network_is_blocked_unless_granted_and_internet_on(isolated_app):
    cfg, _, ctx, app_dir = isolated_app
    install(app_dir, "net-probe", NETWORK_MANIFEST, NETWORK_CODE)
    manifest = next(i["manifest"] for i in extensions.discover() if i["ok"])
    assert manifest["tools"][0]["risky"], "network tools always ask first"
    assert extensions.call(cfg, manifest, "probe", {}, set()) == {"ok": False}
    cfg["allow_internet_tools"] = False
    assert extensions.call(cfg, manifest, "probe", {}, {"network"}) == {"ok": False}
    extensions.set_enabled(cfg, "net-probe", True, ["network"])
    assert "offline" in skills.run(ctx, "ext_net_probe__probe", {})
    cfg["allow_internet_tools"] = True
    assert "NOT DONE YET" in skills.run(ctx, "ext_net_probe__probe", {})


def test_more_permissions_after_approval_disable_the_extension(isolated_app):
    cfg, _, _, app_dir = isolated_app
    target = install(app_dir)
    extensions.set_enabled(cfg, "word-count", True, [])
    data = json.loads((target / "extension.json").read_text())
    data["permissions"] = ["write_selected_folders"]
    (target / "extension.json").write_text(json.dumps(data))
    extensions.register(cfg)
    row = extensions.status(cfg)[0]
    assert not row["enabled"] and row["needs_new_approval"]
    assert "ext_word_count__count_words" not in skills.SKILLS


@pytest.mark.parametrize("change, message", [
    ({"id": "Other"}, "id must"),
    ({"entry": "../escape.py"}, "entry"),
    ({"permissions": ["admin"]}, "Unknown permission"),
    ({"tools": []}, "between 1 and 10"),
    ({"network_hosts": ["example.org"]}, "needs the network permission"),
])
def test_invalid_manifests_are_reported_not_loaded(isolated_app, change, message):
    cfg, _, _, app_dir = isolated_app
    target = install(app_dir)
    data = json.loads((target / "extension.json").read_text())
    data.update(change)
    (target / "extension.json").write_text(json.dumps(data))
    row = extensions.status(cfg)[0]
    assert not row["valid"] and message in row["error"]


def test_bad_output_and_timeouts_are_errors(isolated_app, monkeypatch):
    cfg, _, _, app_dir = isolated_app
    manifest = {"id": "bad-tool", "name": "Bad", "version": "1", "entry": "main.py", "permissions": [],
                "tools": [{"name": "wrong", "description": "", "inputs": {}, "outputs": {"n": "integer"}},
                          {"name": "slow", "description": "", "inputs": {}, "outputs": {}}]}
    install(app_dir, "bad-tool", manifest,
            "import time\n\ndef wrong():\n    return {'n': 'text'}\n\ndef slow():\n    time.sleep(5)\n    return {}\n")
    found = next(i["manifest"] for i in extensions.discover() if i["ok"])
    with pytest.raises(ValueError, match="not integer"):
        extensions.call(cfg, found, "wrong", {}, set())
    monkeypatch.setattr(extensions, "TIMEOUT", 1)
    with pytest.raises(ValueError, match="longer than 1 seconds"):
        extensions.call(cfg, found, "slow", {}, set())


@pytest.fixture(autouse=True)
def _remove_extension_skills():
    yield
    for name in [n for n in skills.SKILLS if n.startswith("ext_")]:
        del skills.SKILLS[name]
