"""Instagram / Facebook data export -> Saved List: reads `saved_posts.json` / `saved_collections.json` from
"Download your information", so no login and no scrolling is needed. The caption and the owner come
from the export and become the Video's metadata (the `metadata` stage is recorded done)."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mealie_pipeline.models import VideoMeta
from mealie_pipeline.store import StateStore
from mealie_pipeline.url_normalizer import normalize

UNCOLLECTED = "(none)"


@dataclass
class ExportedPost:
    url: str
    caption: str = ""
    owner: str = ""
    collections: list[str] = field(default_factory=list)


def _fix(text: str) -> str:
    """Instagram writes UTF-8 bytes as latin-1 escapes ("ðŸ¥³"); undo that when it applies."""
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def _post(label_values: list[dict[str, Any]]) -> ExportedPost | None:
    post = ExportedPost("")
    for entry in label_values:
        if entry.get("label") == "URL" and not post.url:
            post.url = entry.get("href") or entry.get("value", "")
        elif entry.get("label") == "Caption":
            post.caption = _fix(entry.get("value", ""))
        elif entry.get("title") == "Owner":
            for group in entry.get("dict", []):
                for item in group.get("dict", []):
                    if item.get("label") == "Username":
                        post.owner = item.get("value", "")
    return post if post.url else None


def read_export(folder: Path) -> list[ExportedPost]:
    """Every saved post once, with the collections it is in (`(none)` when in no collection)."""
    posts: dict[str, ExportedPost] = {}
    saved = json.loads((folder / "saved_posts.json").read_text(encoding="utf-8"))
    for record in saved:
        post = _post(record.get("label_values", []))
        if post:
            posts.setdefault(post.url, post)
    collections = folder / "saved_collections.json"
    if collections.exists():
        for record in json.loads(collections.read_text(encoding="utf-8")):
            name = ""
            for entry in record.get("label_values", []):
                if entry.get("label") == "Name":
                    name = _fix(entry["value"]).strip()
                for member in entry.get("dict", []):
                    post = _post(member.get("dict", []))
                    if post:
                        known = posts.setdefault(post.url, post)
                        if name not in known.collections:
                            known.collections.append(name)
    for post in posts.values():
        if not post.collections:
            post.collections.append(UNCOLLECTED)
    return list(posts.values())


def read_facebook_collections(path: Path) -> list[ExportedPost]:
    """The saves of Facebook's `collections.json`, once per link; a save has no caption there, so the
    `metadata` stage fetches it."""
    posts: dict[str, ExportedPost] = {}
    for record in json.loads(path.read_text(encoding="utf-8")):
        name = ""
        for entry in record.get("label_values", []):
            if entry.get("label") == "Title":
                name = _fix(entry["value"]).strip()
            for save in entry.get("dict", []) if entry.get("title") == "Saves" else []:
                fields = {x.get("label"): x.get("href") or x.get("value", "") for x in save.get("dict", [])}
                url = fields.get("URL", "")
                if not url:
                    continue
                post = posts.setdefault(url, ExportedPost(url))
                post.owner = post.owner or _fix(fields.get("Name", ""))
                if name not in post.collections:
                    post.collections.append(name)
    return list(posts.values())


def import_posts(
    store: StateStore, list_key: str, source: str, posts: list[ExportedPost], platform: str = "instagram"
) -> list[str]:
    """Registers the list and its Videos; returns the Video Keys that are new to the list."""
    store.add_list(list_key, platform, source)
    keys: list[str] = []
    for post in posts:
        normalized = normalize(post.url)
        if normalized is None or normalized.platform != platform:
            continue
        key = normalized.video_key
        store.add_video(key, platform, normalized.video_id, post.url, normalized.canonical_url)
        if platform == "instagram" and store.video(key).metadata is None:
            first_line = post.caption.strip().split("\n", 1)[0][:100]
            meta = VideoMeta(
                title=first_line or f"Instagram post by {post.owner}",
                description=post.caption,
                uploader=post.owner,
                channel=post.owner,
                webpage_url=normalized.canonical_url,
            )
            store.set_metadata(key, meta.model_dump())
            store.record("video", key, "metadata", "done", "from the Instagram export")
        keys.append(key)
    return store.record_sync(list_key, keys)
