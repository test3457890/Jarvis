"""Project NOMAD integration (https://www.projectnomad.us).

NOMAD runs an offline library (Kiwix), local AI (Ollama), maps, Khan Academy (Kolibri),
notes and more. Jarvis can search NOMAD's offline Wikipedia/medical/repair library,
use NOMAD's Ollama models, and open any NOMAD service.
Default ports come from NOMAD's own service list."""
import html
import re
import socket
import urllib.parse
import urllib.request
import webbrowser
import xml.etree.ElementTree as ET

from . import net
from .skills import skill

SERVICES = {
    "command center": 8080, "library": 8090, "ai": 11434, "education": 8310,
    "notes": 8200, "cyberchef": 8100, "pdf tools": 8400,
}


def _host(cfg):
    return urllib.parse.urlparse(cfg.get("nomad_url", "http://127.0.0.1:8080")).hostname or "127.0.0.1"


def _up(host, port, cfg, timeout=0.6) -> bool:
    try:
        net.check_tcp(host, port, cfg, purpose="nomad_status")
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (OSError, net.NetworkBlockedError):
        return False


def status(cfg) -> dict:
    host = _host(cfg)
    return {name: _up(host, port, cfg) for name, port in SERVICES.items()}


def _kiwix(cfg):
    return cfg.get("kiwix_url") or f"http://{_host(cfg)}:{SERVICES['library']}"


def _get(url, cfg, timeout=10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Jarvis"})
    with net.urlopen(req, cfg, timeout=timeout, purpose="nomad_kiwix") as r:
        return r.read(3_000_000).decode("utf-8", errors="replace")


def _text(page_html: str) -> str:
    page_html = re.sub(r"(?is)<(script|style|table|nav|footer)[^>]*>.*?</\1>", " ", page_html)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", page_html))
    return re.sub(r"\s+", " ", text).strip()


@skill("Search the offline knowledge library on Project NOMAD (Wikipedia, medical, repair and "
       "survival guides). Works without internet. Prefer this for factual questions.",
       params={"query": ("string", "What to look up", True)}, untrusted=True)
def search_library(ctx, query):
    base = _kiwix(ctx.cfg).rstrip("/")
    try:
        feed = _get(f"{base}/search?pattern={urllib.parse.quote(query)}&format=xml&pageLength=5", ctx.cfg)
        items = ET.fromstring(feed).iter("item")
        results = [(i.findtext("title") or "", i.findtext("link") or "", _text(i.findtext("description") or ""))
                   for i in items]
    except OSError:
        return ("The NOMAD library isn't reachable. Make sure Project NOMAD is running "
                f"(expected at {base}).")
    except ET.ParseError:
        return "The library answered in an unexpected format."
    if not results:
        return f"Nothing found in the offline library for '{query}'."
    title, link, _ = results[0]
    try:
        article = _text(_get(base + link if link.startswith("/") else link, ctx.cfg))[:2500]
    except OSError:
        article = ""
    others = "; ".join(t for t, _, _ in results[1:4])
    return f"Top result: {title}\n{article}\n" + (f"Other matches: {others}" if others else "")


@skill("Check which Project NOMAD services are running.")
def nomad_status(ctx):
    st = status(ctx.cfg)
    up = [k for k, v in st.items() if v]
    down = [k for k, v in st.items() if not v]
    if not (st["command center"] or st["library"]):
        return "Project NOMAD isn't running or isn't reachable from this PC."
    return f"NOMAD online: {', '.join(up)}." + (f" Offline: {', '.join(down)}." if down else "")


@skill("Open a Project NOMAD service in the browser: command center, library, maps, education, notes, "
       "cyberchef or pdf tools.",
       params={"service": ("string", "Which service", True)})
def open_nomad(ctx, service):
    s = service.lower().strip()
    host = _host(ctx.cfg)
    if s in ("maps", "map"):
        url = f"http://{host}:8080/maps"
    elif s in ("chat", "ai"):
        url = f"http://{host}:8080/chat"
    else:
        port = next((p for name, p in SERVICES.items() if s in name or name in s), 8080)
        url = f"http://{host}:{port}"
    webbrowser.open(url)
    return f"Opened NOMAD {service}."
