"""VideoSource that answers from `info.json`-shaped fixtures and playlist listings keyed by URL."""

from collections.abc import Iterator
from typing import Any

from mealie_pipeline.adapters.video_source import (
    LoginRequired,
    PlaylistEntry,
    VideoSourceError,
    meta_from_info,
)
from mealie_pipeline.models import VideoMeta


class FakeVideoSource:
    def __init__(
        self,
        infos: dict[str, dict[str, Any]] | None = None,
        pinned: dict[str, str] | None = None,
        playlists: dict[str, list[PlaylistEntry]] | None = None,
    ):
        self.infos = infos or {}
        self.pinned = pinned or {}
        self.playlists = playlists or {}
        self.private: set[str] = set()  # playlist URLs that need a login
        self.calls: list[str] = []

    def metadata(self, url: str) -> VideoMeta:
        self.calls.append(url)
        if url not in self.infos:
            raise VideoSourceError(f"FakeVideoSource has no info for {url}")
        return meta_from_info(self.infos[url])

    def pinned_comments(self, url: str) -> str:
        return self.pinned.get(url, "")

    def list_playlist(self, url: str) -> Iterator[PlaylistEntry]:
        self.calls.append(url)
        if url in self.private:
            raise LoginRequired("This playlist is private")
        if url not in self.playlists:
            raise VideoSourceError(f"FakeVideoSource has no playlist {url}")
        yield from self.playlists[url]
