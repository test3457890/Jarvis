"""Optional Brave searches and manually approved GitHub file uploads."""
import base64
import binascii
import hashlib
import html
import json
import math
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


def _issue_repo(ctx, repo):
    if not isinstance(repo, str) or repo != _target(ctx.cfg)[0]:
        raise ValueError("The GitHub repository changed. Start again and review the new destination.")
    return f"https://{GITHUB_HOST}/repos/{repo}"


def _github_headers():
    return {"Authorization": "Bearer " + secure.get_secret("github_upload_token"),
            "Accept": "application/vnd.github+json", "Content-Type": "application/json"}


@skill("List up to 20 issues from the configured repository after approval.",
       params={"repo":("string", "Configured repository", True)}, risky=True, internet=True,
       untrusted=True, manual=True, available=_upload_ready,
       preview=lambda ctx, repo: f"read up to 20 open issue records from GitHub repository {repo}")
def github_issues_read(ctx, repo):
    base = _issue_repo(ctx, repo)
    rows = _request(Request(base + "/issues?state=open&per_page=20", headers=_github_headers()), ctx.cfg, "github_issues_read")
    if not isinstance(rows, list):
        raise ValueError("GitHub returned invalid issue data.")
    lines = []
    for item in rows[:20]:
        if not isinstance(item, dict) or "pull_request" in item:
            continue
        number = item.get("number")
        if type(number) is not int or number < 1:
            continue
        lines.append(f"#{number}: {_plain(str(item.get('title') or ''), 300)}\nhttps://github.com/{repo}/issues/{number}")
    return "Open GitHub issues (first page; pull requests excluded):\n" + ("\n\n".join(lines) or "No issues in this page.")


def _issue_number(number):
    if type(number) is not int or not 1 <= number <= 2_147_483_647:
        raise ValueError("Use a positive GitHub issue number.")
    return number


@skill("Read one configured-repository issue and up to 10 comments after approval.",
       params={"repo":("string", "Configured repository", True), "number":("integer", "Issue number", True)},
       risky=True, internet=True, untrusted=True, manual=True, available=_upload_ready,
       preview=lambda ctx, repo, number: f"read GitHub issue {repo}#{_issue_number(number)} and its first 10 comments")
def github_issue_read(ctx, repo, number):
    base = _issue_repo(ctx, repo) + f"/issues/{_issue_number(number)}"
    item = _request(Request(base, headers=_github_headers()), ctx.cfg, "github_issue_read")
    comments = _request(Request(base + "/comments?per_page=10", headers=_github_headers()), ctx.cfg, "github_issue_read")
    if not isinstance(item, dict) or not isinstance(comments, list):
        raise ValueError("GitHub returned invalid issue data.")
    lines = [f"https://github.com/{repo}/issues/{number}", _plain(str(item.get("title") or ""), 300),
             f"State: {_plain(str(item.get('state') or ''), 30)}", str(item.get("body") or "")[:8000]]
    for comment in comments[:10]:
        if not isinstance(comment, dict):
            continue
        user = comment.get("user") or {}
        author = _plain(str(user.get("login") or "unknown"), 100) if isinstance(user, dict) else "unknown"
        lines.append(f"Comment by {author}:\n{str(comment.get('body') or '')[:1000]}")
    return "\n\n".join(lines)[:20000]


@skill("List up to 20 open pull requests from the configured repository after approval.",
       params={"repo": ("string", "Configured repository", True)}, risky=True, internet=True,
       untrusted=True, manual=True, available=_upload_ready,
       preview=lambda ctx, repo: f"read up to 20 open pull requests from GitHub repository {repo}")
def github_prs_read(ctx, repo):
    base = _issue_repo(ctx, repo)
    rows = _request(Request(base + "/pulls?state=open&per_page=20", headers=_github_headers()), ctx.cfg, "github_prs_read")
    if not isinstance(rows, list):
        raise ValueError("GitHub returned invalid pull request data.")
    lines = []
    for item in rows[:20]:
        if not isinstance(item, dict):
            continue
        number = item.get("number")
        if type(number) is not int or number < 1:
            continue
        head = (item.get("head") or {}).get("ref", "")
        base_ref = (item.get("base") or {}).get("ref", "")
        lines.append(
            f"PR #{number}: {_plain(str(item.get('title') or ''), 300)} ({_plain(str(head), 60)} -> {_plain(str(base_ref), 60)})\n"
            f"https://github.com/{repo}/pull/{number}"
        )
    return "Open GitHub pull requests (first page):\n" + ("\n\n".join(lines) or "No open pull requests in this page.")


