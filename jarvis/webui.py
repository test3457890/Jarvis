"""The HUD, served only to this PC (http://127.0.0.1:8765).

Security: it listens on 127.0.0.1 only (not your network), rejects requests whose Host
isn't this PC (stops DNS-rebinding tricks), rejects other websites (Origin check), and
every action needs a random session key that only the page Jarvis served knows."""
import json
import queue
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import assistants, config, images

UI_FILE = Path(__file__).with_name("ui.html")
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
            self.end_headers()
            self.wfile.write(body)

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
            elif self.path == "/api/memory":
                self._json(app.memory_operation())
            elif self.path == "/api/watches":
                self._json(app.watches_operation())
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
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._host_ok() or not self._authed():
                return self._json({"error": "forbidden"}, 403)
            try:
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                    return self._json({"error": "one content length required; transfer encoding is unsupported"}, 400)
                length = int(lengths[0])
                limit = images.MAX_UPLOAD_JSON if self.path == "/api/images/lookup" else 100_000
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
