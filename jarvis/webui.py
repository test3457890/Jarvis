"""The HUD, served only to this PC (http://127.0.0.1:8765).

Security: it listens on 127.0.0.1 only (not your network), rejects requests whose Host
isn't this PC (stops DNS-rebinding tricks), rejects other websites (Origin check), and
every action needs a random session key that only the page Jarvis served knows."""
import json
import queue
import secrets
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import assistants, config, images

UI_FILE = Path(__file__).with_name("ui.html")
CC_DIR = Path(__file__).with_name("static") / "cc"
REQUEST_BODY_TIMEOUT = 10


class EventBus:
    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def publish(self, kind, data):
        with self._lock:
            for q in list(self._subs):
                q.put({"kind": kind, "data": data})

    def subscribe(self):
        q = queue.Queue()
        with self._lock:
            self._subs.append(q)
        return q

    def unsubscribe(self, q):
        with self._lock:
            if q in self._subs:
                self._subs.remove(q)


def serve(app, port: int):
    bus = app.bus
    token = secrets.token_urlsafe(24)
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
    allowed_origins = {f"http://{h}" for h in allowed_hosts}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code, body: bytes, ctype):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cache-Control", "no-store")
            if code >= 400:
                self.send_header("Connection", "close")
            self.end_headers()
            try:
                self.wfile.write(body)
                self.wfile.flush()
                if code >= 400:
                    # Half-close write side first so Windows delivers 4xx responses cleanly instead of TCP RST.
                    self.close_connection = True
                    try:
                        self.connection.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj).encode(), "application/json")

        def _host_ok(self):
            return self.headers.get("Host", "") in allowed_hosts

        def _authed(self):
            origin = self.headers.get("Origin")
            if origin and origin not in allowed_origins:
                return False
            return secrets.compare_digest(self.headers.get("X-Jarvis-Key", ""), token)

        def do_GET(self):
            if not self._host_ok():
                return self._json({"error": "forbidden"}, 403)
            if self.path == "/":
                theme = app.cfg.get("theme")
                mode = app.cfg.get("mode")
                page = (UI_FILE.read_text(encoding="utf-8").replace("__JARVIS_KEY__", token)
                        .replace("__JARVIS_THEME__", theme if theme in config.THEMES else "hud")
                        .replace("__JARVIS_MODE__", mode if mode in config.MODES else "everyday")
                        .replace("__JARVIS_VIEW__", app.cfg.get("workspace_view") if app.cfg.get("workspace_view") in config.WORKSPACE_VIEWS else "classic")
                        .replace("__JARVIS_TUKI_NAME__", assistants.TUKI_NAME)
                        .replace("__JARVIS_TUKI_FULL_NAME__", assistants.TUKI_FULL_NAME))
                csp = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                       "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
                body = page.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Security-Policy", csp)
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/command-center" or self.path == "/command-center/":
                cc_index = CC_DIR / "index.html"
                if not cc_index.is_file():
                    return self._json({"error": "Modern Command Center bundle not built yet."}, 503)
                page = (
                    cc_index.read_text(encoding="utf-8")
                    .replace("__JARVIS_KEY__", token)
                    .replace("__JARVIS_THEME__", app.cfg.get("theme") if app.cfg.get("theme") in config.THEMES else "hud")
                )
                csp = ("default-src 'self'; script-src 'self' 'unsafe-inline'; "
                       "style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' data:")
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Content-Security-Policy", csp)
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path.startswith("/cc-assets/"):
                rel = self.path[len("/cc-assets/"):].split("?", 1)[0]
                target = (CC_DIR / "assets" / rel).resolve()
                assets_root = (CC_DIR / "assets").resolve()
                if target.parent != assets_root or not target.is_file():
                    return self._json({"error": "not found"}, 404)
                ctype = (
                    "application/javascript; charset=utf-8" if target.suffix == ".js"
                    else "text/css; charset=utf-8" if target.suffix == ".css"
                    else "image/svg+xml" if target.suffix == ".svg"
                    else "application/octet-stream"
                )
                return self._send(200, target.read_bytes(), ctype)
            if self.path.startswith("/api/events"):
                if not secrets.compare_digest(self.path.partition("key=")[2], token):
                    return self._json({"error": "forbidden"}, 403)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                q = bus.subscribe()
                try:
                    while True:
                        try:
                            ev = q.get(timeout=15)
                            self.wfile.write(f"data: {json.dumps(ev)}\n\n".encode())
                        except queue.Empty:
                            self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    pass
                finally:
                    bus.unsubscribe(q)
                return
            if not self._authed():
                return self._json({"error": "forbidden"}, 403)
            if self.path == "/api/state":
                self._json(app.state())
            elif self.path == "/api/voices":
                from .voice import installed_voice_names, is_british_voice
                names = installed_voice_names()
                self._json({"voices": names, "british": [v for v in names if is_british_voice(v)]})
            elif self.path == "/api/hardware":
                self._json(app.hardware_operation())
            elif self.path == "/api/audio-devices":
                self._json(app.audio_devices_operation())
            elif self.path == "/api/security":
                self._json(app.security_operation())
            elif self.path == "/api/agents":
                self._json(app.agents_operation())
            elif self.path == "/api/mcp":
                self._json(app.mcp_operation())
            elif self.path == "/api/conversations":
                self._json(app.conversations_operation())
            elif self.path == "/api/projects":
                self._json(app.projects_operation())
            elif self.path == "/api/feeds":
                self._json(app.feeds_operation())
            elif self.path == "/api/memory":
                self._json(app.memory_operation())
            elif self.path == "/api/watches":
                self._json(app.watches_operation())
            elif self.path == "/api/repository":
                self._json(app.repository_operation())
            elif self.path == "/api/recovery":
                self._json(app.recovery_operation())
            elif self.path == "/api/setup":
                self._json(app.settings_operation())
            elif self.path == "/api/wizard":
                self._json(app.wizard_operation())
            elif self.path == "/api/apps":
                self._json(app.apps_operation())
            elif self.path == "/api/extensions":
                self._json(app.extensions_operation())
            elif self.path == "/api/dashboard":
                self._json(app.dashboard())
            elif self.path == "/api/activity":
                self._json(app.activity_operation())
            elif self.path == "/api/workflows":
                self._json(app.workflows_operation())
            elif self.path == "/api/connections":
                self._json(app.connections_operation())
            elif self.path == "/api/models":
                self._json(app.models_operation())
            elif self.path == "/api/provider":
                self._json(app.provider_operation())
            elif self.path == "/api/vitals":
                self._json(app.vitals_operation())
            elif self.path == "/api/providers":
                self._json(app.providers_operation())
            elif self.path == "/api/tools/history":
                self._json(app.tool_history_operation())
            elif self.path == "/api/undo":
                self._json(app.undo_operation())
            elif self.path == "/api/bgtasks":
                self._json(app.bgtasks_operation())
            elif self.path == "/api/monitors":
                self._json(app.monitors_operation())
            elif self.path == "/api/macros":
                self._json(app.macros_operation())
            elif self.path == "/api/daily-summary":
                self._json(app.daily_summary_operation())
            elif self.path == "/api/pro":
                self._json(app.pro_operation())
            elif self.path == "/api/companion":
                self._json(app.companion_operation())
            elif self.path == "/api/geospatial":
                self._json(app.geospatial_operation())
            elif self.path == "/api/voice-studio":
                self._json(app.voice_studio_operation())
            elif self.path == "/api/uia":
                self._json(app.uia_operation())
            elif self.path == "/api/smarthome":
                self._json(app.smarthome_operation())
            elif self.path == "/api/sentinel-ops":
                self._json(app.sentinel_ops_operation())
            elif self.path == "/api/containers":
                self._json(app.containers_operation())
            elif self.path == "/api/coop-agents":
                self._json(app.coop_agents_operation())
            elif self.path == "/api/office":
                self._json(app.office_operation())
            elif self.path == "/api/catalogue":
                self._json(app.catalogue_operation())
            elif self.path == "/api/tools/catalogue":
                self._json(app.tools_catalogue_operation())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._host_ok() or not self._authed():
                # Drain tiny unauthenticated bodies so Windows sockets do not emit TCP RST before the 403 is read.
                try:
                    raw_len = int(self.headers.get("Content-Length", "0"))
                    if 0 < raw_len <= 4096:
                        self.rfile.read(raw_len)
                except (ValueError, OSError):
                    pass
                return self._json({"error": "forbidden"}, 403)
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                    return self._json({"error": "one content length required; transfer encoding is unsupported"}, 400)
                length = int(lengths[0])
                limit = images.MAX_UPLOAD_JSON if self.path in ("/api/images/lookup", "/api/documents/preview") else 100_000
                if not 0 <= length <= limit:
                    return self._json({"error": "invalid content length"}, 400)
                self.connection.settimeout(REQUEST_BODY_TIMEOUT)
                body = self.rfile.read(length)
                if len(body) != length:
                    return self._json({"error": "incomplete request body"}, 400)
                data = json.loads(body or b"{}")
                if not isinstance(data, dict):
                    return self._json({"error": "expected a JSON object"}, 400)
            except TimeoutError:
                return self._json({"error": "request body timed out"}, 408)
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            if self.path == "/api/chat":
                text = str(data.get("text", "")).strip()[:4000]
                if not text:
                    return self._json({"error": "empty"}, 400)
                if not app.submit_request(text):
                    return self._json({"error": "Jarvis is working. Use Stop before starting another request."}, 409)
                self._json({"ok": True})
            elif self.path == "/api/stop":
                self._json(app.stop())
            elif self.path == "/api/dictation":
                try:
                    self._json(app.dictation_operation(data))
                except ValueError as error:
                    self._json({"error": str(error)}, 400)
            elif self.path == "/api/toggle":
                self._json(app.toggle(str(data.get("what", ""))))
            elif self.path == "/api/preferences":
                try:
                    state = app.set_preference(data.get("key"), data.get("value"))
                except (ValueError, TypeError) as error:
                    return self._json({"error": str(error)}, 400)
                except OSError:
                    return self._json({"error": "Could not save the setting."}, 500)
                self._json(state)
            elif self.path in ("/api/images/lookup", "/api/images/generate"):
                try:
                    output = app.image_operation(self.path.rsplit("/", 1)[1], data)
                except ValueError as error:
                    return self._json({"error": str(error)}, 400)
                except OSError:
                    return self._json({"error": "The local image backend failed or is unavailable. Check the setup."}, 502)
                self._json(output)
            elif self.path in ("/api/apps", "/api/extensions"):
                try:
                    operation = app.apps_operation if self.path == "/api/apps" else app.extensions_operation
                    result = operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/workflows":
                try:
                    self._json(app.workflows_operation(data))
                except (ValueError, TypeError, OSError) as error:
                    self._json({"error": str(error)}, 400)
            elif self.path == "/api/provider":
                try:
                    self._json(app.provider_operation(data))
                except (ValueError, TypeError, OSError) as error:
                    self._json({"error": str(error)}, 400)
            elif self.path == "/api/connections":
                try:
                    result = app.connections_operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/files":
                try:
                    result = app.files_operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/wizard":
                try:
                    result = app.wizard_operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path in ("/api/setup", "/api/recovery"):
                try:
                    operation = app.settings_operation if self.path == "/api/setup" else app.recovery_operation
                    result = operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/memory":
                try:
                    result = app.memory_operation(data)
                except (ValueError, TypeError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/watches":
                try:
                    result = app.watches_operation(data)
                except (ValueError, TypeError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/models":
                try:
                    result = app.models_operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/repository":
                try:
                    result = app.repository_operation(data)
                except (ValueError, TypeError, OSError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path in ("/api/mcp", "/api/conversations", "/api/projects", "/api/feeds", "/api/documents/preview",
                               "/api/providers", "/api/tools/dry-run", "/api/bgtasks", "/api/monitors", "/api/macros", "/api/daily-summary",
                               "/api/pro", "/api/companion", "/api/geospatial", "/api/voice-studio",
                               "/api/uia", "/api/smarthome", "/api/sentinel-ops", "/api/containers",
                               "/api/coop-agents", "/api/office", "/api/catalogue"):
                try:
                    ops = {
                        "/api/mcp": app.mcp_operation,
                        "/api/conversations": app.conversations_operation,
                        "/api/projects": app.projects_operation,
                        "/api/feeds": app.feeds_operation,
                        "/api/documents/preview": app.document_preview_operation,
                        "/api/providers": app.providers_operation,
                        "/api/tools/dry-run": app.dry_run_operation,
                        "/api/bgtasks": app.bgtasks_operation,
                        "/api/monitors": app.monitors_operation,
                        "/api/macros": app.macros_operation,
                        "/api/daily-summary": app.daily_summary_operation,
                        "/api/pro": app.pro_operation,
                        "/api/companion": app.companion_operation,
                        "/api/geospatial": app.geospatial_operation,
                        "/api/voice-studio": app.voice_studio_operation,
                        "/api/uia": app.uia_operation,
                        "/api/smarthome": app.smarthome_operation,
                        "/api/sentinel-ops": app.sentinel_ops_operation,
                        "/api/containers": app.containers_operation,
                        "/api/coop-agents": app.coop_agents_operation,
                        "/api/office": app.office_operation,
                        "/api/catalogue": app.catalogue_operation,
                    }
                    result = ops[self.path](data)
                except (ValueError, TypeError, OSError, PermissionError) as error:
                    return self._json({"error": str(error)}, 400)
                self._json(result)
            elif self.path == "/api/voice-preview":
                self._json(app.preview_voice(str(data.get("assistant", "jarvis"))))
            elif self.path == "/api/confirm":
                if not isinstance(data.get("yes"), bool):
                    return self._json({"error": "expected a boolean confirmation"}, 400)
                if not isinstance(data.get("id"), str) or not data["id"]:
                    return self._json({"error": "expected a request identifier"}, 400)
                self._json(app.confirm(data["yes"], data["id"]))
            else:
                self._json({"error": "not found"}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    return server
