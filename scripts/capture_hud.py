"""Capture the real HUD with synthetic data and stubbed model services."""
import base64
import datetime as dt
import io
import os
import socket
import tempfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw
from playwright.sync_api import expect, sync_playwright

from jarvis import config, memory, nomad, webui
from jarvis.__main__ import App

OUT = Path("hud-captures")


def artwork():
    image = Image.new("RGB", (420, 300), "#34486d")
    draw = ImageDraw.Draw(image)
    draw.ellipse((282, 30, 351, 99), fill="#f3d7a5")
    draw.polygon([(0, 250), (132, 106), (230, 204), (306, 144), (420, 255)], fill="#557391")
    draw.polygon([(0, 280), (117, 190), (205, 263), (341, 191), (420, 271), (420, 300), (0, 300)], fill="#143b49")
    buffer = io.BytesIO()
    image.save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


def capture(app, base_url):
    OUT.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=os.environ.get("JARVIS_CHROME") or None)
        page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce", device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base_url)
        # A new install opens the first-run setup wizard.
        expect(page.locator("#wizard")).to_be_visible()
        expect(page.locator("#wizard-plan tr").first).to_be_visible()
        page.screenshot(path=OUT / "setup-wizard.png")
        page.get_by_role("button", name="Close", exact=True).click()
        expect(page.locator("#wizard")).to_be_hidden()
        tiles = []
        for theme in ("contrast", "midnight", "paper"):
            page.locator("#theme").select_option(theme)
            expect(page.locator("body")).to_have_attribute("data-theme", theme)
            tiles.append(Image.open(io.BytesIO(page.screenshot())).resize((720, 450)))
        sheet = Image.new("RGB", (720 * 3, 450), "white")
        for number, tile in enumerate(tiles):
            sheet.paste(tile, (720 * number, 0))
        sheet.save(OUT / "themes.png")

        page.set_viewport_size({"width": 390, "height": 844})
        overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert overflow <= 1, f"mobile layout scrolls sideways by {overflow}px"
        page.screenshot(path=OUT / "mobile.png")
        page.set_viewport_size({"width": 1440, "height": 900})

        page.locator("#theme").select_option("midnight")
        page.get_by_role("button", name="Try TUKI voice").click()
        expect(page.locator("#log .system").last).to_contain_text("TUKI is using Windows voice Microsoft Zira")
        page.locator("#assistant").select_option("tuki")
        page.locator("#q").fill("What is the derivative of x squared?")
        page.locator("#q").press("Enter")
        expect(page.locator("#log .jarvis").last).to_contain_text("Checked with")
        page.screenshot(path=OUT / "tuki-voice.png")
        page.locator("#assistant").select_option("auto")

        page.locator("#theme").select_option("light")
        expect(page.locator("body")).to_have_attribute("data-theme", "light")
        page.locator("#mode").select_option("talk")
        expect(page.locator("body")).to_have_attribute("data-mode", "talk")
        page.locator("#q").fill("Help me plan a relaxed afternoon.")
        page.locator("#q").press("Enter")
        expect(page.get_by_text("Of course.")).to_be_visible()
        page.screenshot(path=OUT / "talk-light.png")

        page.locator("#mode").select_option("coding")
        expect(page.locator("body")).to_have_attribute("data-mode", "coding")
        page.locator("#theme").select_option("simple")
        expect(page.locator("body")).to_have_attribute("data-theme", "simple")
        page.locator("#q").fill("/fix budget.py | handle empty input and add a test")
        page.locator("#q").press("Enter")
        expect(page.get_by_text("Preview only.", exact=False)).to_be_visible()
        page.screenshot(path=OUT / "coding-diff.png")
        page.get_by_role("button", name="Apply proposal").click()
        expect(page.get_by_text("Updated budget.py, test_budget.py.", exact=False)).to_be_visible()

        page.locator("#mode").select_option("everyday")
        page.locator("#file-tasks summary").click()
        expect(page.locator("#ft-items")).to_contain_text("holiday.jpg")
        page.locator("#ft-action").select_option("organize")
        page.get_by_role("button", name="Preview changes").click()
        expect(page.locator("#ft-preview")).to_contain_text("Move holiday.jpg to Images/holiday.jpg")
        expect(page.locator("#pending")).to_be_visible()
        page.screenshot(path=OUT / "file-tasks.png")
        page.get_by_role("button", name="Confirm").click()
        expect(page.locator("#log .jarvis").last).to_contain_text("Finished")
        expect(page.locator("#ft-items")).to_contain_text("Images")
        page.get_by_role("button", name="Show task history").click()
        page.locator("#ft-history").get_by_role("button", name="Undo").click()
        page.get_by_role("button", name="Confirm").click()
        expect(page.locator("#log .jarvis").last).to_contain_text("File task undone")
        assert (Path(app.cfg["file_folders"][0]) / "holiday.jpg").exists()
        page.locator("#mode").select_option("coding")

        page.locator("#images summary").click()
        page.locator("#image-prompt").fill("Minimal mountain landscape at dusk")
        page.get_by_role("button", name="Generate locally").click()
        expect(page.get_by_role("link", name="Download PNG")).to_be_visible()
        page.screenshot(path=OUT / "image-tools.png")

        page.locator("#mode").select_option("briefing")
        page.locator("#theme").select_option("hud")
        expect(page.locator("body")).to_have_attribute("data-theme", "hud")
        page.reload()
        page.wait_for_function("es.readyState === EventSource.OPEN")
        page.locator("#planner summary").click()
        page.get_by_label("Task", exact=True).fill("Draft lab report")
        page.get_by_label("Due date (optional)").fill((dt.date.today() + dt.timedelta(days=2)).isoformat())
        page.get_by_label("Minutes (optional)").fill("60")
        page.get_by_role("button", name="Add task").click()
        expect(page.locator("#log .jarvis").last).to_contain_text("Task added: Draft lab report")
        page.get_by_role("button", name="Plan my week").click()
        expect(page.locator("#log .jarvis").last).to_contain_text("for the next seven days")
        expect(page.locator("#deadlines")).to_contain_text("Draft lab report")
        page.screenshot(path=OUT / "planner.png")
        page.get_by_role("button", name="View week").click()
        expect(page.locator("#log .jarvis").last).to_contain_text("DUE")
        page.locator("#knowledge summary").click()
        page.locator("#document-query").fill("compass")
        page.get_by_role("button", name="Search documents").click()
        expect(page.locator("#log .jarvis").last).to_contain_text("navigation.txt")
        app.memory.remember("I prefer morning study blocks")
        page.get_by_role("button", name="Review remembered facts").click()
        field = page.locator("#memory-list textarea").first
        expect(field).to_have_value("I prefer morning study blocks")
        field.fill("I prefer afternoon study blocks")
        page.get_by_role("button", name="Save memory").click()
        expect(page.locator("#memory-status")).to_contain_text("Remembered facts")
        expect(field).to_have_value("I prefer afternoon study blocks")
        page.get_by_role("button", name="Back up local data").click()
        expect(page.locator("#backup-status")).to_contain_text("Saved Jarvis")
        with page.expect_download() as download:
            page.get_by_role("button", name="Export remembered facts").click()
        assert download.value.suggested_filename == "Jarvis Memories.json"
        page.screenshot(path=OUT / "documents-memory.png")
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Delete memory").click()
        expect(page.locator("#memory-status")).to_have_text("No remembered facts.")
        assert not app.memory.all_facts()
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Restore backup", exact=True).click()
        expect(page.locator("#backup-status")).to_contain_text("Restored.")
        assert app.memory.all_facts()[0][1] == "I prefer afternoon study blocks"
        page.once("dialog", lambda dialog: dialog.accept())
        page.get_by_role("button", name="Clear conversation history").click()
        expect(page.locator("#memory-status")).to_have_text("Conversation history cleared.")
        assert not app.brain.history
        page.locator("#setup-panel summary").click()
        page.get_by_role("button", name="Load current setup").click()
        expect(page.locator("#setup-folders")).not_to_have_value("")
        page.locator("#setup-form button").click()
        expect(page.locator("#setup-status")).to_contain_text("Saved.")
        page.get_by_role("button", name="Stop", exact=True).click()
        page.screenshot(path=OUT / "setup-recovery.png")
        assert not errors, errors


