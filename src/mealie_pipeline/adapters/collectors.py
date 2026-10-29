"""The ListCollector port: one per platform, `enumerate(list_url)` yields the raw entries of a Saved List.

YouTube lists through `VideoSource.list_playlist` (yt-dlp flat extraction). Instagram and Facebook
collectors (tickets 15 and 16) will use the Browser.
"""

from collections.abc import Iterator
from typing import Protocol

from mealie_pipeline.adapters.video_source import LoginRequired, PlaylistEntry, VideoSource
from mealie_pipeline.url_normalizer import normalize_list


class ListCollector(Protocol):
    def enumerate(self, list_url: str) -> Iterator[PlaylistEntry]:
        """Every entry of the list, newest first where the platform orders it. Raises `LoginRequired`."""
        ...


class YouTubeCollector:
    def __init__(self, videos: VideoSource, *, logged_in: bool = False):
        self.videos = videos
        self.logged_in = logged_in  # cookies for yt-dlp arrive with `mp login youtube` (ticket 14)

    def enumerate(self, list_url: str) -> Iterator[PlaylistEntry]:
        normalized = normalize_list(list_url)
        if normalized is not None and normalized.private and not self.logged_in:
            raise LoginRequired(f"{normalized.list_id} is only visible to the logged-in owner")
        yield from self.videos.list_playlist(list_url)