def _issue_draft(title, body):
    from .memory import redact
    if (not isinstance(title, str) or not 1 <= len(title.strip()) <= 120
            or not isinstance(body, str) or not 1 <= len(body.strip()) <= 6000):
        raise ValueError("Use an issue title of 1-120 characters and a body of 1-6,000 characters.")
    if redact(title) != title or redact(body) != body:
        raise ValueError("Remove credentials and sensitive numbers before publishing an issue.")
    return title.strip(), body.strip()


def _issue_preview(ctx, repo, title, body):
    _issue_repo(ctx, repo)
    title, body = _issue_draft(title, body)
    return (f"create a GitHub issue in {repo}. Repository readers can see this text.\n"
            f"Title: {title}\nBody:\n{body}")


@skill("Create an explicitly drafted issue in the configured repository after approval.",
       params={"repo":("string", "", True), "title":("string", "", True), "body":("string", "", True)},
       risky=True, internet=True, manual=True, available=_upload_ready, preview=_issue_preview)
def github_issue_create(ctx, repo, title, body):
    base = _issue_repo(ctx, repo)
    title, body = _issue_draft(title, body)
    request = Request(base + "/issues", headers=_github_headers(), method="POST",
                      data=json.dumps({"title":title, "body":body}).encode())
    try:
        result = _request(request, ctx.cfg, "github_issue_create")
    except (ValueError, OSError):
        return (f"GitHub did not confirm issue creation. Check https://github.com/{repo}/issues "
                "before trying again; the request may already have created an issue. No retry was made.")
    number = result.get("number") if isinstance(result, dict) else None
    if type(number) is not int or number < 1:
        return f"GitHub returned no issue number. Check https://github.com/{repo}/issues before retrying."
    return f"Created GitHub issue https://github.com/{repo}/issues/{number}"


def _feed_link(value, source):
    from urllib.parse import urljoin
    if not isinstance(value, str) or len(value) > 2000 or any(ord(c) < 33 for c in value):
        return ""
    try:
        value = urljoin(source, value)
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
                or parsed.password is not None or parsed.port not in (None, 443)):
            return ""
        return value
    except ValueError:
        return ""


