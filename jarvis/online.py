"""Optional Brave searches and manually approved GitHub file uploads."""
import base64
import binascii
import hashlib
import html
import json
import re
from pathlib import PureWindowsPath
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit
from urllib.request import Request

from . import coder, net, secure
from .skills import run, skill

SEARCH_HOST = "api.search.brave.com"
GITHUB_HOST = "api.github.com"
_MAX_FILE_BYTES = 5 * 1024 * 1024
_REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
_BRANCH = re.compile(r"[A-Za-z0-9][A-Za-z0-9_./-]*\Z")
_UPLOAD_TYPES = frozenset(
    {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".webp", ".csv", ".json",
     ".py", ".js", ".ts", ".html", ".css", ".c", ".h", ".cpp", ".java", ".rs", ".go"}
)


def _search_ready(cfg):
    return bool(cfg.get("allow_web_search") and secure.has_secret("brave_search_key"))


def _query_text(query):
    query = " ".join(query.split())
    if not query or len(query) > 600 or len(query.split()) > 75:
        raise ValueError("Use a web query of 1 to 75 words and at most 600 characters.")
    return query


def _plain(text, limit):
    return " ".join(html.unescape(re.sub(r"<[^>]*>", "", text)).split())[:limit]


def _request(req, cfg, purpose):
    try:
        with net.urlopen(req, cfg, purpose=purpose, allow_redirects=False) as response:
            data = response.read(256 * 1024 + 1)
            if len(data) <= 256 * 1024:
                return json.loads(data)
    except HTTPError as error:
        if purpose == "github_upload" and error.code in (409, 422):
            raise ValueError("GitHub rejected the upload. Check the branch or whether the path already exists.") from None
        raise ValueError(f"The service returned HTTP {error.code}. Check the credentials and try again.") from None
    except URLError:
        raise ValueError("The service could not be reached.") from None
    raise ValueError("The service returned an oversized response.")


@skill("Search Brave for up-to-date public information. Ask before sending the search terms.",
       params={"query": ("string", "Short public search query, without private details", True)},
       risky=True, internet=True, untrusted=True, available=_search_ready,
       preview=lambda ctx, query: f'send this web search to Brave: "{_query_text(query)}"')
def web_search(ctx, query):
    query = _query_text(query)
    req = Request(
        f"https://{SEARCH_HOST}/res/v1/web/search?" + urlencode({"q": query, "count": 5}),
        headers={"Accept": "application/json", "X-Subscription-Token": secure.get_secret("brave_search_key")},
    )
    results = _request(req, ctx.cfg, "brave_search").get("web", {}).get("results", [])
    lines = []
    for item in results[:5]:
        url = item.get("url", "")
        try:
            parsed = urlsplit(url)
        except ValueError:
            continue
        if parsed.scheme not in ("http", "https") or not parsed.hostname or parsed.username is not None:
            continue
        title = _plain(item.get("title", ""), 160)
        snippet = _plain(item.get("description", ""), 360)
        lines.append(f"{title}\n{url}\n{snippet}")
    return "\n\n".join(lines) or "Brave returned no results for that query."


def _target(cfg):
    repo = cfg.get("github_upload_repo", "").strip()
    branch = cfg.get("github_upload_branch", "main").strip()
    if not _REPO.fullmatch(repo) or not _BRANCH.fullmatch(branch) or ".." in branch:
        raise ValueError("Set a GitHub repository (owner/repo) and branch in Jarvis setup.")
    return repo, branch


def _upload_ready(cfg):
    return bool(cfg.get("github_upload_repo") and secure.has_secret("github_upload_token"))


