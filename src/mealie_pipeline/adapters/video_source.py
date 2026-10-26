"""The VideoSource port: yt-dlp as a library. Only `metadata` exists so far."""

from typing import Any, Protocol

from mealie_pipeline.models import VideoMeta


class VideoSourceError(Exception):
    """The platform refused or the video could not be read."""


class VideoSource(Protocol):
    def metadata(self, url: str) -> VideoMeta:
        """Title, description, thumbnail and so on, without downloading the video."""
        ...


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
