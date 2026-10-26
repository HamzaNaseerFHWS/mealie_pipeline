"""Fixture-backed WebFetcher: pages by URL, redirects by URL; every request is recorded."""

from mealie_pipeline.adapters.web import Page


class FakeWebFetcher:
    def __init__(
        self,
        pages: dict[str, str] | None = None,
        *,
        redirects: dict[str, str] | None = None,
        blocked: dict[str, str] | None = None,
    ):
        self.pages = pages or {}
        self.redirects = redirects or {}
        self.blocked = blocked or {}  # url -> "needs_browser" | "robots"
        self.fetched: list[str] = []
        self.expanded: list[str] = []

    def _resolve(self, url: str) -> str:
        seen = 0
        while url in self.redirects and seen < 5:
            url, seen = self.redirects[url], seen + 1
        return url

    def expand(self, url: str) -> str:
        self.expanded.append(url)
        return self._resolve(url)

    def fetch(self, url: str) -> Page:
        self.fetched.append(url)
        final = self._resolve(url)
        if final in self.blocked or url in self.blocked:
            reason = self.blocked.get(final) or self.blocked[url]
            return Page(url, final, 403 if reason == "needs_browser" else 0, blocked=reason)  # type: ignore[arg-type]
        if final not in self.pages:
            return Page(url, final, 404)
        return Page(url, final, 200, self.pages[final])
