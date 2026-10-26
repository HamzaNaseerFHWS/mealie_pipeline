"""The WebFetcher port: polite page fetching for Recipe Websites.

`HttpxWebFetcher` sends a real browser User-Agent, honours `robots.txt` for domains that are not on
the allowlist, waits at least `min_delay_seconds` between requests to one domain, and caches every
page on disk by URL so it is fetched once. A blocked page (403/429 or a challenge page) comes back
marked `needs_browser` for the Playwright fallback of ticket 17; it is not an error.
"""

import hashlib
import json
import time
import urllib.robotparser
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx

Blocked = Literal["", "needs_browser", "robots", "error"]

CHALLENGE_MARKERS = (
    "just a moment...",
    "cf-chl",
    "attention required! | cloudflare",
    "checking your browser",
    "enable javascript and cookies to continue",
    "g-recaptcha",
    "px-captcha",
)
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)


@dataclass(frozen=True)
class Page:
    url: str
    final_url: str
    status: int
    html: str = ""
    blocked: Blocked = ""
    detail: str = ""

    @property
    def ok(self) -> bool:
        return not self.blocked and 200 <= self.status < 300 and bool(self.html)


class WebFetcher(Protocol):
    def fetch(self, url: str) -> Page: ...

    def expand(self, url: str) -> str:
        """Follows redirects (HEAD, then GET) and returns the final URL; the input if that fails."""
        ...


def looks_blocked(status: int, html: str) -> bool:
    """403/429, or a 200 that is really a bot-challenge page."""
    if status in (403, 429):
        return True
    head = html[:6000].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)


class HttpxWebFetcher:
    def __init__(
        self,
        cache_dir: Path,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        min_delay_seconds: float = 2.0,
        timeout: float = 20.0,
        robots_allowlist: tuple[str, ...] = (),
        client: httpx.Client | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.cache_dir = cache_dir
        self.min_delay = min_delay_seconds
        self.allowlist = {d.lower() for d in robots_allowlist}
        self.client = client or httpx.Client(
            headers={"User-Agent": user_agent, "Accept-Language": "en,de;q=0.8"},
            timeout=timeout,
            follow_redirects=True,
            http2=False,
        )
        if client is not None:
            self.client.headers["User-Agent"] = user_agent
        self.user_agent = user_agent
        self.clock = clock
        self.sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, urllib.robotparser.RobotFileParser | None] = {}

    # -- politeness -----------------------------------------------------------------------

    def _wait_turn(self, host: str) -> None:
        last = self._last_request.get(host)
        if last is not None:
            remaining = self.min_delay - (self.clock() - last)
            if remaining > 0:
                self.sleep(remaining)
        self._last_request[host] = self.clock()

    def _allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if host in self.allowlist or host.removeprefix("www.") in self.allowlist:
            return True
        if host not in self._robots:
            parser = urllib.robotparser.RobotFileParser()
            try:
                self._wait_turn(host)
                response = self.client.get(f"{parsed.scheme}://{parsed.netloc}/robots.txt")
                if response.status_code == 200:
                    parser.parse(response.text.splitlines())
                    self._robots[host] = parser
                else:
                    self._robots[host] = None  # no robots.txt: everything is allowed
            except httpx.HTTPError:
                self._robots[host] = None
        parser = self._robots[host]
        return True if parser is None else parser.can_fetch(self.user_agent, url)

    # -- cache ----------------------------------------------------------------------------

    def _cache_path(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha256(url.encode("utf-8")).hexdigest() + ".json")

    def _cached(self, url: str) -> Page | None:
        path = self._cache_path(url)
        if path.is_file():
            try:
                return Page(**json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, TypeError):
                return None
        return None

    def _store(self, page: Page) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path(page.url).write_text(json.dumps(asdict(page), ensure_ascii=False), encoding="utf-8")

    # -- port -----------------------------------------------------------------------------

    def fetch(self, url: str) -> Page:
        cached = self._cached(url)
        if cached is not None:
            return cached
        if not self._allowed(url):
            return Page(url, url, 0, blocked="robots", detail="disallowed by robots.txt")
        host = (urlparse(url).hostname or "").lower()
        try:
            self._wait_turn(host)
            response = self.client.get(url)
        except httpx.HTTPError as err:
            return Page(url, url, 0, blocked="error", detail=str(err)[:300])  # not cached: retry later
        html = response.text if "html" in response.headers.get("content-type", "html") else ""
        blocked: Blocked = "needs_browser" if looks_blocked(response.status_code, html) else ""
        page = Page(url, str(response.url), response.status_code, html, blocked)
        self._store(page)
        return page

    def expand(self, url: str) -> str:
        cached = self._cached(url)
        if cached is not None:
            return cached.final_url
        host = (urlparse(url).hostname or "").lower()
        try:
            self._wait_turn(host)
            response = self.client.head(url)
            if response.status_code >= 400 or response.status_code == 405:
                self._wait_turn(host)
                response = self.client.get(url)
            return str(response.url)
        except httpx.HTTPError:
            return url
