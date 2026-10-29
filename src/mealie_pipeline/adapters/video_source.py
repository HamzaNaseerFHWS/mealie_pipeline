"""The VideoSource port: yt-dlp as a library. `metadata`, `pinned_comments` and `list_playlist`."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from mealie_pipeline.models import VideoMeta


class VideoSourceError(Exception):
    """The platform refused or the video could not be read."""


class LoginRequired(VideoSourceError):
    """The list or Video is private: only a logged-in session (`mp login <platform>`) can read it."""


# Phrases in yt-dlp's errors that mean "log in first", not "this is broken".
LOGIN_HINTS = (
    "private",
    "sign in",
    "login required",
    "log in",
    "requires authentication",
    "members-only",
    "playlist does not exist",  # what YouTube says about someone else's private playlist
)


def is_login_error(message: str) -> bool:
    lowered = message.lower()
    return any(hint in lowered for hint in LOGIN_HINTS)


@dataclass(frozen=True)
class PlaylistEntry:
    """One item of a flat playlist listing: the URL plus the metadata that comes for free."""

    url: str
    title: str | None = None
    channel: str | None = None
    duration_s: float | None = None


class VideoSource(Protocol):
    def metadata(self, url: str) -> VideoMeta:
        """Title, description, thumbnail and so on, without downloading the video."""
        ...

    def pinned_comments(self, url: str) -> str:
        """Text of the creator's own pinned comment(s), or "" (many creators post the recipe there)."""
        ...

    def list_playlist(self, url: str, cookiefile: Path | None = None) -> Iterator[PlaylistEntry]:
        """Every entry of a playlist, without downloading anything. Raises `LoginRequired`.

        `cookiefile` is the `secrets/cookies.txt` of `mp login`, for private lists."""
        ...


def entry_from_flat(item: dict[str, Any]) -> PlaylistEntry | None:
    """Maps one `extract_flat` playlist entry; None when it has no usable URL or id."""
    url = item.get("url") or item.get("webpage_url") or ""
    if not url and item.get("id"):
        url = f"https://www.youtube.com/watch?v={item['id']}"
    if not url:
        return None
    return PlaylistEntry(
        url=url,
        title=item.get("title"),
        channel=item.get("channel") or item.get("uploader"),
        duration_s=item.get("duration"),
    )


def meta_from_info(info: dict[str, Any]) -> VideoMeta:
    """Maps a yt-dlp `info` dict (or `.info.json` content) to `VideoMeta`."""
    return VideoMeta(
        title=info.get("title") or "",
        description=info.get("description") or "",
        uploader=info.get("uploader") or info.get("channel") or "",
        uploader_id=info.get("uploader_id") or info.get("channel_id") or "",
        duration_s=info.get("duration"),
        upload_date=info.get("upload_date"),
        thumbnail=info.get("thumbnail"),
        webpage_url=info.get("webpage_url") or "",
    )


class YtDlpVideoSource:
    def metadata(self, url: str) -> VideoMeta:
        import yt_dlp  # imported lazily: it is slow to import and not needed by most tests
        from yt_dlp.utils import DownloadError

        options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        try:
            with yt_dlp.YoutubeDL(options) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(url, download=False)
        except DownloadError as err:
            raise VideoSourceError(str(err)) from err
        if not isinstance(info, dict):
            raise VideoSourceError(f"yt-dlp returned nothing for {url}")
        return meta_from_info(dict(info))

    def pinned_comments(self, url: str) -> str:
        import yt_dlp

        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "getcomments": True,
            "extractor_args": {"youtube": {"max_comments": ["20", "0", "0", "0"], "comment_sort": ["top"]}},
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(url, download=False)
        except Exception:  # comments are a bonus Source: never fail the Video over them
            return ""
        comments = (info or {}).get("comments") or []
        return "\n\n".join(
            str(c.get("text") or "") for c in comments if c.get("is_pinned") and c.get("author_is_uploader")
        )

    def list_playlist(self, url: str, cookiefile: Path | None = None) -> Iterator[PlaylistEntry]:
        import yt_dlp
        from yt_dlp.utils import DownloadError

        # extract_flat lists entries without visiting each Video; lazy_playlist pages through large
        # playlists as the iterator is consumed instead of loading every page first.
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "lazy_playlist": True,
        }
        if cookiefile is not None:
            options["cookiefile"] = str(cookiefile)
        try:
            with yt_dlp.YoutubeDL(options) as ydl:  # type: ignore[arg-type]
                info = ydl.extract_info(url, download=False)
                for item in (info or {}).get("entries") or []:
                    if isinstance(item, dict) and (entry := entry_from_flat(dict(item))) is not None:
                        yield entry
        except DownloadError as err:
            if is_login_error(str(err)):
                raise LoginRequired(str(err)) from err
            raise VideoSourceError(str(err)) from err
