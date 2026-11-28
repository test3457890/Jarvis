"""Approved, fail-closed Playwright Browser Automation (read-only page inspection).

Security rules:
- Disabled in offline mode or Lockdown.
- Requires an explicit public HTTPS URL (blocks RFC1918/loopback/link-local SSRF via DNS check).
- Requires explicit user confirmation (risky=True, internet=True, untrusted=True).
- Extracted page content is bounded and fenced against prompt injection.
"""
import ipaddress
import socket
import urllib.parse

from . import net, secure
from .skills import skill

MAX_TEXT_CHARS = 12_000


def validate_public_https_url(url: str) -> str:
    raw = str(url or "").strip()
    if len(raw) > 2000 or any(ord(c) < 33 for c in raw):
        raise net.NetworkBlockedError("Provide a valid public HTTPS URL.")
    parsed = urllib.parse.urlsplit(raw)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username is not None or parsed.password is not None:
        raise net.NetworkBlockedError("Only public HTTPS URLs without embedded credentials are permitted.")
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


def inspect_page(cfg: dict, url: str, *, timeout_ms: int = 15000) -> dict:
    """Open an approved public HTTPS page in headless Playwright Chromium and return bounded text."""
    if not cfg.get("allow_internet_tools") or cfg.get("lockdown"):
        raise net.NetworkBlockedError("Approved browser inspection requires Internet ON and Lockdown OFF.")
    clean_url = validate_public_https_url(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("Playwright is not installed in this environment.") from None

    secure.audit("browser_inspect", {"host": urllib.parse.urlsplit(clean_url).hostname})
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.goto(clean_url, wait_until="domcontentloaded", timeout=timeout_ms)
            title = (page.title() or "")[:200]
            text = (page.inner_text("body") or "")[:MAX_TEXT_CHARS]
            return {"url": clean_url, "title": title, "text": text, "chars": len(text)}
        finally:
            browser.close()


@skill(
    "Inspect an explicitly approved public HTTPS web page using headless Playwright.",
    params={"url": ("string", "Public HTTPS URL to inspect", True)},
    risky=True,
    internet=True,
    untrusted=True,
    manual=True,
    preview=lambda ctx, url: f"open and read public HTTPS page {url} in headless Playwright",
)
def browser_inspect(ctx, url):
    res = inspect_page(ctx.cfg, url)
    return f"Title: {res['title']}\nURL: {res['url']}\n\n{res['text']}"
