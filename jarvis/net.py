"""Central network allowlist. Every outbound HTTP/TCP/SMTP request goes through here and fails closed."""
import urllib.parse
import urllib.request

from . import secure

NOMAD_PORTS = frozenset({8080, 8090, 11434, 8310, 8200, 8100, 8400})


class NetworkBlockedError(PermissionError):
    """Raised when an outbound request is not on the central allowlist."""


def _norm_port(scheme: str, port: int | None) -> int:
    if port is not None:
        return port
    return 443 if scheme == "https" else 80


def _parse_endpoint(url: str) -> tuple[str, str, int] | None:
    try:
        p = urllib.parse.urlparse(url)
    except ValueError:
        return None
    scheme = (p.scheme or "").lower()
    host = (p.hostname or "").lower()
    if scheme not in ("http", "https") or not host:
        return None
    return scheme, host, _norm_port(scheme, p.port)


def local_image_endpoint(value):
    if not isinstance(value, str):
        return None
    try:
        url = urllib.parse.urlsplit(value)
        port = url.port
    except ValueError:
        return None
    if (url.scheme == "http" and url.hostname == "127.0.0.1" and url.username is None
            and url.path in ("", "/") and not url.query and not url.fragment and port):
        return f"http://127.0.0.1:{port}"
    return None


def allowed_endpoints(cfg: dict) -> set[tuple[str, str, int]]:
    """Build the exact set of allowed (scheme, host, port) tuples from config and secrets."""
    allowed: set[tuple[str, str, int]] = set()

    ollama = _parse_endpoint(cfg.get("ollama_url", "http://127.0.0.1:11434"))
    if ollama:
        allowed.add(ollama)

    nomad = _parse_endpoint(cfg.get("nomad_url", "http://127.0.0.1:8080"))
    if nomad:
        _, nhost, _ = nomad
        for port in NOMAD_PORTS:
            allowed.add(("http", nhost, port))
            allowed.add(("https", nhost, port))

    kiwix = cfg.get("kiwix_url") or ""
    if kiwix:
        k = _parse_endpoint(kiwix)
        if k:
            allowed.add(k)

    canvas_feed = secure.get_secret("canvas_feed_url")
    if canvas_feed:
        c = _parse_endpoint(canvas_feed)
        if c:
            allowed.add(c)
            allowed.add(("https", c[1], 443))

    for setting in ("vision_url", "image_generation_url"):
        endpoint = local_image_endpoint(cfg.get(setting))
        if endpoint:
            allowed.add(_parse_endpoint(endpoint))

    if cfg.get("allow_internet_tools"):
        allowed.add(("https", "en.wikipedia.org", 443))
        if cfg.get("allow_web_search") and secure.has_secret("brave_search_key"):
            allowed.add(("https", "api.search.brave.com", 443))
            allowed.add(("https", "imgs.search.brave.com", 443))
        if cfg.get("github_upload_repo") and secure.has_secret("github_upload_token"):
            allowed.add(("https", "api.github.com", 443))

    return allowed


def check_url(url: str, cfg: dict, purpose: str = "") -> str:
    """Validate that url is on the allowlist; fail closed and audit otherwise."""
    ep = _parse_endpoint(url)
    if not ep or ep not in allowed_endpoints(cfg):
        secure.audit("network_blocked", {"url": str(url)[:200], "purpose": purpose})
        raise NetworkBlockedError(f"Blocked outbound request (not on allowlist): {url}")
    return url


def urlopen(req_or_url, cfg: dict, timeout: int = 20, purpose: str = "", *, allow_redirects=True, bypass_proxy=False):
    """Open an HTTP/HTTPS URL only if both the initial URL and any redirects are allowlisted."""
    url = req_or_url.full_url if isinstance(req_or_url, urllib.request.Request) else str(req_or_url)
    check_url(url, cfg, purpose=purpose)

    class _AllowlistRedirectHandler(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            if not allow_redirects:
                raise NetworkBlockedError("This request does not allow redirects.")
            check_url(newurl, cfg, purpose=f"{purpose}:redirect" if purpose else "redirect")
            return super().redirect_request(req, fp, code, msg, headers, newurl)

    handlers = [_AllowlistRedirectHandler()]
    if bypass_proxy:
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    return opener.open(req_or_url, timeout=timeout)


def check_tcp(host: str, port: int, cfg: dict, purpose: str = "tcp") -> tuple[str, int]:
    """Validate a raw TCP connection (used for NOMAD service status probes)."""
    h = (host or "").strip().lower()
    nomad = _parse_endpoint(cfg.get("nomad_url", "http://127.0.0.1:8080"))
    ollama = _parse_endpoint(cfg.get("ollama_url", "http://127.0.0.1:11434"))
    ok = False
    if nomad and h == nomad[1] and port in NOMAD_PORTS:
        ok = True
    if ollama and h == ollama[1] and port == ollama[2]:
        ok = True
    if not ok:
        secure.audit("network_blocked", {"host": h, "port": port, "purpose": purpose})
        raise NetworkBlockedError(f"Blocked outbound TCP connection to {h}:{port}")
    return host, port


def check_smtp(host: str, cfg: dict) -> str:
    """Validate an SMTP host (only allowed when SMTP credentials are configured)."""
    if not (secure.has_secret("smtp_password") and bool(secure.get_secret("smtp_user"))):
        secure.audit("network_blocked", {"host": host, "purpose": "smtp_unconfigured"})
        raise NetworkBlockedError("Blocked SMTP connection: SMTP is not configured.")
    expected = (secure.get_secret("smtp_host") or "smtp.gmail.com").strip().lower()
    h = (host or "").strip().lower()
    if not h or h != expected:
        secure.audit("network_blocked", {"host": h, "purpose": "smtp_host_mismatch"})
        raise NetworkBlockedError(f"Blocked SMTP connection to non-configured host: {host}")
    return host
