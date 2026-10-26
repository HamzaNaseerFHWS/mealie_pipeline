"""The ImageDownloader port: fetches thumbnail bytes. Mealie never scrapes a Video page itself."""

from typing import Protocol

import httpx


class ImageDownloader(Protocol):
    def get(self, url: str) -> tuple[int, bytes]:
        """`(status_code, body)`; a connection failure counts as status 0 with an empty body."""
        ...


class HttpImageDownloader:
    def __init__(self, timeout: float = 20):
        self.timeout = timeout

    def get(self, url: str) -> tuple[int, bytes]:
        try:
            response = httpx.get(url, timeout=self.timeout, follow_redirects=True)
        except httpx.HTTPError:
            return 0, b""
        return response.status_code, response.content


class FakeImageDownloader:
    """Serves `files[url] = bytes`; anything else is a 404."""

    def __init__(self, files: dict[str, bytes] | None = None):
        self.files = files or {}
        self.requests: list[str] = []

    def get(self, url: str) -> tuple[int, bytes]:
        self.requests.append(url)
        if url in self.files:
            return 200, self.files[url]
        return 404, b""
