"""Live Chrome Playwright Audit for the 19-Workspace Modern Command Center HUD (/command-center).

Verifies all 19 workspaces, real backend data wiring, interactive 3D Globe, Sentinel Ops,
Hardened Containers, Cooperative Agents, Command Palette, Floating/Fullscreen/Reduced-Motion,
Legacy HUD link, and captures authentic screenshots under docs/screenshots/.
"""
import os
from pathlib import Path
import re
import socket
import tempfile

from playwright.sync_api import sync_playwright, expect

from jarvis import __main__ as jarvis_main, config, memory, webui

WORKSPACES = [
    "console", "computer", "globe", "sentinel", "agents", "research",
    "developer", "academic", "professional", "communications", "smarthome",
    "automation", "containers", "voice", "models", "connections", "audit",
    "repair", "settings",
]


def run_audit() -> tuple[int, int]:
    passed = 0
    total = 0
    errors: list[str] = []

    def check(label: str, fn):
        nonlocal passed, total
        total += 1
        try:
            fn()
            passed += 1
            print(f"PASS {label}")
        except Exception as exc:
            errors.append(f"FAIL {label}: {exc}")
            print(f"FAIL {label}: {exc}")

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        config.APP_DIR = tmp
        config.CONFIG_PATH = tmp / "config.json"
        memory.DB_PATH = tmp / "cc_audit.db"
        cfg = dict(config.DEFAULTS, notes_dir=str(tmp / "notes"), setup_complete=True)
        (tmp / "notes").mkdir(exist_ok=True)
        config.save(cfg)

        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]

        app = jarvis_main.App(cfg, use_voice=False)
        server = webui.serve(app, port)
        base = f"http://127.0.0.1:{port}"
        chrome = os.environ.get("JARVIS_CHROME", r"C:\Program Files\Google\Chrome\Application\chrome.exe")
        shots_dir = Path("docs/screenshots")
        shots_dir.mkdir(parents=True, exist_ok=True)

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(executable_path=chrome if Path(chrome).is_file() else None, headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page_errors: list[str] = []
                page.on("pageerror", lambda err: page_errors.append(str(err)))

                page.goto(f"{base}/command-center", wait_until="networkidle")

                check("Command Center loads with Jarvis & TUKI core indicators", lambda: (
                    expect(page.get_by_text("JARVIS & TUKI", exact=True)).to_be_visible(),
                    expect(page.locator(".cc-core")).to_be_visible(),
                ))

                check("Console live vitals refresh & authentic screenshot", lambda: (
                    page.get_by_role("button", name="Refresh Live Vitals").click(),
                    expect(page.locator(".cc-card:visible").filter(has_text="CPU Load (Live)")).to_contain_text(
                        re.compile(r"\d+(?:\.\d+)?%"), timeout=15000),
                    page.locator(".cc-grid").first.screenshot(path=str(shots_dir / "command-center-vitals-2026-11.png")),
                ))

                # Verify all 19 workspaces switch cleanly
                def verify_all_19():
                    for ws in WORKSPACES:
                        btn = page.locator(f"button[data-cc-ws='{ws}']")
                        expect(btn).to_be_visible()
                        btn.click()
                        expect(btn).to_have_class(re.compile(r"\bactive\b"))
                check("All 19 Command Center workspaces render and switch cleanly", verify_all_19)

                # Each workspace must reach a real authenticated backend route. This
                # verifies data wiring; it does not claim every control is end-to-end.
                backend_routes = {
                    "console": "/api/vitals", "computer": "/api/uia", "globe": "/api/geospatial",
                    "sentinel": "/api/sentinel-ops", "agents": "/api/coop-agents",
                    "research": "/api/office", "developer": "/api/tools/catalogue",
                    "academic": "/api/office", "professional": "/api/office",
                    "communications": "/api/connections", "smarthome": "/api/smarthome",
                    "automation": "/api/coop-agents", "containers": "/api/containers",
                    "voice": "/api/voice-studio", "models": "/api/providers",
                    "connections": "/api/catalogue", "audit": "/api/activity",
                    "repair": "/api/recovery", "settings": "/api/setup",
                }
                for workspace, route in backend_routes.items():
                    def verify_backend(ws=workspace, ep=route):
                        page.locator(f"button[data-cc-ws='{ws}']").click()
                        expect(page.locator("main .cc-card:visible").first).to_be_visible()
                        response = page.evaluate("""async path => {
                            const res = await fetch(path, {headers: {'X-Jarvis-Key': window.__JARVIS_SESSION__}});
                            const body = await res.json();
                            return {status: res.status, keys: Object.keys(body || {})};
                        }""", ep)
                        assert response["status"] == 200 and response["keys"], response
                    check(f"{workspace} workspace authenticated backend read", verify_backend)

                check("Global Intelligence 3D Globe: SAR grid, voice nav & authentic screenshot", lambda: (
                    page.locator("button[data-cc-ws='globe']").click(),
                    expect(page.locator("canvas.cc-globe-canvas")).to_be_visible(),
                    page.get_by_role("button", name="Plot SAR Grid (Simulated)").click(),
                    expect(page.locator("[role='status']")).to_contain_text("SAR Grid [SIMULATED]"),
                    page.get_by_placeholder("Voice nav:").fill("fly to Tokyo"),
                    page.get_by_role("button", name="Navigate").click(),
                    expect(page.locator("[role='status']")).to_contain_text("Tokyo"),
                    page.screenshot(path=str(shots_dir / "command-center-globe-2026-11.png")),
                ))

                check("Sentinel Cybersecurity: FIM verify & defensive firewall preview", lambda: (
                    page.locator("button[data-cc-ws='sentinel']").click(),
                    page.get_by_role("button", name="Verify FIM Baselines").click(),
                    expect(page.locator("[role='status']")).to_contain_text("FIM Verify"),
                    page.get_by_role("button", name="Preview Defensive Firewall Rule").click(),
                    expect(page.locator("[role='status']")).to_contain_text("New-NetFirewallRule"),
                ))

                check("Container Management: hardened sandbox preview", lambda: (
                    page.locator("button[data-cc-ws='containers']").click(),
                    page.get_by_role("button", name="Preview Hardened Sandbox Command").click(),
                    expect(page.locator("[role='status']")).to_contain_text("--cap-drop=ALL"),
                ))

                check("Agent Center: create cooperative Jarvis+TUKI plan", lambda: (
                    page.locator("button[data-cc-ws='agents']").click(),
                    page.get_by_role("button", name="New Cooperative Plan").click(),
                    expect(page.locator("[role='status']")).to_contain_text("Created cooperative plan"),
                ))

                check("Developer Center: searchable live skill catalogue", lambda: (
                    page.locator("button[data-cc-ws='developer']").click(),
                    expect(page.get_by_text("Searchable Tool Catalogue")).to_be_visible(),
                ))

                check("Connections: searchable vetted MCP catalogue", lambda: (
                    page.locator("button[data-cc-ws='connections']").click(),
                    expect(page.get_by_text("God's Eye View Geospatial MCP")).to_be_visible(),
                ))

                check("Command Palette (Ctrl+K), Reduced Motion, Floating Mini & Full Screen", lambda: (
                    page.get_by_role("button", name="Palette (Ctrl+K)").click(),
                    expect(page.get_by_role("dialog", name="Command Palette")).to_be_visible(),
                    page.keyboard.press("Escape"),
                    page.get_by_role("button", name="Motion: On").click(),
                    expect(page.get_by_role("button", name="Motion: Reduced")).to_be_visible(),
                    page.get_by_role("button", name="Full Screen").click(),
                    expect(page.get_by_role("button", name="Show Rail")).to_be_visible(),
                    page.get_by_role("button", name="Show Rail").click(),
                ))

                def verify_canvas():
                    page.evaluate("""() => localStorage.setItem('jarvis-intelligence-canvas-v1', JSON.stringify([
                        {id:'fixture_1', kind:'summary', title:'Synthetic bench note', text:'Synthetic fixture only', assistant:'tuki', provenance:'simulation'},
                        {id:'fixture_2', kind:'progress', title:'Synthetic progress', value:35, provenance:'simulation'}
                    ]))""")
                    page.reload(wait_until="networkidle")
                    page.get_by_role("button", name="Intelligence Canvas").click()
                    canvas = page.get_by_role("region", name="Intelligence Canvas")
                    expect(canvas.get_by_text("Synthetic bench note")).to_be_visible()
                    expect(canvas.get_by_text("Synthetic fixture only")).to_be_visible()
                    canvas.get_by_role("button", name="Move Synthetic progress earlier").click()
                    assert canvas.locator("article strong").first.inner_text() == "Synthetic progress"
                    with page.expect_download() as download:
                        canvas.get_by_role("button", name="Export JSON").click()
                    assert download.value.suggested_filename == "jarvis-intelligence-canvas.json"
                    canvas.screenshot(path=str(shots_dir / "command-center-intelligence-canvas.png"))
                    page.reload(wait_until="networkidle")
                    page.get_by_role("button", name="Intelligence Canvas").click()
                    assert page.get_by_role("region", name="Intelligence Canvas").locator("article strong").first.inner_text() == "Synthetic progress"
                    page.get_by_role("button", name="Workspaces").click()
                check("Intelligence Canvas restores, reorders and exports synthetic cards", verify_canvas)

                def verify_local_camera():
                    page.locator("button[data-cc-ws='smarthome']").click()
                    page.evaluate("""() => {
                        const track = document.createElement('canvas').captureStream(5).getVideoTracks()[0];
                        window.__TEST_CAMERA_TRACK__ = track;
                        Object.defineProperty(navigator, 'mediaDevices', {configurable:true, value: {
                            getUserMedia: async () => new MediaStream([track]),
                            enumerateDevices: async () => [{kind:'videoinput', deviceId:'synthetic', label:'Synthetic camera'}]
                        }});
                    }""")
                    camera = page.get_by_role("region", name="Local camera preview")
                    camera.get_by_role("button", name="Start camera").click()
                    expect(camera.get_by_text("CAMERA ON", exact=False)).to_be_visible()
                    camera.get_by_role("button", name="Stop camera").click()
                    expect(camera.get_by_role("status")).to_contain_text("Camera off")
                    assert page.evaluate("window.__TEST_CAMERA_TRACK__.readyState") == "ended"
                    page.evaluate("""() => {
                        navigator.mediaDevices.getUserMedia = () => new Promise(resolve => { window.__TEST_RESOLVE__ = resolve; });
                        window.__TEST_LATE_TRACK__ = document.createElement('canvas').captureStream(5).getVideoTracks()[0];
                    }""")
                    camera.get_by_role("button", name="Start camera").click()
                    expect(camera.get_by_role("status")).to_contain_text("Waiting for browser camera permission")
                    camera.get_by_role("button", name="Stop camera").click()
                    page.evaluate("window.__TEST_RESOLVE__(new MediaStream([window.__TEST_LATE_TRACK__]))")
                    expect(camera.get_by_role("status")).to_contain_text("Camera off")
                    page.wait_for_function("window.__TEST_LATE_TRACK__.readyState === 'ended'")
                    page.locator("button[data-cc-ws='console']").click()
                check("Local camera starts only on click and stops synthetic track", verify_local_camera)

                check("Legacy HUD switch returns cleanly to /", lambda: (
                    page.get_by_role("link", name="Legacy HUD").click(),
                    page.wait_for_url(f"{base}/"),
                    expect(page.locator("#open-command-center")).to_be_visible(),
                ))

                check("Zero uncaught JavaScript page errors", lambda: (
                    None if not page_errors else (_ for _ in ()).throw(AssertionError(f"Page errors: {page_errors}"))
                ))

                browser.close()
        finally:
            server.shutdown()
            server.server_close()
            try:
                app.memory.db.close()
            except Exception:
                pass

    print(f"COMMAND_CENTER_AUDIT: {passed}/{total} passed")
    return passed, total


if __name__ == "__main__":
    p, t = run_audit()
    raise SystemExit(0 if p == t else 1)
