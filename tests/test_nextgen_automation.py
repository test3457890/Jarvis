"""Step 2 Completion tests:
- Desktop window state validation & blocked hotkey security policy (desktop.py)
- Real Playwright Chromium SafeBrowserSession: tab management, form fill, click,
  screenshot capture, route-level SSRF subresource blocking, and cancellation (browser_auto.py)
"""
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading
import pytest

from jarvis import browser_auto, config, desktop


def test_desktop_hotkey_policy_and_window_state_validation():
    assert desktop.send_approved_hotkey("ctrl+c", dry_run=True)["keys"] == ["ctrl", "c"]
    for blocked in ("ctrl+alt+del", "win+r", "win+x"):
        with pytest.raises(PermissionError, match="blocked"):
            desktop.validate_hotkey(blocked)
    with pytest.raises(ValueError, match="window state"):
        desktop.set_window_state("Notepad", "destroy")


def test_playwright_safe_session_tabs_forms_screenshot_and_ssrf_subresource_block(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "APP_DIR", tmp_path)

    # Local fixture HTTP server with a form, button, and an illicit SSRF image pointing to 169.254.169.254
    html = b"""<!doctype html><html><head><title>Jarvis Auto Fixture</title></head><body>
    <input id="name" type="text">
    <button id="go" onclick="document.getElementById('out').textContent='Hello ' + document.getElementById('name').value">Go</button>
    <div id="out"></div>
    <img src="http://169.254.169.254/latest/meta-data/" alt="ssrf">
    </body></html>"""

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

    srv = HTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()

    cfg = dict(config.DEFAULTS, allow_internet_tools=True, lockdown=False)
    cancel_ev = threading.Event()
    try:
        with browser_auto.SafeBrowserSession(cfg, allow_test_loopback=("127.0.0.1", port), cancel_event=cancel_ev) as sess:
            tab0 = sess.open_tab(f"http://127.0.0.1:{port}/")
            assert tab0["title"] == "Jarvis Auto Fixture"
            assert sess.fill("#name", "Jarvis")["ok"] is True
            assert sess.click("#go")["ok"] is True
            assert "Hello Jarvis" in sess.read_text()

            # Subresource SSRF to AWS metadata IP MUST have been intercepted & aborted
            assert any("169.254.169.254" in u for u in sess.blocked_requests)

            # Screenshot saved strictly inside APP_DIR/screenshots
            shot = sess.screenshot("fixture_test.png")
            assert shot.is_file() and shot.stat().st_size > 100

            # Multi-tab management
            sess.open_tab(f"http://127.0.0.1:{port}/second")
            assert len(sess.list_tabs()) == 2
            assert sess.switch_tab(0)["tab"] == 0

            # Cancellation halts subsequent actions immediately
            cancel_ev.set()
            with pytest.raises(RuntimeError, match="cancelled"):
                sess.read_text()
    finally:
        srv.shutdown()
        srv.server_close()