def main():
    with tempfile.TemporaryDirectory() as tmp, patch.object(App, "_watchdog"), patch.object(nomad, "status", return_value={}):
        home = Path(tmp)
        reading = home / "reading"
        reading.mkdir()
        (reading / "navigation.txt").write_text("Check the compass before departure.", encoding="utf-8")
        code = home / "code"
        code.mkdir()
        (code / "budget.py").write_text("def total(values):\n    return sum(values) / len(values)\n", encoding="utf-8")
        files = home / "Downloads"
        files.mkdir()
        for name, data in (("holiday.jpg", b"jpg"), ("receipt.pdf", b"pdf"), ("podcast.mp3", b"mp3"), ("notes.txt", b"notes")):
            (files / name).write_bytes(data)
        cfg = dict(config.DEFAULTS, code_dir=str(code), speak_replies=False, document_folders=[str(reading)],
                   file_folders=[str(files)],
                   image_generation_url="http://127.0.0.1:7860")
        with patch.object(config, "APP_DIR", home), patch.object(config, "CONFIG_PATH", home / "config.json"), \
                patch.object(memory, "APP_DIR", home), patch.object(memory, "DB_PATH", home / "memory.db"):
            app = App(cfg, use_voice=False)
            app.brain.embed = lambda text: None
            app.brain.raw_chat = lambda messages, model: (
                "FILE: budget.py\n<<<<<<< SEARCH\n    return sum(values) / len(values)\n=======\n"
                "    if not values:\n        return 0\n    return sum(values) / len(values)\n>>>>>>> REPLACE\n"
                "FILE: test_budget.py\n<<<<<<< SEARCH\n=======\nfrom budget import total\n\n\n"
                "def test_empty():\n    assert total([]) == 0\n>>>>>>> REPLACE\n"
            )
            from unittest.mock import MagicMock
            app.speaker = MagicMock()
            app.speaker.describe.return_value = "Windows voice Microsoft Zira"
            app.brain._chat = lambda messages, use_tools: {"content": (
                "The derivative of x squared is 2x, by the power rule.\nConfidence: high, standard calculus rule."
                if "TUKI" in messages[0]["content"] else "Of course.")}
            app.image_operation = lambda kind, data: {"name": "sample-landscape.png", "image": artwork()}
            with socket.socket() as listener:
                listener.bind(("127.0.0.1", 0))
                port = listener.getsockname()[1]
            server = webui.serve(app, port)
            try:
                capture(app, f"http://127.0.0.1:{port}")
            finally:
                server.shutdown()
                server.server_close()


if __name__ == "__main__":
    main()