def _file(cfg, filename):
    relative = PureWindowsPath(filename)
    if any(part.startswith(".") or part.lower() in {"secrets", "node_modules", "__pycache__"}
           for part in relative.parts) or relative.suffix.lower() not in _UPLOAD_TYPES:
        raise ValueError("Select a supported document, image or source file in your Jarvis Code folder.")
    path = coder._safe_path(cfg, filename)
    # Use the resolved path as well so an in-workspace link cannot masquerade as a different file.
    resolved = path.relative_to(coder.code_dir(cfg).resolve())
    if resolved.parts != relative.parts or path.suffix.lower() not in _UPLOAD_TYPES:
        raise ValueError("Select the real file path inside Jarvis Code.")
    if not path.is_file():
        raise ValueError("That file does not exist in Jarvis Code.")
    with path.open("rb") as stream:
        data = stream.read(_MAX_FILE_BYTES + 1)
    if len(data) > _MAX_FILE_BYTES:
        raise ValueError("The GitHub upload limit in Jarvis is 5 MiB per file.")
    return relative.as_posix(), data


def prepare_upload(ctx, filename):
    if not ctx.cfg.get("allow_internet_tools") or not _upload_ready(ctx.cfg):
        return "GitHub upload is disabled. Configure your destination and token in Jarvis setup."
    if ctx.cfg.get("lockdown") or ctx.cfg.get("mode") == "talk":
        return "GitHub upload is unavailable in Lockdown or Talk mode."
    try:
        repo, branch = _target(ctx.cfg)
        name, data = _file(ctx.cfg, filename)
    except (ValueError, OSError) as error:
        return str(error)
    result = run(ctx, "github_upload", {"filename": name, "repo": repo, "branch": branch,
                                        "digest": hashlib.sha256(data).hexdigest(), "size": len(data)})
    if ctx.pending and ctx.pending["name"] == "github_upload":
        return ctx.pending["preview"] + ". Use the HUD Confirm button or type “confirm upload” to proceed."
    return result


def _upload_preview(ctx, filename, repo, branch, digest, size):
    return (f"upload {filename} ({size:,} bytes) to {repo}, branch {branch}, at uploads/{filename}. "
            "This creates a GitHub commit and may make the file public")


@skill("Upload a manually selected workspace file to the configured GitHub repository.",
       params={"filename": ("string", "", True), "repo": ("string", "", True),
               "branch": ("string", "", True), "digest": ("string", "", True),
               "size": ("integer", "", True)},
       risky=True, internet=True, available=_upload_ready, preview=_upload_preview, manual=True)
def github_upload(ctx, filename, repo, branch, digest, size):
    if (repo, branch) != _target(ctx.cfg):
        return "The GitHub destination changed. Start the upload again."
    name, data = _file(ctx.cfg, filename)
    if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
        return "The local file changed. Start the upload again to review it."
    destination = "uploads/" + name
    payload = {"message": f"Add {destination} from Jarvis", "branch": branch,
               "content": base64.b64encode(data).decode("ascii")}
    request = Request(
        f"https://{GITHUB_HOST}/repos/{repo}/contents/{quote(destination, safe='/')}",
        data=json.dumps(payload).encode(), method="PUT",
        headers={"Authorization": "Bearer " + secure.get_secret("github_upload_token"),
                 "Accept": "application/vnd.github+json", "Content-Type": "application/json"},
    )
    result = _request(request, ctx.cfg, "github_upload")
    if not result.get("commit", {}).get("sha"):
        return "GitHub returned no commit. Check the repository before retrying."
    return f"Uploaded to https://github.com/{repo}/blob/{result['commit']['sha']}/{quote(destination, safe='/')}"


@skill("Read the configured GitHub repository metadata and README after approval.",
       params={}, risky=True, internet=True, untrusted=True, manual=True, available=_upload_ready,
       preview=lambda ctx: f"read repository details and README from GitHub for {_target(ctx.cfg)[0]}")
