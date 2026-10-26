"""Recipe image selection and upload (the pipeline fetches images itself; Mealie never scrapes)."""

import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from mealie_pipeline.adapters.downloader import ImageDownloader
from mealie_pipeline.adapters.mealie import MealieGateway
from mealie_pipeline.errors import MealieError

PLACEHOLDER_MAX_WIDTH = 120  # YouTube answers 200 with a 120x90 grey image when maxres is missing


@dataclass(frozen=True)
class PickedImage:
    url: str
    data: bytes
    extension: str


def candidate_urls(
    platform: str, video_id: str, thumbnail: str | None, preferred: str | None = None
) -> list[str]:
    """Image URLs to try, best first. A Recipe Website's own image (`preferred`) beats the thumbnail."""
    if platform == "youtube":
        base = f"https://i.ytimg.com/vi/{video_id}"
        urls = [f"{base}/maxresdefault.jpg", f"{base}/hqdefault.jpg"]
    else:
        urls = [thumbnail] if thumbnail else []
    return [preferred, *urls] if preferred else urls


def image_info(data: bytes) -> tuple[str, int | None] | None:
    """`(extension, width)` of a jpg/png/webp, or None when the bytes are not one of those."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        return "png", struct.unpack(">I", data[16:20])[0]
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", _webp_width(data)
    if data[:2] == b"\xff\xd8":
        return "jpg", _jpeg_width(data)
    return None


def _jpeg_width(data: bytes) -> int | None:
    pos = 2
    while pos + 9 < len(data):
        if data[pos] != 0xFF:
            pos += 1
            continue
        marker = data[pos + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            pos += 2
            continue
        length = struct.unpack(">H", data[pos + 2 : pos + 4])[0]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return struct.unpack(">H", data[pos + 7 : pos + 9])[0]
        pos += 2 + length
    return None


def _webp_width(data: bytes) -> int | None:
    kind = data[12:16]
    if kind == b"VP8X" and len(data) >= 30:
        return 1 + int.from_bytes(data[24:27], "little")
    if kind == b"VP8 " and len(data) >= 30:
        return struct.unpack("<H", data[26:28])[0] & 0x3FFF
    if kind == b"VP8L" and len(data) >= 25:
        return 1 + (int.from_bytes(data[21:25], "little") & 0x3FFF)
    return None


def pick_image(urls: list[str], downloader: ImageDownloader) -> PickedImage | None:
    """The first URL that downloads as a real image (not a 404, not the tiny placeholder)."""
    for url in urls:
        status, body = downloader.get(url)
        info = image_info(body) if status == 200 else None
        if info is None:
            continue
        extension, width = info
        if width is not None and width <= PLACEHOLDER_MAX_WIDTH:
            continue
        return PickedImage(url, body, extension)
    return None


ImageOutcome = Literal["file", "url", "missing"]


def attach_image(
    mealie: MealieGateway, slug: str, urls: list[str], downloader: ImageDownloader, scratch: Path
) -> ImageOutcome:
    """File upload first, then Mealie fetching the URL; a recipe without an image is not a failure."""
    picked = pick_image(urls, downloader)
    if picked is not None:
        scratch.mkdir(parents=True, exist_ok=True)
        path = scratch / f"{slug}.{picked.extension}"
        path.write_bytes(picked.data)
        try:
            mealie.upload_image(slug, path)
            return "file"
        except MealieError:
            pass
    fallback = picked.url if picked else (urls[-1] if urls else None)
    if fallback:
        try:
            mealie.set_image_from_url(slug, fallback)
            return "url"
        except MealieError:
            pass
    return "missing"
