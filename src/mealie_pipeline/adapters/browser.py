"""The Browser port: real Chrome through Playwright, on the pipeline's own persistent profile.

Thin on purpose and verified by hand on the laptop (ticket 14); tests use `FakeBrowser`. It never
reads the user's everyday Chrome profile, never sees a password and stops on a stop signal.
`fetch_rendered` (ticket 17) reads public pages that need a real browser: link-in-bio pages and
recipe pages that came back blocked or JS-only. A challenge page is returned as it is, never solved.

Playwright's sync API only works on the thread that started it, while `scrape` may run on several
workers, so every call runs on one browser thread.
"""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, TypeVar

from mealie_pipeline.errors import NeedsHumanLogin
from mealie_pipeline.sessions import PlatformProfile, stop_signal


@dataclass(frozen=True)
class RenderedPage:
    url: str  # after redirects
    status: int
    title: str
    html: str

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300 and bool(self.html)


T = TypeVar("T")


class Browser(Protocol):
    def show(self, url: str) -> None:
        """Opens `url` in the visible window, without any checks (the login page itself)."""
        ...

    def cookies(self) -> list[dict[str, Any]]:
        """Every cookie of the pipeline profile, as Playwright returns them."""
        ...

    def open(self, url: str, profile: PlatformProfile) -> RenderedPage:
        """Loads a platform page. Raises `NeedsHumanLogin` on a login wall, checkpoint or rate limit."""
        ...

    def fetch_rendered(self, url: str) -> RenderedPage:
        """Loads a public page and returns its rendered HTML (status 0 when it could not be loaded)."""
        ...

    def close(self) -> None: ...


def checked(page: RenderedPage, profile: PlatformProfile) -> RenderedPage:
    kind = "rate_limit" if page.status == 429 else stop_signal(profile, page.url, page.title, page.html)
    if kind is not None:
        raise NeedsHumanLogin(profile.name, kind, page.url)
    return page


class PlaywrightBrowser:
    def __init__(self, profile_dir: Path, *, headless: bool = False, timeout_ms: int = 30_000):
        self.profile_dir = profile_dir
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright: Any = None
        self._context: Any = None
        self._thread = ThreadPoolExecutor(max_workers=1, thread_name_prefix="browser")

    def _on_thread(self, work: Callable[[], T]) -> T:
        return self._thread.submit(work).result()

    def _page(self) -> Any:
        if self._context is None:
            from playwright.sync_api import sync_playwright  # lazy: slow import, and tests never launch it

            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._playwright = sync_playwright().start()
            self._context = self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir), channel="chrome", headless=self.headless
            )
            self._context.set_default_timeout(self.timeout_ms)
        pages = self._context.pages
        return pages[0] if pages else self._context.new_page()

    def show(self, url: str) -> None:
        self._on_thread(lambda: self._page().goto(url))

    def cookies(self) -> list[dict[str, Any]]:
        def read() -> list[dict[str, Any]]:
            self._page()
            return [dict(c) for c in self._context.cookies()]

        return self._on_thread(read)

    def _load(self, url: str) -> RenderedPage:
        page = self._page()
        response = page.goto(url, wait_until="domcontentloaded")
        return RenderedPage(page.url, response.status if response else 0, page.title(), page.content())

    def open(self, url: str, profile: PlatformProfile) -> RenderedPage:
        return checked(self._on_thread(lambda: self._load(url)), profile)

    def fetch_rendered(self, url: str) -> RenderedPage:
        def render() -> RenderedPage:
            from playwright.sync_api import Error as PlaywrightError

            try:
                page = self._page()
                response = page.goto(url, wait_until="domcontentloaded")
                try:  # link-in-bio buttons and recipe cards are often drawn after the first paint
                    page.wait_for_load_state("networkidle", timeout=10_000)
                except PlaywrightError:
                    pass
                status = response.status if response else 0
                return RenderedPage(page.url, status, page.title(), page.content())
            except PlaywrightError:  # unreachable, timed out: the caller treats it like a failed fetch
                return RenderedPage(url, 0, "", "")

        return self._on_thread(render)

    def close(self) -> None:
        def stop() -> None:
            if self._context is not None:
                self._context.close()
                self._playwright.stop()
            self._context = self._playwright = None

        self._on_thread(stop)
