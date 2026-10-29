"""The Browser port: real Chrome through Playwright, on the pipeline's own persistent profile.

Thin on purpose and verified by hand on the laptop (ticket 14); tests use `FakeBrowser`. It never
reads the user's everyday Chrome profile, never sees a password and stops on a stop signal.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mealie_pipeline.errors import NeedsHumanLogin
from mealie_pipeline.sessions import PlatformProfile, stop_signal


@dataclass(frozen=True)
class RenderedPage:
    url: str  # after redirects
    status: int
    title: str
    html: str


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
        self._page().goto(url)

    def cookies(self) -> list[dict[str, Any]]:
        self._page()
        return [dict(c) for c in self._context.cookies()]

    def open(self, url: str, profile: PlatformProfile) -> RenderedPage:
        page = self._page()
        response = page.goto(url, wait_until="domcontentloaded")
        rendered = RenderedPage(page.url, response.status if response else 0, page.title(), page.content())
        return checked(rendered, profile)

    def close(self) -> None:
        if self._context is not None:
            self._context.close()
            self._playwright.stop()
        self._context = self._playwright = None
