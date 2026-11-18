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

UI_FILE = Path(__file__).with_name("ui.html")


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
                page = UI_FILE.read_text(encoding="utf-8").replace("__JARVIS_KEY__", token)
                csp = ("default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' "
                       "https://fonts.googleapis.com; font-src https://fonts.gstatic.com; connect-src 'self'")
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
            elif self.path == "/api/dashboard":
                self._json(app.dashboard())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self):
            if not self._host_ok() or not self._authed():
                return self._json({"error": "forbidden"}, 403)
            length = min(int(self.headers.get("Content-Length") or 0), 100_000)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                return self._json({"error": "bad json"}, 400)
            if self.path == "/api/chat":
                text = str(data.get("text", "")).strip()[:4000]
                if not text:
                    return self._json({"error": "empty"}, 400)
                threading.Thread(target=app.handle, args=(text, "", "typed"), daemon=True).start()
                self._json({"ok": True})
            elif self.path == "/api/toggle":
                self._json(app.toggle(str(data.get("what", ""))))
            elif self.path == "/api/confirm":
                self._json(app.confirm(bool(data.get("yes"))))
            else:
                self._json({"error": "not found"}, 404)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True, name="web").start()
    return server
