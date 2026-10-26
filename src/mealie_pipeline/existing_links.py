"""The Existing Link Set (pure): every Mealie recipe's `orgURL` as a key, so a Video that is already
in Mealie is recognised by its link and never done twice. There is no name matching: the link is
the identity, and recipes without an `orgURL` are not matched."""

from typing import Any

from mealie_pipeline.url_normalizer import normalize, normalize_website


def link_key(url: object) -> str | None:
    """A Video Key (`instagram:ABC`) for a Video link, a normalized URL for a website link, else None."""
    if not isinstance(url, str) or not url.strip():
        return None
    video = normalize(url)
    return video.video_key if video else normalize_website(url)


def build_link_set(summaries: list[dict[str, Any]]) -> dict[str, str]:
    """`key -> slug` for every recipe summary with a usable `orgURL`. The first recipe wins a key."""
    links: dict[str, str] = {}
    for summary in summaries:
        key = link_key(summary.get("orgURL"))
        if key and summary.get("slug"):
            links.setdefault(key, str(summary["slug"]))
    return links
