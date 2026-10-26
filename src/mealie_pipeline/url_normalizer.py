"""URL Normalizer (pure). Only YouTube is handled so far; later tickets add the other platforms."""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}


@dataclass(frozen=True)
class NormalizedUrl:
    platform: str
    video_id: str
    canonical_url: str

    @property
    def video_key(self) -> str:
        return f"{self.platform}:{self.video_id}"


def normalize(url: str) -> NormalizedUrl | None:
    """Any supported Video URL -> platform, id and canonical URL; None when unsupported."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    video_id: str | None = None
    if host == "youtu.be":
        video_id = parsed.path.strip("/").split("/")[0]
    elif host in _YOUTUBE_HOSTS:
        parts = [p for p in parsed.path.split("/") if p]
        if parsed.path == "/watch":
            video_id = (parse_qs(parsed.query).get("v") or [""])[0]
        elif len(parts) == 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            video_id = parts[1]
    if video_id and _ID.match(video_id):
        return NormalizedUrl("youtube", video_id, f"https://www.youtube.com/watch?v={video_id}")
    return None