def parse_feed(text, source):
    """Read bounded RSS/Atom data, never XML declarations for entities or DTDs."""
    import xml.etree.ElementTree as ET
    if (not isinstance(text, str) or len(text) > 1_000_000 or '\x00' in text
            or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', text, re.I)):
        raise ValueError("Feeds must be at most 1 MB and cannot contain NUL characters, entities or a DTD.")
    try:
        root = ET.fromstring(text)
    except (ET.ParseError, RecursionError):
        raise ValueError("The source did not provide a valid RSS or Atom feed.") from None
    local = lambda element: str(element.tag).rsplit('}', 1)[-1].lower()
    if local(root) not in ("rss", "feed", "rdf"):
        raise ValueError("The source is not an RSS or Atom feed.")
    count = 0
    for element in root.iter():
        count += 1
        if count > 10000:
            raise ValueError("The feed contains too many XML elements.")
    heading = next((element for element in root if local(element) == "channel"), root)
    title = next((_plain(''.join(e.itertext()), 200) for e in heading if local(e) == "title"), "")
    items = []
    for entry in root.iter():
        if local(entry) not in ("item", "entry"):
            continue
        fields, link = {}, ""
        for child in entry:
            tag = local(child)
            if tag == "link":
                relation = child.get("rel", "alternate")
                if relation == "alternate":
                    candidate = child.get("href") or ''.join(child.itertext()).strip()
                    link = _feed_link(candidate, source) or link
            elif tag in ("title", "description", "summary", "content", "pubdate", "published", "updated", "date"):
                fields.setdefault(tag, _plain(''.join(child.itertext()), 500))
        if not fields.get("title") and not link:
            continue
        items.append({"title":fields.get("title", "Untitled entry")[:200], "url":link,
                      "summary":(fields.get("summary") or fields.get("description") or fields.get("content") or "")[:500],
                      "reported_date":(fields.get("published") or fields.get("pubdate") or fields.get("updated") or fields.get("date") or "")[:100]})
        if len(items) == 20:
            break
    return {"title":title or "Selected feed", "source":source, "items":items}


@skill("Read up to 20 RSS or Atom feed entries after approving the exact public HTTPS URL.",
       params={"url":("string", "Public HTTPS feed URL", True)}, risky=True, internet=True,
       untrusted=True, manual=True, preview=lambda ctx, url: f"read RSS/Atom entries from this exact URL: {url}")
def feed_read(ctx, url):
    text, _ = net.read_public_page(url, ctx.cfg, content_types=(
        "application/rss+xml", "application/atom+xml", "application/rdf+xml", "application/xml", "text/xml", "text/plain"))
    feed = parse_feed(text, url)
    lines = [f"Feed: {feed['title']}", f"Source: {url}", "Dates and summaries below are reported by the feed, not independently verified."]
    for index, item in enumerate(feed["items"], 1):
        lines.append(f"[{index}] {item['title']}\n{item['url']}\nReported date: {item['reported_date'] or 'Not supplied'}\n{item['summary']}")
    if not feed["items"]:
        lines.append("No usable entries were found in the feed.")
    return '\n\n'.join(lines)[:20000]


def _weather_coordinates(latitude, longitude):
    if isinstance(latitude, bool) or isinstance(longitude, bool):
        raise ValueError("Use numeric latitude and longitude.")
    try:
        lat, lon = float(latitude), float(longitude)
    except (ValueError, TypeError, OverflowError):
        raise ValueError("Use numeric latitude and longitude.") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Latitude must be -90 to 90 and longitude -180 to 180.")
    return f"{lat:.4f}", f"{lon:.4f}"


def _weather_preview(ctx, latitude, longitude):
    lat, lon = _weather_coordinates(latitude, longitude)
    return (f"send coordinates {lat}, {lon} to api.weather.gov/points and read its official grid forecast "
            "from api.weather.gov. This service covers supported US locations; no GPS is accessed")


@skill("Read the National Weather Service forecast for explicitly supplied coordinates after approval.",
       params={"latitude":("number", "Latitude", True), "longitude":("number", "Longitude", True)},
       risky=True, internet=True, untrusted=True, manual=True, preview=_weather_preview)
def weather_read(ctx, latitude, longitude):
    lat, lon = _weather_coordinates(latitude, longitude)
    types = ("application/geo+json", "application/ld+json", "application/json")
    points = f"https://api.weather.gov/points/{lat},{lon}"
    text, _ = net.read_public_page(points, ctx.cfg, content_types=types)
    try:
        data = json.loads(text)
        forecast_url = data["properties"]["forecast"]
    except (ValueError, TypeError, KeyError, RecursionError):
        raise ValueError("The weather service did not return a supported forecast grid.") from None
    if not isinstance(forecast_url, str):
        raise ValueError("The weather service returned an invalid forecast address.")
    try:
        parsed = urlsplit(forecast_url)
        valid = (parsed.scheme == "https" and parsed.hostname == "api.weather.gov" and parsed.port in (None,443)
                 and parsed.username is None and parsed.password is None and not parsed.query and not parsed.fragment
                 and re.fullmatch(r"/gridpoints/[A-Za-z]{3}/\d{1,5},\d{1,5}/forecast", parsed.path))
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("The weather service returned a forecast outside the approved NWS grid path.")
    if ctx.cfg.get("lockdown") or not ctx.cfg.get("allow_internet_tools") or (ctx.cancelled is not None and ctx.cancelled.is_set()):
        return "Weather request stopped before the forecast read."
    text, _ = net.read_public_page(forecast_url, ctx.cfg, content_types=types)
    try:
        forecast = json.loads(text)
        properties = forecast["properties"]
        periods = properties["periods"]
        if not isinstance(properties, dict) or not isinstance(periods, list):
            raise ValueError
    except (ValueError, KeyError, TypeError, RecursionError):
        raise ValueError("The weather service returned invalid forecast data.") from None
    lines = [f"National Weather Service forecast for supplied coordinates {lat}, {lon}", f"Source: {forecast_url}",
             f"Service update: {_plain(str(properties.get('updated') or 'Not supplied'), 100)}"]
    for period in periods[:8]:
        if not isinstance(period, dict):
            raise ValueError("The weather service returned an invalid forecast period.")
        temperature, unit = period.get("temperature"), period.get("temperatureUnit")
        if type(temperature) not in (int,float) or unit not in ("F","C"):
            raise ValueError("The forecast temperature or units are missing; no reading was substituted.")
        if not math.isfinite(temperature) or not -200 <= temperature <= 200:
            raise ValueError("The weather service returned an invalid temperature.")
        lines.append(f"{_plain(str(period.get('name') or 'Forecast period'), 100)} ({_plain(str(period.get('startTime') or 'Time not supplied'), 80)}): "
                     f"{temperature} {unit}; {_plain(str(period.get('shortForecast') or 'Description not supplied'), 300)}; "
                     f"wind {_plain(str(period.get('windSpeed') or 'not supplied'), 80)} {_plain(str(period.get('windDirection') or ''), 30)}")
    if not periods:
        lines.append("The service returned no forecast periods. No weather readings are available.")
    return '\n\n'.join(lines)


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
