"""Exercise every HUD control against a real Jarvis server and verify its actual result.

Model, voice and image services are stubbed, so this checks the HUD, the HTTP API and the
app state, not model quality. Run:  python -m scripts.hud_control_audit
Writes hud-captures/control-report.md and screenshots. Exits 1 if any check fails.
"""
import base64
import io
import json
import os
import socket
import sys
import tempfile
import threading
import time
import traceback
from pathlib import Path
from unittest.mock import MagicMock, patch

from PIL import Image
from playwright.sync_api import expect, sync_playwright

from jarvis import config, memory, net, nomad, setupwizard, webui
from jarvis.__main__ import App

OUT = Path("hud-captures")
RESULTS = []


def check(control, action, expected):
    """Decorator-style runner: record pass or fail with the observed result."""
    def run(fn):
        started = time.perf_counter()
        try:
            observed = fn() or "as expected"
            RESULTS.append((control, action, expected, "PASS", str(observed)))
        except Exception as error:  # recorded, the audit continues
            detail = f"{type(error).__name__}: {(str(error).splitlines() or [''])[0][:200]}"
            RESULTS.append((control, action, expected, "FAIL", detail))
            traceback.print_exc()
        finally:
            print(f"{RESULTS[-1][3]} {control}: {action} ({time.perf_counter() - started:.1f}s)")
    return run


