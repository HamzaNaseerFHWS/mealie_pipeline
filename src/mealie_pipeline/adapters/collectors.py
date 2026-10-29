"""The ListCollector port: one per platform, `enumerate(list_url)` yields the raw entries of a Saved List.

YouTube lists through `VideoSource.list_playlist` (yt-dlp flat extraction). Instagram and Facebook
collectors (tickets 15 and 16) will use the Browser.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Protocol

from mealie_pipeline.adapters.video_source import LoginRequired, PlaylistEntry, VideoSource
from mealie_pipeline.url_normalizer import normalize_list


class ListCollector(Protocol):
    def enumerate(self, list_url: str) -> Iterator[PlaylistEntry]:
        """Every entry of the list, newest first where the platform orders it. Raises `LoginRequired`."""
        ...


class YouTubeCollector:
    def __init__(self, videos: VideoSource, *, cookiefile: Path | None = None):
        self.videos = videos
        self.cookiefile = cookiefile  # `secrets/cookies.txt`, written by `mp login youtube`

    def enumerate(self, list_url: str) -> Iterator[PlaylistEntry]:
        cookies = self.cookiefile if self.cookiefile is not None and self.cookiefile.is_file() else None
        normalized = normalize_list(list_url)
        if normalized is not None and normalized.private and cookies is None:
            raise LoginRequired(f"{normalized.list_id} is only visible to the logged-in owner")
        yield from self.videos.list_playlist(list_url, cookies)
