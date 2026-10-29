"""Collect: sync the registered Saved Lists into the State Store.

Every entry goes through the URL Normalizer (short and share links are expanded first), so one Video
is stored once per Video Key however it was linked, with one membership per list. A list that needs
a login fails alone with a hint; the other lists still sync.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

from mealie_pipeline.adapters.collectors import ListCollector
from mealie_pipeline.adapters.video_source import LoginRequired, VideoSourceError
from mealie_pipeline.store import SavedList, StateStore
from mealie_pipeline.url_normalizer import resolve


@dataclass
class ListSync:
    list_key: str
    seen: int = 0
    new: list[str] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    error: str | None = None


def login_hint(platform: str, detail: str) -> str:
    return f"needs a login ({detail}). Run `mp login {platform}`, then `mp sync` again."


def sync_list(
    store: StateStore, saved: SavedList, collector: ListCollector, expand: Callable[[str], str]
) -> ListSync:
    result = ListSync(saved.list_key)
    keys: list[str] = []
    try:
        for entry in collector.enumerate(saved.url):
            result.seen += 1
            normalized = resolve(entry.url, expand)
            if normalized is None:
                result.unsupported.append(entry.url)
                continue
            key = normalized.video_key
            store.add_video(
                key, normalized.platform, normalized.video_id, entry.url, normalized.canonical_url
            )
            store.add_video_url(key, entry.url)
            early = {"title": entry.title, "channel": entry.channel, "duration_s": entry.duration_s}
            if any(v is not None for v in early.values()):
                store.set_early_metadata(key, early)
            keys.append(key)
    except LoginRequired as err:
        result.error = login_hint(saved.platform, str(err))
    except VideoSourceError as err:
        result.error = f"could not list it: {err}"
    if result.error is not None:
        store.record_sync_error(saved.list_key, result.error)
        return result
    result.new = store.record_sync(saved.list_key, keys)
    return result


def sync_lists(
    store: StateStore,
    collectors: dict[str, ListCollector],
    expand: Callable[[str], str],
    only: list[str] | None = None,
) -> list[ListSync]:
    """Syncs every registered list (or the List Keys in `only`), one after the other."""
    results = []
    for saved in store.saved_lists():
        if only is not None and saved.list_key not in only:
            continue
        collector = collectors.get(saved.platform)
        if collector is None:
            result = ListSync(saved.list_key, error=f"no collector for {saved.platform} yet")
            store.record_sync_error(saved.list_key, result.error or "")
            results.append(result)
            continue
        results.append(sync_list(store, saved, collector, expand))
    return results