def until(condition, timeout=5.0, message="condition not met"):
    """Wait for app state changed by an asynchronous HUD request."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.05)
    raise AssertionError(message)


def png():
    buffer = io.BytesIO()
    Image.new("RGB", (64, 48), "#3366aa").save(buffer, "PNG")
    return buffer.getvalue()


def last_reply(page):
    return page.locator("#log .jarvis").last


def build(home):
    reading = home / "reading"
    reading.mkdir()
    (reading / "navigation.txt").write_text("Check the compass before departure.", encoding="utf-8")
    code = home / "code"
    (code / "budget").mkdir(parents=True)
    (code / "budget" / "budget.py").write_text("def total(values):\n    return sum(values) / len(values)\n")
    (code / "budget" / "test_budget.py").write_text("def test_ok():\n    assert True\n")
    (code / "notes.txt").write_text("workspace note")
    files = home / "Downloads"
    (files / "Trips").mkdir(parents=True)
    for name, data in (("holiday.jpg", b"jpg"), ("receipt.pdf", b"pdf"), ("podcast.mp3", b"mp3")):
        (files / name).write_bytes(data)
    cfg = dict(config.DEFAULTS, code_dir=str(code), speak_replies=False, document_folders=[str(reading)],
               file_folders=[str(files)], image_generation_url="http://127.0.0.1:7860")
    app = App(cfg, use_voice=False)
    app.brain.embed = lambda text: None
    gate = threading.Event()
    gate.set()

    def chat(messages, use_tools):
        text = messages[-1]["content"]
        if "slow" in text:
            for part in ("Working", " on it", " slowly"):
                app.brain.on_stream(part)
                time.sleep(0.6)
                if app.brain.cancelled.is_set():
                    from jarvis.brain import OllamaError
                    raise OllamaError("Stopped by the user.")
        if "You are answering as TUKI" in messages[0]["content"]:
            return {"content": "Two x.\nConfidence: high, power rule."}
        return {"content": "Of course."}

    app.brain._chat = chat
    app.brain.raw_chat = lambda messages, model: (
        "FILE: budget/budget.py\n<<<<<<< SEARCH\n    return sum(values) / len(values)\n=======\n"
        "    if not values:\n        return 0\n    return sum(values) / len(values)\n>>>>>>> REPLACE\n")
    app.speaker = MagicMock()
    app.speaker.describe.side_effect = lambda who: "Windows voice Microsoft " + ("Zira" if who == "tuki" else "George")
    app.image_operation = lambda kind, data: (
        {"name": "generated.png", "image": base64.b64encode(png()).decode()} if kind == "generate"
        else {"text": "A plain blue rectangle."})
    return app, cfg, code, files


def audit(app, cfg, code, files, url):
    with sync_playwright() as playwright:
        # Chrome's screen-share picker is auto-answered here, which a real user does by hand.
        browser = playwright.chromium.launch(
            executable_path=os.environ.get("JARVIS_CHROME") or None,
            args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                  "--auto-accept-this-tab-capture"])
        page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce")
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        answers = {"accept": True}
        dialogs = []

        def on_dialog(dialog):
            dialogs.append(dialog.message)
            dialog.accept() if answers["accept"] else dialog.dismiss()

        page.on("dialog", on_dialog)
        page.goto(url)
        page.wait_for_function("typeof es !== 'undefined' && es.readyState === EventSource.OPEN")

        # ---------------------------------------------------------------- setup wizard
        @check("Setup wizard", "opens on first run", "dialog visible with prerequisites and a download plan")
        def _():
            expect(page.locator("#wizard")).to_be_visible()
            expect(page.locator("#wizard-plan tr").first).to_be_visible()
            return f"{page.locator('#wizard-plan tr').count()} planned downloads"

        @check("Wizard profile and budget", "choose 8 GB and a 1 GB budget", "plan switches models and warns over budget")
        def _():
            page.locator("input[name=wizard-profile][value=low-memory]").check()
            page.locator("#wizard-budget").fill("1")
            page.locator("#wizard-budget").dispatch_event("change")
            expect(page.locator("#wizard-plan")).to_contain_text("qwen2.5-coder:1.5b")
            expect(page.locator("#wizard-warnings")).to_contain_text("budget")
            page.screenshot(path=OUT / "audit-wizard.png")

        @check("Wizard Download and finish", "start over budget, decline the warning", "nothing starts, state unchanged")
        def _():
            answers["accept"] = False
            seen = len(dialogs)
            page.get_by_role("button", name="Download and finish").click()
            page.wait_for_timeout(500)
            answers["accept"] = True
            assert len(dialogs) == seen + 1 and "budget" in dialogs[-1], "no budget warning dialog"
            assert not setupwizard.load_state().get("steps"), "downloads started"

        @check("Wizard Download and finish", "start with stubbed downloads", "all steps done, setup marked complete")
        def _():
            page.locator("#wizard-budget").fill("")
            page.locator("#wizard-voice").uncheck()
            with patch.object(setupwizard, "_pull_ollama", lambda cfg, name, progress: progress(1, 1)), \
                    patch.object(setupwizard, "installed_ollama", lambda cfg: {}):
                page.get_by_role("button", name="Download and finish").click()
                expect(page.locator("#wizard-status")).to_have_text("Setup finished.", timeout=8000)
            assert app.cfg["setup_complete"] is True and app.cfg["performance_profile"] == "low-memory"
            assert json.loads(config.CONFIG_PATH.read_text())["setup_complete"] is True
            return "state: " + ", ".join(s["status"] for s in setupwizard.load_state()["steps"])

        @check("Wizard Close", "click Close", "dialog closes and stays closed after reload")
        def _():
            page.get_by_role("button", name="Close", exact=True).click()
            expect(page.locator("#wizard")).to_be_hidden()
            page.reload()
            page.wait_for_function("es.readyState === EventSource.OPEN")
            page.wait_for_timeout(400)
            expect(page.locator("#wizard")).to_be_hidden()

        @check("Compact view", "toggle, reload, return to full view", "view is saved without changing assistant mode")
        def _():
            mode = app.cfg["mode"]
            page.locator("#compact-view").click()
            expect(page.locator("body")).to_have_attribute("data-compact", "true")
            expect(page.locator(".col.left")).to_be_hidden()
            page.reload()
            page.wait_for_function("es.readyState === EventSource.OPEN")
            expect(page.locator("body")).to_have_attribute("data-compact", "true")
            page.locator("#compact-view").click()
            assert app.cfg["mode"] == mode

        @check("Local provider settings", "save local settings, reject remote URL, restore Ollama", "explicit local model shown and no remote configuration accepted")
        def _():
            page.locator("#setup-panel summary").first.click()
            page.locator("#provider-load").click()
            expect(page.locator("#provider-status")).to_contain_text("ollama")
            page.locator("#chat-provider").select_option("openai_local")
            page.locator("#local-chat-url").fill("http://127.0.0.1:8081")
            page.locator("#local-chat-model").fill("audit-local-model")
            page.locator("#provider-form button").first.click()
            expect(page.locator("#provider-status")).to_contain_text("openai_local")
            assert cfg["chat_provider"] == "openai_local"
            page.locator("#local-chat-url").fill("https://remote.invalid")
            page.locator("#provider-form button").first.click()
            expect(page.locator("#provider-status")).to_contain_text("127.0.0.1")
            assert cfg["local_chat_url"] == "http://127.0.0.1:8081"
            page.locator("#local-chat-url").fill("http://127.0.0.1:8081")
            page.locator("#chat-provider").select_option("ollama")
            page.locator("#provider-form button").first.click()
            expect(page.locator("#provider-status")).to_contain_text("ollama")
            page.locator("#setup-panel summary").first.click()

        @check("Workspace views", "Command Center and Ambient, then Classic", "shared settings and no private text in Ambient")
        def _():
            mode, theme = cfg["mode"], cfg["theme"]
            page.locator("#workspace_view").select_option("command")
            expect(page.locator("body")).to_have_attribute("data-view", "command")
            expect(page.locator("#command-nav")).to_be_visible()
            page.locator("#command-nav button[data-panel=workflows]").click()
            assert page.locator("#workflows").evaluate("e => e.open")
            page.locator("#workflows summary").first.click()
            page.screenshot(path=OUT / "audit-phase2-command.png")
            page.locator("#compact-view").click()
            page.locator("#workspace_view").select_option("ambient")
            expect(page.locator(".app")).to_be_hidden()
            expect(page.locator("#ambient-view")).to_be_visible()
            page.evaluate("setPending({id:'private-preview',text:'PRIVATE ACCOUNT DETAILS'})")
            expect(page.locator("#ambient-pending")).to_contain_text("Open controls")
            assert "PRIVATE" not in page.locator("#ambient-view").inner_text()
            page.locator("#ambient-clock-toggle").click()
            expect(page.locator("#ambient-clock")).to_be_hidden()
            page.locator("#ambient-clock-toggle").click()
            page.screenshot(path=OUT / "audit-phase2-ambient.png")
            page.locator("#ambient-controls").click()
            expect(page.locator("body")).to_have_attribute("data-view", "command")
            page.locator("#compact-view").click()
            page.locator("#workspace_view").select_option("classic")
            expect(page.locator("body")).to_have_attribute("data-view", "classic")
            page.evaluate("setPending(null)")
            assert cfg["mode"] == mode and cfg["theme"] == theme

        @check("Manual voice preview", "hold, release, review, copy to message, cancel", "transcript never submits itself")
        def _():
            import numpy as np
            from types import SimpleNamespace
            from jarvis import voice
            with patch.object(voice, "load_whisper", lambda cfg: SimpleNamespace(transcribe=lambda *a, **kw:
                    ([SimpleNamespace(text="review this transcript", no_speech_prob=0)], None))):
                app.listener = voice.Listener(cfg, None, lambda *a: (_ for _ in ()).throw(AssertionError("dictation executed")), app.emit)
            try:
                page.evaluate("api('/api/state').then(setToggles)")
                page.locator("#voice_input_mode").select_option("manual")
                until(lambda: cfg["voice_input_mode"] == "manual")
                count = page.locator("#log .user").count()
                button = page.locator("#record-voice")
                button.hover()
                page.mouse.down()
                until(lambda: app.listener._manual is not None)
                app.listener._receive(np.ones((16000, 1), dtype="float32"))
                page.mouse.up()
                expect(page.locator("#dictation-text")).to_have_value("review this transcript")
                assert page.locator("#log .user").count() == count
                page.locator("#dictation-use").click()
                expect(page.locator("#q")).to_have_value("review this transcript")
                assert page.locator("#log .user").count() == count
                page.locator("#q").fill("")
                page.keyboard.down("Control")
                page.keyboard.down("Shift")
                page.keyboard.down("Space")
                until(lambda: app.listener._manual is not None)
                page.keyboard.press("Escape")
                page.keyboard.up("Space")
                page.keyboard.up("Shift")
                page.keyboard.up("Control")
                until(lambda: app.listener._manual is None)
                expect(page.locator("#dictation")).to_be_hidden()
            finally:
                app.listener.cancel_manual()
                app.listener = None
                page.evaluate("api('/api/state').then(setToggles)")

        @check("Local workflows", "save, preview, run, export and delete", "real calculation result and persisted completion")
        def _():
            page.locator("#workflows summary").first.click()
            page.locator("#workflow-name").fill("Audit calculation")
            page.locator("#workflow-kind").select_option("calculate")
            page.locator("#workflow-value").fill("12 * 3")
            page.locator("#workflow-add-step").click()
            page.locator("#workflow-create button").last.click()
            expect(page.locator("#workflow-list")).to_contain_text("Audit calculation")
            answers["accept"] = False
            page.get_by_role("button", name="Review and run", exact=True).click()
            assert not app.workflows_operation()["runs"]
            answers["accept"] = True
            page.get_by_role("button", name="Review and run", exact=True).click()
            expect(page.locator("#workflow-runs")).to_contain_text("completed (1/1 steps)")
            page.locator("#workflow-runs summary").click()
            expect(page.locator("#workflow-runs pre")).to_contain_text("12 * 3 = 36")
            with page.expect_download() as downloaded:
                page.get_by_role("button", name="Export results", exact=True).click()
            assert downloaded.value.suggested_filename.startswith("Jarvis-Workflow-")
            page.get_by_role("button", name="Delete results", exact=True).click()
            expect(page.locator("#workflow-runs")).to_be_empty()
            page.get_by_role("button", name="Delete workflow", exact=True).click()
            expect(page.locator("#workflow-list")).to_be_empty()
            page.locator("#workflows summary").first.click()

        @check("RSS and Atom feed", "preview, cancel, then approve a fixture feed", "no fetch before approval and source-attributed output")
        def _():
            cfg['allow_internet_tools'] = True
            page.evaluate("api('/api/state').then(setToggles)")
            page.locator('#read-feed').click()
            expect(page.locator('#q')).to_have_value('/feed ')
            body = '<rss><channel><title>Audit feed</title><item><title>Review event</title><link>https://example.org/event</link></item></channel></rss>'
            try:
                with patch.object(net, 'read_public_page', return_value=(body, 'application/rss+xml')) as read:
                    send(page, '/feed https://example.org/feed')
                    expect(page.locator('#pending')).to_have_class('on')
                    assert read.call_count == 0
                    page.locator('#p-no').click()
                    expect(last_reply(page)).to_contain_text('Cancelled')
                    assert read.call_count == 0
                    send(page, '/feed https://example.org/feed')
                    expect(page.locator('#pending')).to_have_class('on')
                    page.locator('#p-yes').click()
                    expect(last_reply(page)).to_contain_text('Review event')
                    assert read.call_count == 1
            finally:
                cfg['allow_internet_tools'] = False
                page.evaluate("api('/api/state').then(setToggles)")

        @check("US weather forecast", "approve coordinates with NWS fixtures", "exact coordinates reviewed and real response fields displayed")
        def _():
            cfg['allow_internet_tools'] = True
            page.evaluate("api('/api/state').then(setToggles)")
            page.locator('#read-weather').click()
            expect(page.locator('#q')).to_have_value('/weather ')
            url='https://api.weather.gov/gridpoints/PSR/159,76/forecast'
            responses=[(json.dumps({'properties':{'forecast':url}}),'application/geo+json'),
                       (json.dumps({'properties':{'updated':'2026-11-27T12:00:00Z','periods':[{
                           'name':'Afternoon','startTime':'2026-11-27T12:00:00-07:00','temperature':72,
                           'temperatureUnit':'F','shortForecast':'Sunny','windSpeed':'5 mph','windDirection':'NE'}]}}),'application/geo+json')]
            try:
                with patch.object(net, 'read_public_page', side_effect=responses) as read:
                    send(page, '/weather 33.49,-111.92')
                    expect(page.locator('#pending')).to_have_class('on')
                    expect(page.locator('#pending-text')).to_contain_text('33.4900, -111.9200')
                    assert read.call_count == 0
                    page.locator('#p-yes').click()
                    expect(last_reply(page)).to_contain_text('72 F')
                    assert read.call_count == 2
            finally:
                cfg['allow_internet_tools'] = False
                page.evaluate("api('/api/state').then(setToggles)")

        # ---------------------------------------------------------------- header controls
        @check("Mode menu", "select each mode", "body, app state and saved config change; Talk hides tools")
        def _():
            for mode in ("coding", "briefing", "talk", "everyday"):
                page.locator("#mode").select_option(mode)
                expect(page.locator("body")).to_have_attribute("data-mode", mode)
                until(lambda: app.cfg["mode"] == mode and json.loads(config.CONFIG_PATH.read_text())["mode"] == mode,
                      message=f"mode {mode} not saved")
                if mode == "talk":
                    expect(page.locator("#planner")).to_be_hidden()

        @check("Assistant menu", "select TUKI, Jarvis, Auto", "saved and used for the next reply")
        def _():
            page.locator("#assistant").select_option("tuki")
            until(lambda: app.cfg["assistant"] == "tuki")
            send(page, "derivative of x squared")
            expect(last_reply(page)).to_contain_text("Checked with")
            expect(page.locator("#log .jarvis .via").last).to_contain_text("TUKI")
            page.locator("#assistant").select_option("auto")
            until(lambda: app.cfg["assistant"] == "auto")

        @check("Theme menu", "select all six themes, reload", "theme applied and kept after reload")
        def _():
            for theme in config.THEMES:
                page.locator("#theme").select_option(theme)
                expect(page.locator("body")).to_have_attribute("data-theme", theme)
            page.reload()
            page.wait_for_function("es.readyState === EventSource.OPEN")
            expect(page.locator("body")).to_have_attribute("data-theme", config.THEMES[-1])
            expect(page.locator("#theme")).to_have_value(config.THEMES[-1])
            page.locator("#theme").select_option("simple")

        @check("Voice menu", "Piper option without a Piper model", "Piper disabled; Windows selection saved")
        def _():
            assert page.evaluate("document.querySelector('#voice_choice option[value=piper]').disabled")
            assert page.evaluate("document.querySelector('#tuki_voice_choice option[value=piper]').disabled")
            page.locator("#voice_choice").select_option("windows")
            page.locator("#tuki_voice_choice").select_option("windows")
            until(lambda: app.cfg["voice_choice"] == "windows" and app.cfg["tuki_voice_choice"] == "windows")

        @check("Try voice / Try TUKI voice", "click both", "each assistant speaks with its own reported voice")
        def _():
            page.get_by_role("button", name="Try voice", exact=True).click()
            expect(page.locator("#log .system").last).to_contain_text("George")
            page.get_by_role("button", name="Try TUKI voice").click()
            expect(page.locator("#log .system").last).to_contain_text("Zira")
            until(lambda: [c.args[1] for c in app.speaker.say.call_args_list[-2:]] == ["jarvis", "tuki"])

        @check("Voice toggle", "click twice", "speak_replies flips, aria-pressed matches, saved")
        def _():
            before = app.cfg["speak_replies"]
            page.locator("#t-speak").click()
            expect(page.locator("#t-speak")).to_have_attribute("aria-pressed", str(not before).lower())
            until(lambda: app.cfg["speak_replies"] is (not before))
            page.locator("#t-speak").click()
            until(lambda: app.cfg["speak_replies"] is before)

        @check("Mic toggle", "without a microphone", "disabled with an explanation")
        def _():
            expect(page.locator("#t-mic")).to_be_disabled()
            return page.locator("#t-mic").get_attribute("title")

        @check("Internet toggle", "click twice", "allow_internet_tools flips and the label says on/off")
        def _():
            page.locator("#t-internet").click()
            expect(page.locator("#t-internet")).to_have_text("Internet on")
            assert app.cfg["allow_internet_tools"] is True
            page.locator("#t-internet").click()
            expect(page.locator("#t-internet")).to_have_text("Internet off")
            assert app.cfg["allow_internet_tools"] is False

        @check("Lockdown toggle", "turn on, try a risky command, turn off", "risky actions blocked while on")
        def _():
            page.locator("#t-lock").click()
            expect(page.locator("#t-lock")).to_have_text("Lockdown ON")
            send(page, "/copy notes.txt | copy-locked.txt")
            expect(last_reply(page)).to_contain_text("Lockdown")
            assert not (code / "copy-locked.txt").exists()
            page.locator("#t-lock").click()
            expect(page.locator("#t-lock")).to_have_text("Lockdown")
            assert app.cfg["lockdown"] is False

        # ---------------------------------------------------------------- chat
        @check("Message box and Send", "type and press Enter", "user message and reply appear, box clears")
        def _():
            count = page.locator("#log .jarvis").count()
            send(page, "hello there")
            expect(page.locator("#log .jarvis")).to_have_count(count + 1)
            text = last_reply(page).inner_text()
            assert text.endswith("Of course."), text
            expect(page.locator("#q")).to_have_value("")

        @check("Stop button", "stop a streaming reply", "stream cleared, reply cancelled, status idle")
        def _():
            page.locator("#q").fill("please answer slow")
            page.locator("#q").press("Enter")
            expect(page.locator("#stream-draft")).to_be_visible()
            page.get_by_role("button", name="Stop", exact=True).click()
            expect(page.locator("#stream-draft")).to_be_hidden(timeout=5000)
            expect(page.locator("#log").locator("text=Stopped").last).to_be_visible(timeout=5000)
            assert app._turn_lock.acquire(timeout=3)
            app._turn_lock.release()

        @check("Escape key", "press Escape during a reply", "same as Stop")
        def _():
            page.locator("#q").fill("another slow one")
            page.locator("#q").press("Enter")
            expect(page.locator("#stream-draft")).to_be_visible()
            page.keyboard.press("Escape")
            expect(page.locator("#stream-draft")).to_be_hidden(timeout=5000)
            assert app._turn_lock.acquire(timeout=3)
            app._turn_lock.release()

        @check("Busy guard", "send while a reply runs", "second message refused, typed text kept")
        def _():
            page.locator("#q").fill("slow third")
            page.locator("#q").press("Enter")
            expect(page.locator("#stream-draft")).to_be_visible()
            page.locator("#q").fill("queued text")
            page.locator("#q").press("Enter")
            expect(page.locator("#log .system").last).to_contain_text("working")
            expect(page.locator("#q")).to_have_value("queued text")
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)
            page.locator("#q").fill("")

        @check("Read briefing", "Briefing mode, click", "briefing reply appears")
        def _():
            page.locator("#mode").select_option("briefing")
            page.get_by_role("button", name="Read briefing").click()
            expect(last_reply(page)).not_to_have_text("Of course.")
            text = last_reply(page).inner_text()
            page.locator("#mode").select_option("everyday")
            return text[:80]

        @check("Calculate / Find a file", "TUKI buttons fill commands; run /calc", "command prefilled; result 2.5")
        def _():
            page.locator("#assistant").select_option("tuki")
            page.get_by_role("button", name="Calculate").click()
            expect(page.locator("#q")).to_have_value("/calc ")
            page.locator("#q").fill("/calc 10 / 4")
            page.locator("#q").press("Enter")
            expect(last_reply(page)).to_contain_text("2.5")
            page.get_by_role("button", name="Find a file").click()
            expect(page.locator("#q")).to_have_value("/files ")
            page.locator("#q").fill("")
            page.locator("#assistant").select_option("auto")

        @check("Copy file + Confirm", "/copy in Jarvis Code then Confirm", "banner shows plan; copy created")
        def _():
            page.get_by_role("button", name="Copy file").click()
            expect(page.locator("#q")).to_have_value("/copy ")
            page.locator("#q").fill("/copy notes.txt | notes copy.txt")
            page.locator("#q").press("Enter")
            expect(page.locator("#pending")).to_be_visible()
            page.locator("#p-yes").click()
            expect(last_reply(page)).to_contain_text("Finished copy")
            assert (code / "notes copy.txt").read_text() == "workspace note"

        @check("Move file + Cancel", "/move then Cancel", "nothing moved")
        def _():
            page.get_by_role("button", name="Move file").click()
            page.locator("#q").fill("/move notes.txt | moved.txt")
            page.locator("#q").press("Enter")
            expect(page.locator("#pending")).to_be_visible()
            page.locator("#p-no").click()
            expect(last_reply(page)).to_contain_text("Cancelled")
            assert (code / "notes.txt").exists() and not (code / "moved.txt").exists()

        @check("File task history", "click", "lists the copy job")
        def _():
            page.get_by_role("button", name="File task history").click()
            expect(last_reply(page)).to_contain_text("done copy notes.txt")

        @check("Read source page", "click", "prefills /read; offline request explains")
        def _():
            page.get_by_role("button", name="Read source page").click()
            expect(page.locator("#q")).to_have_value("/read ")
            page.locator("#q").fill("/read https://example.org | claim")
            page.locator("#q").press("Enter")
            expect(last_reply(page)).to_contain_text("off")

        @check("Web search / Upload buttons", "without keys", "hidden")
        def _():
            expect(page.locator("#web-search")).to_be_hidden()
            expect(page.locator("#upload-file")).to_be_hidden()

        # ---------------------------------------------------------------- coding
        @check("Propose fix / Show diff / Apply / Undo", "full coding cycle", "diff shown, file changed, then restored")
        def _():
            page.locator("#mode").select_option("coding")
            original = (code / "budget" / "budget.py").read_text()
            page.get_by_role("button", name="Propose fix").click()
            page.locator("#q").fill("/fix budget/budget.py | handle empty input")
            page.locator("#q").press("Enter")
            expect(last_reply(page)).to_contain_text("+    if not values:")
            page.get_by_role("button", name="Show diff").click()
            expect(last_reply(page)).to_contain_text("Proposed edit for budget/budget.py")
            page.screenshot(path=OUT / "audit-coding.png")
            page.get_by_role("button", name="Apply proposal").click()
            expect(last_reply(page)).to_contain_text("Updated budget.py")
            assert "if not values" in (code / "budget" / "budget.py").read_text()
            page.get_by_role("button", name="Undo last edit").click()
            expect(last_reply(page)).to_contain_text("Restored")
            assert (code / "budget" / "budget.py").read_text() == original

        @check("Run project tests", "/test then Cancel", "exact command shown, nothing runs on Cancel")
        def _():
            page.get_by_role("button", name="Run project tests").click()
            expect(page.locator("#q")).to_have_value("/test ")
            with patch("jarvis.coder._run_in_job") as runner:
                page.locator("#q").fill("/test budget/budget.py")
                page.locator("#q").press("Enter")
                expect(page.locator("#pending-text")).to_contain_text("run the project tests")
                page.locator("#p-no").click()
                expect(last_reply(page)).to_contain_text("Cancelled")
                runner.assert_not_called()

        @check("Build project", "/build then Confirm", "exact compileall command shown, then build result")
        def _():
            page.get_by_role("button", name="Build project").click()
            expect(page.locator("#q")).to_have_value("/build ")
            page.locator("#q").fill("/build budget/budget.py")
            page.locator("#q").press("Enter")
            expect(page.locator("#pending-text")).to_contain_text("compileall")
            page.locator("#p-yes").click()
            expect(last_reply(page)).to_contain_text("Build passed")
            assert list((code / "budget").rglob("*.pyc")), "nothing was compiled"

        @check("Undo after restart", "apply, restart the brain, Undo", "edit restored from the saved journal")
        def _():
            from jarvis.brain import Brain
            original = (code / "budget" / "budget.py").read_text()
            send(page, "/fix budget/budget.py | handle empty input")
            expect(last_reply(page)).to_contain_text("Preview only")
            page.get_by_role("button", name="Apply proposal").click()
            expect(last_reply(page)).to_contain_text("Updated budget.py")
            restarted = Brain(app.cfg, app.memory)
            restarted.raw_chat = app.brain.raw_chat
            assert "Restored" in restarted.ask("/undo")
            assert (code / "budget" / "budget.py").read_text() == original
            page.locator("#mode").select_option("everyday")

        # ---------------------------------------------------------------- planner
        @check("Planner: Add task / Open tasks / Plan my week / View week", "add a task and plan",
               "task stored, plan made, deadline listed")
        def _():
            page.locator("#planner summary").click()
            page.get_by_label("Task", exact=True).fill("Audit lab report")
            page.get_by_label("Minutes (optional)").fill("60")
            page.get_by_role("button", name="Add task").click()
            expect(last_reply(page)).to_contain_text("Task added: Audit lab report")
            page.get_by_role("button", name="Open tasks").click()
            expect(last_reply(page)).to_contain_text("Audit lab report")
            page.get_by_role("button", name="Plan my week").click()
            expect(last_reply(page)).to_contain_text("seven days")
            page.get_by_role("button", name="View week").click()
            expect(last_reply(page)).not_to_have_text("")

        # ---------------------------------------------------------------- documents and memory
        @check("Documents: search", "search 'compass'", "cites navigation.txt")
        def _():
            page.locator("#knowledge summary").click()
            page.locator("#document-query").fill("compass")
            page.get_by_role("button", name="Search documents").click()
            expect(last_reply(page)).to_contain_text("navigation.txt")

        @check("Documents: local research", "research selected documents", "model summary and original source shown")
        def _():
            page.locator("#document-query").fill("compass")
            page.get_by_role("button", name="Research selected docs").click()
            expect(last_reply(page)).to_contain_text("Local document research")
            expect(last_reply(page)).to_contain_text("navigation.txt")

        @check("Memory: review, edit, export, delete", "full cycle", "edit stored, export downloads, delete removes")
        def _():
            app.memory.remember("I prefer morning study")
            page.get_by_role("button", name="Review remembered facts").click()
            field = page.locator("#memory-list textarea").first
            field.fill("I prefer evening study")
            page.get_by_role("button", name="Save memory").click()
            expect(page.locator("#memory-status")).to_contain_text("Remembered facts")
            assert app.memory.all_facts()[0][1] == "I prefer evening study"
            with page.expect_download() as download:
                page.get_by_role("button", name="Export remembered facts").click()
            assert "evening" in Path(download.value.path()).read_text()
            page.get_by_role("button", name="Back up local data").click()
            expect(page.locator("#backup-status")).to_contain_text("Saved")
            answers["accept"] = False
            page.get_by_role("button", name="Delete memory").click()
            page.wait_for_timeout(300)
            answers["accept"] = True
            assert "Delete this remembered fact" in dialogs[-1] and app.memory.all_facts(), "declined delete ran"
            page.get_by_role("button", name="Delete memory").click()
            expect(page.locator("#memory-status")).to_have_text("No remembered facts.")
            assert not app.memory.all_facts()

        @check("Backups: review and restore", "restore the backup", "deleted fact returns")
        def _():
            page.get_by_role("button", name="Review backups").click()
            expect(page.locator("#backup-name option").first).to_be_attached()
            seen = len(dialogs)
            page.get_by_role("button", name="Restore backup", exact=True).click()
            expect(page.locator("#backup-status")).to_contain_text("Restored")
            assert len(dialogs) == seen + 1 and "rescue backup" in dialogs[-1], "no confirmation dialog"
            assert app.memory.all_facts()[0][1] == "I prefer evening study"

        @check("Clear conversation history", "click and confirm", "history emptied")
        def _():
            seen = len(dialogs)
            page.get_by_role("button", name="Clear conversation history").click()
            expect(page.locator("#memory-status")).to_have_text("Conversation history cleared.")
            assert len(dialogs) == seen + 1, "no confirmation dialog"
            assert not app.brain.history

        # ---------------------------------------------------------------- setup panel
        @check("Setup: load and save", "load, change profile, save", "profile saved to config")
        def _():
            page.locator("#setup-panel summary").click()
            page.get_by_role("button", name="Load current setup").click()
            expect(page.locator("#setup-profile")).to_have_value("low-memory")
            page.locator("#setup-profile").select_option("standard")
            page.locator("#setup-form button").click()
            expect(page.locator("#setup-status")).to_contain_text("Saved")
            assert json.loads(config.CONFIG_PATH.read_text())["performance_profile"] == "standard"

        @check("Setup: Open setup wizard", "click", "wizard reopens with saved values")
        def _():
            page.get_by_role("button", name="Open setup wizard").click()
            expect(page.locator("#wizard")).to_be_visible()
            expect(page.locator("input[name=wizard-profile][value=standard]")).to_be_checked()
            page.get_by_role("button", name="Close", exact=True).click()

        # ---------------------------------------------------------------- file tasks
        @check("File tasks: browse, open folder, up, find", "navigate", "listing and search results correct")
        def _():
            page.locator("#file-tasks summary").click()
            expect(page.locator("#ft-items")).to_contain_text("holiday.jpg")
            page.locator("#ft-items").get_by_role("button", name="Trips").click()
            expect(page.locator("#ft-path")).to_contain_text("Trips")
            page.get_by_role("button", name="Up one level").click()
            expect(page.locator("#ft-path")).to_contain_text("top")
            page.locator("#ft-search").fill("podcast")
            page.get_by_role("button", name="Find", exact=True).click()
            expect(page.locator("#ft-status")).to_contain_text("1 matches")

        def file_task(action, value="", select=(), done=lambda: True):
            page.locator("#ft-search").fill("")
            page.get_by_role("button", name="Find", exact=True).click()
            for name in select:
                page.get_by_label("Select " + name).check()
            page.locator("#ft-action").select_option(action)
            if value:
                page.locator("#ft-value").fill(value)
            page.get_by_role("button", name="Preview changes").click()
            expect(page.locator("#pending")).to_be_visible()
            preview = page.locator("#ft-preview").inner_text()
            page.locator("#p-yes").click()
            until(done, message=f"{action} did not change the files")
            expect(page.locator("#pending")).to_be_hidden()
            return preview

        @check("File tasks: create folder", "Create folder 'Archive'", "folder exists")
        def _():
            preview = file_task("mkdir", "Archive", done=lambda: (files / "Archive").is_dir())
            assert (files / "Archive").is_dir()
            return preview

        @check("File tasks: rename", "rename receipt.pdf", "file renamed")
        def _():
            file_task("rename", "receipt 2026.pdf", ["receipt.pdf"], done=lambda: (files / "receipt 2026.pdf").exists())
            assert (files / "receipt 2026.pdf").exists() and not (files / "receipt.pdf").exists()

        @check("File tasks: copy and move", "copy then move into Archive", "files in Archive")
        def _():
            file_task("copy", "Archive", ["podcast.mp3"], done=lambda: (files / "Archive" / "podcast.mp3").exists())
            file_task("move", "Archive", ["holiday.jpg"], done=lambda: (files / "Archive" / "holiday.jpg").exists())
            assert (files / "Archive" / "podcast.mp3").exists() and (files / "podcast.mp3").exists()
            assert (files / "Archive" / "holiday.jpg").exists() and not (files / "holiday.jpg").exists()

        @check("File tasks: delete", "delete podcast.mp3", "moved to .Jarvis Recycle")
        def _():
            file_task("delete", "", ["podcast.mp3"], done=lambda: not (files / "podcast.mp3").exists())
            assert not (files / "podcast.mp3").exists() and list((files / ".Jarvis Recycle").rglob("podcast.mp3"))

        @check("File tasks: history Undo", "undo the delete", "file restored")
        def _():
            page.get_by_role("button", name="Show task history").click()
            page.locator("#ft-history").get_by_role("button", name="Undo").first.click()
            expect(page.locator("#pending")).to_be_visible()
            page.locator("#p-yes").click()
            expect(last_reply(page)).to_contain_text("undone")
            assert (files / "podcast.mp3").exists()
            page.screenshot(path=OUT / "audit-file-tasks.png")

        @check("File tasks: organise", "organise top folder", "files sorted by type")
        def _():
            file_task("organize", done=lambda: (files / "Audio" / "podcast.mp3").exists())
            assert (files / "Audio" / "podcast.mp3").exists()

        @check("File tasks: refused change", "rename to an existing name", "error shown, nothing changed")
        def _():
            page.locator("#ft-search").fill("")
            page.get_by_role("button", name="Find", exact=True).click()
            page.get_by_label("Select Trips").check()
            page.locator("#ft-action").select_option("rename")
            page.locator("#ft-value").fill("Archive")
            page.get_by_role("button", name="Preview changes").click()
            expect(page.locator("#ft-status")).to_contain_text("already exists")
            assert (files / "Trips").is_dir()

        # ---------------------------------------------------------------- images
        @check("Images: search button", "without Brave Search", "disabled with a reason")
        def _():
            page.locator("#images summary").click()
            expect(page.locator("#image-search-button")).to_be_disabled()
            return page.locator("#image-search-button").get_attribute("title")

        @check("Images: generate", "generate locally (stub)", "image and Download link shown")
        def _():
            page.locator("#image-prompt").fill("blue square")
            page.get_by_role("button", name="Generate locally").click()
            expect(page.get_by_role("link", name="Download PNG")).to_be_visible()

        @check("Images: describe", "choose a PNG and ask", "description shown")
        def _():
            image = OUT / "audit-sample.png"
            image.write_bytes(png())
            page.locator("#image-file").set_input_files(str(image))
            page.locator("#image-lookup button").click()
            expect(page.locator("#image-status")).to_contain_text("blue rectangle")

        # ---------------------------------------------------------------- screen
        @check("Screen: choose and ask", "share, preview, ask, discard", "one still shown before sending; answer from vision stub")
        def _():
            page.locator("#screen summary").click()
            expect(page.locator("#screen-ask")).to_be_hidden()
            page.get_by_role("button", name="Choose a window or screen").click()
            expect(page.locator("#screen-preview")).to_be_visible(timeout=10000)
            expect(page.locator("#screen-status")).to_contain_text("Sharing has stopped. Nothing has been sent")
            assert page.evaluate("document.querySelector('#screen-preview').naturalWidth") > 0
            page.locator("#screen-question").fill("What is shown?")
            page.get_by_role("button", name="Ask about this capture").click()
            expect(page.locator("#screen-answer")).to_have_text("A plain blue rectangle.")
            page.screenshot(path=OUT / "audit-screen.png")
            page.get_by_role("button", name="Discard capture").click()
            expect(page.locator("#screen-preview")).to_be_hidden()

        # ---------------------------------------------------------------- apps and extensions
        @check("App actions: refuse a shell", "add /bin/sh", "refused with a reason, nothing saved")
        def _():
            page.locator("#apps summary").click()
            page.locator("#apps-name").fill("Shell")
            page.locator("#apps-program").fill("/bin/sh")
            page.get_by_role("button", name="Add app action").click()
            expect(page.locator("#apps-status")).to_contain_text("can run any command")
            assert not app.cfg.get("app_actions")

        @check("App actions: add, run, stop, remove", "approve sleep, Confirm, Stop", "program starts, then is closed")
        def _():
            import shutil as _shutil
            program = _shutil.which("sleep")
            assert program, "needs a sleep program"
            page.locator("#apps-name").fill("Wait")
            page.locator("#apps-program").fill(program)
            page.get_by_role("button", name="Add app action").click()
            expect(page.locator("#apps-list")).to_contain_text("Wait")
            from jarvis import appactions as _apps
            with patch.object(_apps, "_command", lambda cfg, name, file="": ({"name": "Wait", "program": program}, [program, "30"])):
                page.get_by_role("button", name="Run Wait").click()
                expect(page.locator("#pending")).to_be_visible()
                page.locator("#p-yes").click()
                expect(last_reply(page)).to_contain_text("Started Wait.")
            until(lambda: _apps.running())
            page.screenshot(path=OUT / "audit-apps.png")
            expect(page.locator("#apps-stop")).to_be_enabled()
            page.get_by_role("button", name="Stop app actions").click()
            expect(page.locator("#apps-status")).to_contain_text("Closed Wait")
            assert not _apps.running()
            page.get_by_role("button", name="Remove Wait").click()
            expect(page.locator("#apps-list")).to_contain_text("No approved app actions")

        @check("Extensions: enable, run tests, disable", "example word-count", "skill registered, tests pass, removed")
        def _():
            import shutil as _shutil
            from jarvis import extensions as _ext, skills as _skills
            _shutil.copytree(Path(__file__).parents[1] / "docs" / "examples" / "extensions" / "word-count",
                             _ext.folder() / "word-count")
            page.locator("#apps summary").click()
            page.locator("#apps summary").click()
            expect(page.locator("#ext-list")).to_contain_text("Word count")
            page.get_by_role("button", name="Enable Word count").click()
            expect(page.locator("#ext-status")).to_have_text("Enabled.")
            assert "ext_word_count__count_words" in _skills.SKILLS
            page.get_by_role("button", name="Run tests for Word count").click()
            expect(page.locator("#ext-status")).to_contain_text("2 passed, 0 failed")
            page.get_by_role("button", name="Disable Word count").click()
            expect(page.locator("#ext-status")).to_have_text("Disabled.")
            assert "ext_word_count__count_words" not in _skills.SKILLS

        @check("Setup: OCR checkbox", "turn on and save", "ocr_enabled saved")
        def _():
            page.locator("#setup-panel summary").click()
            page.get_by_role("button", name="Load current setup").click()
            expect(page.locator("#setup-ocr-note")).not_to_have_text("")
            page.locator("#setup-ocr").check()
            page.locator("#setup-form button").click()
            expect(page.locator("#setup-status")).to_contain_text("Saved")
            until(lambda: json.loads(config.CONFIG_PATH.read_text()).get("ocr_enabled") is True)

        # ---------------------------------------------------------------- layout and connection
        @check("Phone layout", "390 px wide", "no sideways scrolling")
        def _():
            page.set_viewport_size({"width": 390, "height": 844})
            overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            page.screenshot(path=OUT / "audit-mobile.png")
            page.set_viewport_size({"width": 1440, "height": 900})
            assert overflow <= 1, f"{overflow}px"

        @check("Restart", "new App on the same settings", "theme, mode, assistant and profile kept")
        def _():
            restarted = config.load()
            for key, value in (("theme", app.cfg["theme"]), ("performance_profile", "standard"),
                               ("tuki_voice_choice", "windows"), ("setup_complete", True)):
                assert restarted[key] == value, f"{key}={restarted[key]}"

        assert not errors, errors
        browser.close()
        return page


def send(page, text):
    page.locator("#q").fill(text)
    page.locator("#q").press("Enter")
    expect(page.locator("#log .user").last).to_contain_text(text[:30])


def write_report():
    passed = sum(row[3] == "PASS" for row in RESULTS)
    lines = ["# HUD control report", "",
             "Generated by `python -m scripts.hud_control_audit` against a real Jarvis HUD server in Chromium.",
             "Model, voice and image services are stubbed. These results check controls, API calls, files and saved",
             "settings, not model quality or Windows audio.", "",
             f"**{passed} of {len(RESULTS)} checks passed.**", "",
             "| Control | Action | Expected result | Result | Observed |", "|---|---|---|---|---|"]
    for control, action, expected, status, observed in RESULTS:
        lines.append(f"| {control} | {action} | {expected} | {status} | {observed.replace('|', '/')[:160]} |")
    (OUT / "control-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return passed == len(RESULTS)


def main():
    OUT.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp, patch.object(App, "_watchdog"), \
            patch.object(nomad, "status", return_value={}):
        home = Path(tmp)
        with patch.object(config, "APP_DIR", home), patch.object(config, "CONFIG_PATH", home / "config.json"), \
                patch.object(memory, "APP_DIR", home), patch.object(memory, "DB_PATH", home / "memory.db"), \
                patch.object(setupwizard, "hf_cache_dir", lambda: home), \
                patch.object(setupwizard, "ollama_models_dir", lambda: home):
            from jarvis import recovery
            with patch.object(recovery, "BACKUP_DIR", home / "backups", create=True):
                app, cfg, code, files = build(home)
                with socket.socket() as probe:
                    probe.bind(("127.0.0.1", 0))
                    port = probe.getsockname()[1]
                server = webui.serve(app, port)
                try:
                    audit(app, cfg, code, files, f"http://127.0.0.1:{port}")
                except Exception:
                    traceback.print_exc()
                    RESULTS.append(("Audit run", "complete", "no page errors", "FAIL", "see log"))
                finally:
                    server.shutdown()
                    server.server_close()
    ok = write_report()
    print(f"{sum(r[3] == 'PASS' for r in RESULTS)}/{len(RESULTS)} passed. Report: {OUT / 'control-report.md'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
