"""URL Normalizer (pure): any supported URL -> `(platform, video_id, canonical_url)` or None.

Strips tracking parameters, folds the many URL shapes of one Video into one Video Key, and also
provides `normalize_website` for ordinary recipe-page links. Facebook `fb.watch` and `/share/`
short links need a redirect to resolve; the caller does that and then normalizes the result.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlencode, urlparse

_YT_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_IG_CODE = re.compile(r"^[A-Za-z0-9_-]{5,}$")
_FB_ID = re.compile(r"^\d{5,}$")
_YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com"}
_INSTAGRAM_HOSTS = {"instagram.com", "www.instagram.com", "m.instagram.com"}
_FACEBOOK_HOSTS = {
    "facebook.com",
    "www.facebook.com",
    "m.facebook.com",
    "web.facebook.com",
    "mbasic.facebook.com",
}
_TRACKING_EXACT = {
    "si", "igsh", "igshid", "fbclid", "mibextid", "gclid", "dclid", "msclkid", "yclid", "ref", "ref_src",
    "feature", "pp", "spm", "mc_cid", "mc_eid", "_ga", "s", "sfnsn", "app", "rdid", "share_url",
}  # fmt: skip
_TRACKING_PREFIXES = ("utm_", "fb_", "ga_", "pk_", "hsa_")


@dataclass(frozen=True)
class NormalizedUrl:
    platform: str
    video_id: str
    canonical_url: str

    @property
    def video_key(self) -> str:
        return f"{self.platform}:{self.video_id}"


def _query(url_query: str) -> dict[str, str]:
    return dict(parse_qsl(url_query, keep_blank_values=True))


def normalize(url: str) -> NormalizedUrl | None:
    """Any supported Video URL -> platform, id and canonical URL; None when unsupported."""
    parsed = urlparse(url.strip())
    host = (parsed.hostname or "").lower()
    parts = [p for p in parsed.path.split("/") if p]
    query = _query(parsed.query)

    if host == "youtu.be" and parts and _YT_ID.match(parts[0]):
        return _youtube(parts[0])
    if host in _YOUTUBE_HOSTS:
        video_id = query.get("v", "") if parsed.path == "/watch" else ""
        if len(parts) == 2 and parts[0] in {"shorts", "embed", "live", "v"}:
            video_id = parts[1]
        if _YT_ID.match(video_id):
            return _youtube(video_id)
    if host in _INSTAGRAM_HOSTS:
        # /p/CODE, /reel/CODE, /reels/CODE, /tv/CODE, optionally behind /<username>/
        for index, part in enumerate(parts[:-1]):
            if part in {"p", "reel", "reels", "tv"} and index <= 1 and _IG_CODE.match(parts[index + 1]):
                code = parts[index + 1]
                return NormalizedUrl("instagram", code, f"https://www.instagram.com/p/{code}/")
    if host in _FACEBOOK_HOSTS:
        video_id = ""
        if len(parts) == 2 and parts[0] == "reel":
            video_id = parts[1]
        elif parsed.path.rstrip("/") == "/watch":
            video_id = query.get("v", "")
        elif len(parts) >= 3 and parts[-2] == "videos":
            video_id = parts[-1]
        elif parsed.path == "/video.php":
            video_id = query.get("v", "")
        if _FB_ID.match(video_id):
            return NormalizedUrl("facebook", video_id, f"https://www.facebook.com/watch/?v={video_id}")
    return None


def _youtube(video_id: str) -> NormalizedUrl:
    return NormalizedUrl("youtube", video_id, f"https://www.youtube.com/watch?v={video_id}")


def _is_tracking(name: str) -> bool:
    lowered = name.lower()
    return lowered in _TRACKING_EXACT or lowered.startswith(_TRACKING_PREFIXES)


def normalize_website(url: str) -> str | None:
    """A recipe-page link as a comparable key: no scheme, no `www.`/`m.`, no fragment, no trailing
    slash, no tracking parameters (the remaining parameters are sorted). None for garbage."""
    text = url.strip()
    if not text or " " in text:
        return None
    if "://" not in text:
        text = "https://" + text
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or "." not in host:
        return None
    host = host.removeprefix("www.").removeprefix("m.")
    path = re.sub(r"/{2,}", "/", parsed.path).rstrip("/")
    kept = sorted((k, v) for k, v in _query(parsed.query).items() if not _is_tracking(k))
    return host + path + (f"?{urlencode(kept)}" if kept else "")
