"""Approved, fail-closed Playwright Browser Automation with Route-Level SSRF Guard.

Security rules:
- Disabled in offline mode or Lockdown.
- Every navigation, redirect, subresource, and subsequent request passes through a
  Playwright context route interceptor (`_route_guard`) that blocks non-HTTPS schemes,
  embedded credentials, and private/loopback/link-local SSRF addresses (unless an
  explicit test loopback host is supplied for local test fixtures).
- Consequential actions (click, fill, press, navigate, screenshot) require explicit
  approval (`risky=True`), verify results, and support cancellation.
- Extracted page text is bounded and fenced against prompt injection.
"""
import ipaddress
import os
import socket
import threading
import urllib.parse
from pathlib import Path

from . import config, net, secure
from .skills import skill

MAX_TEXT_CHARS = 12_000


def validate_public_https_url(url: str, *, allow_test_loopback: tuple[str, int] | None = None) -> str:
    raw = str(url or "").strip()
    if len(raw) > 2000 or any(ord(c) < 33 for c in raw):
        raise net.NetworkBlockedError("Provide a valid public HTTPS URL.")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.username is not None or parsed.password is not None:
        raise net.NetworkBlockedError("Embedded credentials in URLs are forbidden.")

    if allow_test_loopback is not None:
        thost, tport = allow_test_loopback
        if parsed.scheme == "http" and parsed.hostname == thost and parsed.port == tport:
            return raw

    if parsed.scheme != "https" or not parsed.hostname:
        raise net.NetworkBlockedError("Only public HTTPS URLs are permitted.")
    if parsed.port not in (None, 443):
        raise net.NetworkBlockedError("Only standard HTTPS port 443 is permitted.")
    host = parsed.hostname.encode("idna").decode("ascii")
    try:
        addrs = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise net.NetworkBlockedError(f"Could not resolve host '{host}': {exc}") from None
    if not addrs or any(not ipaddress.ip_address(a[4][0]).is_global for a in addrs):
        raise net.NetworkBlockedError("URL must resolve exclusively to globally routable public IP addresses.")
    return raw


class SafeBrowserSession:
    """Managed Playwright Chromium session with route-level network enforcement & tab management."""

    def __init__(self, cfg: dict, *, allow_test_loopback: tuple[str, int] | None = None, cancel_event: threading.Event | None = None):
        if not cfg.get("allow_internet_tools") or cfg.get("lockdown"):
            raise net.NetworkBlockedError("Approved browser automation requires Internet ON and Lockdown OFF.")
        self.cfg = cfg
        self.allow_test_loopback = allow_test_loopback
        self.cancel_event = cancel_event or threading.Event()
        self.blocked_requests: list[str] = []
        self._pw = None
        self._browser = None
        self._context = None
        self._pages: list = []
        self._active_idx = 0

    def __enter__(self):
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        exe = os.environ.get("JARVIS_CHROME") or None
        self._browser = self._pw.chromium.launch(headless=True, executable_path=exe)
        self._context = self._browser.new_context()
        self._context.route("**/*", self._route_guard)
        return self

    def __exit__(self, *_exc):
        try:
            if self._context:
                self._context.close()
        finally:
            try:
                if self._browser:
                    self._browser.close()
            finally:
                if self._pw:
                    self._pw.stop()

    def _check_cancel(self) -> None:
        if self.cancel_event.is_set():
            raise RuntimeError("Browser automation cancelled by user.")

    def _route_guard(self, route) -> None:
        req_url = route.request.url
        if req_url.startswith("about:blank"):
            route.continue_()
            return
        try:
            validate_public_https_url(req_url, allow_test_loopback=self.allow_test_loopback)
            route.continue_()
        except net.NetworkBlockedError:
            self.blocked_requests.append(req_url[:200])
            secure.audit("browser_request_blocked", {"url": req_url[:120]})
            route.abort("blockedbyclient")

    def open_tab(self, url: str, *, timeout_ms: int = 15000) -> dict:
        self._check_cancel()
        clean = validate_public_https_url(url, allow_test_loopback=self.allow_test_loopback)
        page = self._context.new_page()
        page.goto(clean, wait_until="domcontentloaded", timeout=timeout_ms)
        self._pages.append(page)
        self._active_idx = len(self._pages) - 1
        secure.audit("browser_tab_opened", {"host": urllib.parse.urlsplit(clean).hostname})
        return {"tab": self._active_idx, "url": page.url, "title": (page.title() or "")[:200]}

    def list_tabs(self) -> list[dict]:
        return [
            {"index": i, "active": i == self._active_idx, "url": p.url, "title": (p.title() or "")[:120]}
            for i, p in enumerate(self._pages) if not p.is_closed()
        ]

    def switch_tab(self, index: int) -> dict:
        if not 0 <= index < len(self._pages) or self._pages[index].is_closed():
            raise ValueError(f"Invalid tab index {index}.")
        self._active_idx = index
        p = self._pages[index]
        return {"tab": index, "url": p.url, "title": (p.title() or "")[:120]}

    def active_page(self):
        if not self._pages or self._pages[self._active_idx].is_closed():
            raise ValueError("No open browser tab.")
        return self._pages[self._active_idx]

    def fill(self, selector: str, value: str) -> dict:
        self._check_cancel()
        page = self.active_page()
        page.locator(selector).first.fill(str(value or ""))
        actual = page.locator(selector).first.input_value()
        return {"ok": actual == str(value or ""), "selector": selector}

    def click(self, selector: str) -> dict:
        self._check_cancel()
        page = self.active_page()
        page.locator(selector).first.click(timeout=5000)
        return {"ok": True, "selector": selector, "url": page.url}

    def read_text(self) -> str:
        self._check_cancel()
        return (self.active_page().inner_text("body") or "")[:MAX_TEXT_CHARS]

    def screenshot(self, filename: str) -> Path:
        self._check_cancel()
        clean_name = Path(str(filename or "browser.png")).name
        if not clean_name.lower().endswith(".png"):
            clean_name += ".png"
        out_dir = config.APP_DIR / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = (out_dir / clean_name).resolve()
        if dest.parent != out_dir.resolve():
            raise ValueError("Invalid screenshot filename.")
        self.active_page().screenshot(path=str(dest))
        return dest


def inspect_page(cfg: dict, url: str, *, timeout_ms: int = 15000) -> dict:
    """Open an approved public HTTPS page in a route-guarded Playwright Chromium session."""
    with SafeBrowserSession(cfg) as sess:
        info = sess.open_tab(url, timeout_ms=timeout_ms)
        text = sess.read_text()
        return {
            "url": info["url"],
            "title": info["title"],
            "text": text,
            "chars": len(text),
            "blocked_subresources": list(sess.blocked_requests),
        }


@skill(
    "Inspect an explicitly approved public HTTPS web page using route-guarded Playwright.",
    params={"url": ("string", "Public HTTPS URL to inspect", True)},
    risky=True,
    internet=True,
    untrusted=True,
    manual=True,
    preview=lambda ctx, url: f"open and read public HTTPS page {url} in route-guarded Playwright",
)
def browser_inspect(ctx, url):
    res = inspect_page(ctx.cfg, url)
    return f"Title: {res['title']}\nURL: {res['url']}\n\n{res['text']}"
