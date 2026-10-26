"""VideoSource that answers from `info.json`-shaped fixtures keyed by URL."""

from typing import Any

from mealie_pipeline.adapters.video_source import VideoSourceError, meta_from_info
from mealie_pipeline.models import VideoMeta


class FakeVideoSource:
    def __init__(self, infos: dict[str, dict[str, Any]] | None = None):
        self.infos = infos or {}
        self.calls: list[str] = []

    def metadata(self, url: str) -> VideoMeta:
        self.calls.append(url)
        if url not in self.infos:
            raise VideoSourceError(f"FakeVideoSource has no info for {url}")
        return meta_from_info(self.infos[url])
