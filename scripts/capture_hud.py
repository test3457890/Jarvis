"""Capture the real HUD with synthetic data and stubbed model services."""
import base64
import io
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
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, reduced_motion="reduce", device_scale_factor=1)
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(base_url)
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
        page.locator("#q").fill("/fix budget.py | handle empty input")
        page.locator("#q").press("Enter")
        expect(page.get_by_text("Preview only.", exact=False)).to_be_visible()
        page.screenshot(path=OUT / "coding-diff.png")
        page.get_by_role("button", name="Apply proposal").click()
        expect(page.get_by_text("Updated budget.py.", exact=False)).to_be_visible()

        page.locator("#images summary").click()
        page.locator("#image-prompt").fill("Minimal mountain landscape at dusk")
        page.get_by_role("button", name="Generate locally").click()
        expect(page.get_by_role("link", name="Download PNG")).to_be_visible()
        page.screenshot(path=OUT / "image-tools.png")
        assert not errors, errors


def main():
    with tempfile.TemporaryDirectory() as tmp, patch.object(App, "_watchdog"), patch.object(nomad, "status", return_value={}):
        home = Path(tmp)
        code = home / "code"
        code.mkdir()
        (code / "budget.py").write_text("def total(values):\n    return sum(values) / len(values)\n", encoding="utf-8")
        cfg = dict(config.DEFAULTS, code_dir=str(code), speak_replies=False,
                   image_generation_url="http://127.0.0.1:7860")
        with patch.object(config, "APP_DIR", home), patch.object(config, "CONFIG_PATH", home / "config.json"), \
                patch.object(memory, "APP_DIR", home), patch.object(memory, "DB_PATH", home / "memory.db"):
            app = App(cfg, use_voice=False)
            app.brain.embed = lambda text: None
            app.brain._chat = lambda messages, use_tools: {"content": "Of course."}
            app.brain.raw_chat = lambda messages, model: (
                "```python\ndef total(values):\n    if not values:\n        return 0\n"
                "    return sum(values) / len(values)\n```"
            )
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