def github_repo_read(ctx):
    repo, _ = _target(ctx.cfg)
    headers = {"Authorization": "Bearer " + secure.get_secret("github_upload_token"),
               "Accept": "application/vnd.github+json"}
    base = f"https://{GITHUB_HOST}/repos/{repo}"
    details = _request(Request(base, headers=headers), ctx.cfg, "github_repo_read")
    readme = _request(Request(base + "/readme", headers=headers), ctx.cfg, "github_repo_read")
    if not isinstance(details, dict) or not isinstance(readme, dict):
        return "GitHub returned invalid repository data."
    encoded = readme.get("content", "")
    if not isinstance(encoded, str) or len(encoded) > 40000 or readme.get("encoding") != "base64":
        return "GitHub README is unavailable or exceeds the reading limit."
    try:
        content = base64.b64decode("".join(encoded.split()), validate=True).decode("utf-8", errors="replace")
    except (ValueError, UnicodeError, binascii.Error):
        return "GitHub README could not be decoded."
    content = content[:12000]
    description = _plain(str(details.get("description") or ""), 300)
    return (f"GitHub repository https://github.com/{repo}\n"
            f"Description: {description}\n"
            f"Default branch: {_plain(str(details.get('default_branch') or ''), 100)}\n"
            f"Visibility: {'private' if details.get('private') else 'public'}\n"
            f"README ({readme.get('path', 'README.md')}, first 12,000 characters):\n{content}")


@skill('Read a public HTTPS source page after the user approves its URL. '
       'Return extracted source text for evidence comparison.',
       params={'url': ('string', 'Public HTTPS URL to read', True)},
       risky=True, internet=True, untrusted=True,
       preview=lambda ctx, url: f'read this public source page: {url}')
def read_source(ctx, url):
    from html.parser import HTMLParser

    class ArticleText(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hidden = 0
            self.parts = []

        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style', 'noscript', 'svg'):
                self.hidden += 1
            if tag in ('p', 'div', 'br', 'h1', 'h2', 'li') and not self.hidden:
                self.parts.append('\n')

        def handle_endtag(self, tag):
            if tag in ('script', 'style', 'noscript', 'svg') and self.hidden:
                self.hidden -= 1

        def handle_data(self, data):
            if not self.hidden:
                self.parts.append(data)

    if not isinstance(url, str):
        raise ValueError('Enter a source URL.')
    text, kind = net.read_public_page(url, ctx.cfg)
    if kind == 'text/html':
        parser = ArticleText()
        parser.feed(text)
        text = ''.join(parser.parts)
    text = '\n'.join(' '.join(line.split()) for line in text.splitlines() if line.strip())
    clipped = len(text) > 12000
    text = text[:12000]
    return f'Source page\n{url}\nExtracted text' + (' (first 12,000 characters)' if clipped else '') + f'\n{text}'


def _source_urls(urls):
    if not isinstance(urls, str):
        raise ValueError('Enter up to three HTTPS source URLs separated by |.')
    selected = [value.strip() for value in urls.split('|') if value.strip()]
    if not 1 <= len(selected) <= 3 or any(not url.startswith('https://') or len(url)>2000 for url in selected):
        raise ValueError('Enter one to three HTTPS source URLs separated by |.')
    return selected


@skill('Compare a claim against up to three public source pages after URL approval.',
       params={'urls':('string','One to three HTTPS URLs separated by |',True),
               'claim':('string','Claim to assess against the supplied sources',True)},
       risky=True, internet=True, untrusted=True,
       preview=lambda ctx, urls, claim: 'read and compare these source pages: ' + ' | '.join(_source_urls(urls)))
def check_sources(ctx, urls, claim):
    selected = _source_urls(urls)
    budget = min(12000, int(ctx.cfg.get('num_ctx',8192)) * 2)
    per_source = max(700, budget // len(selected))
    excerpts = []
    for url in selected:
        if ctx.cancelled is not None and ctx.cancelled.is_set():
            return 'Stopped by the user.'
        try:
            excerpts.append(read_source(ctx,url)[:per_source])
        except (ValueError, OSError) as error:
            excerpts.append(f'Source could not be read: {url}\n{error}')
    return '\n\n'.join(excerpts)
