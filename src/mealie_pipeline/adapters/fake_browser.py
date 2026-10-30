"""Scripted Browser: cookie snapshots in order (the last one repeats) and pages by URL.

`open` and `fetch_rendered` share `pages`; an unknown URL renders as status 0 in `fetch_rendered`."""

from typing import Any

from mealie_pipeline.adapters.browser import RenderedPage, checked
from mealie_pipeline.sessions import PlatformProfile


class FakeBrowser:
    def __init__(
        self,
        cookie_script: list[list[dict[str, Any]]] | None = None,
        pages: dict[str, RenderedPage] | None = None,
    ):
        self.cookie_script = cookie_script or [[]]
        self.pages = pages or {}
        self.shown: list[str] = []
        self.opened: list[str] = []
        self.rendered: list[str] = []  # every `fetch_rendered` call
        self.closed = False
        self._reads = 0

    def show(self, url: str) -> None:
        self.shown.append(url)

    def cookies(self) -> list[dict[str, Any]]:
        snapshot = self.cookie_script[min(self._reads, len(self.cookie_script) - 1)]
        self._reads += 1
        return [dict(c) for c in snapshot]

    def open(self, url: str, profile: PlatformProfile) -> RenderedPage:
        self.opened.append(url)
        return checked(self.pages[url], profile)

    def fetch_rendered(self, url: str) -> RenderedPage:
        self.rendered.append(url)
        return self.pages.get(url, RenderedPage(url, 0, "", ""))

    def close(self) -> None:
        self.closed = True
