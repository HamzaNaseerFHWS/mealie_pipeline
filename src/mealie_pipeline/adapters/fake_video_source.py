"""VideoSource that answers from `info.json`-shaped fixtures and playlist listings keyed by URL."""

from collections.abc import Iterator
from pathlib import Path
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
        subtitles: dict[str, str] | None = None,
    ):
        self.infos = infos or {}
        self.pinned = pinned or {}
        self.playlists = playlists or {}
        self.subtitle_texts = subtitles or {}
        self.subtitle_calls: list[str] = []
        self.private: set[str] = set()  # playlist URLs that need a login (a cookie file)
        self.cookiefiles: list[Path] = []  # every cookie file a listing was given
        self.calls: list[str] = []
        self.frame_image: bytes | None = None  # what `frame` saves; None means no frame can be grabbed
        self.frame_calls: list[tuple[str, float]] = []

    def frame(self, url: str, at_s: float, dest: Path) -> Path | None:
        self.frame_calls.append((url, at_s))
        if self.frame_image is None:
            return None
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(self.frame_image)
        return dest

    def metadata(self, url: str) -> VideoMeta:
        self.calls.append(url)
        if url not in self.infos:
            raise VideoSourceError(f"FakeVideoSource has no info for {url}")
        return meta_from_info(self.infos[url])

    def pinned_comments(self, url: str) -> str:
        return self.pinned.get(url, "")

    def subtitles(self, url: str) -> str:
        self.subtitle_calls.append(url)
        return self.subtitle_texts.get(url, "")

    def list_playlist(self, url: str, cookiefile: Path | None = None) -> Iterator[PlaylistEntry]:
        self.calls.append(url)
        if cookiefile is not None:
            self.cookiefiles.append(cookiefile)
        if url in self.private and cookiefile is None:
            raise LoginRequired("This playlist is private")
        if url not in self.playlists:
            raise VideoSourceError(f"FakeVideoSource has no playlist {url}")
        yield from self.playlists[url]
