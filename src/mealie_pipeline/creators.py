"""The Creator -> Recipe Website registry.

A Creator is keyed by a normalized handle, so the same account on YouTube, Instagram and Facebook
(`@yourfoodlab`, `yourfoodlab`) shares one Recipe Website. The first Video (or bio page) that leads
to a website teaches it; later ones never overwrite it. Site search uses it for Videos that say
"recipe in bio" but link nothing.
"""

import re
from datetime import UTC, datetime
from typing import Literal

from mealie_pipeline.models import VideoMeta
from mealie_pipeline.store import StateStore

Source = Literal["video", "bio", "about"]
_CHANNEL_ID = re.compile(r"^UC[\w-]{22}$")  # a YouTube channel id, not a handle


def _normalize(text: str) -> str:
    return "".join(re.findall(r"[^\W_]+", text.casefold()))


def creator_handle(meta: VideoMeta) -> str:
    """The Creator's key: the handle (`@name` or username), else the display name, normalized."""
    for value in (meta.uploader_id, meta.channel, meta.uploader):
        value = value.strip()
        if not value or value.isdigit() or _CHANNEL_ID.match(value):
            continue
        handle = _normalize(value.removeprefix("@"))
        if handle:
            return handle
    return ""


class CreatorRegistry:
    def __init__(self, store: StateStore):
        self._store = store

    def website(self, handle: str) -> str | None:
        if not handle:
            return None
        row = self._store.db.execute(
            "SELECT website FROM creator_websites WHERE handle = ?", (handle,)
        ).fetchone()
        return row["website"] if row else None

    def learn(self, handle: str, website: str, source: Source, learned_from: str) -> bool:
        """Records the Creator's website unless one is known already; True when it was new."""
        if not handle or not website:
            return False
        cursor = self._store.db.execute(
            "INSERT OR IGNORE INTO creator_websites (handle, website, source, learned_from, added_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (handle, website, source, learned_from, datetime.now(UTC).isoformat(timespec="seconds")),
        )
        self._store.db.commit()
        return cursor.rowcount == 1

    def all(self) -> dict[str, str]:
        rows = self._store.db.execute("SELECT handle, website FROM creator_websites ORDER BY handle")
        return {r["handle"]: r["website"] for r in rows}
