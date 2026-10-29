"""Ticket 04 at the pipeline seam: register YouTube Saved Lists, sync them, re-sync incrementally."""

import pytest

from mealie_pipeline.adapters.fake_video_source import FakeVideoSource
from mealie_pipeline.adapters.video_source import PlaylistEntry
from tests.test_pipeline_seam import World, clean_environment  # noqa: F401  (autouse fixture)

__all__ = ["clean_environment"]

PLAYLIST = "https://www.youtube.com/playlist?list=PLdinner"
OTHER = "https://www.youtube.com/playlist?list=PLquick"


def entry(video_id: str, *, short: bool = False) -> PlaylistEntry:
    url = f"https://youtu.be/{video_id}?si=x" if short else f"https://www.youtube.com/watch?v={video_id}"
    return PlaylistEntry(url=url, title=f"Recipe {video_id}", channel="Some Chef", duration_s=300)


def ids(*names: str) -> list[str]:
    return [name.ljust(11, "0") for name in names]


@pytest.fixture
def world(tmp_path) -> World:
    w = World(tmp_path)
    w.videos = FakeVideoSource(w.videos.infos)
    return w


def test_sync_collects_every_video_of_a_registered_playlist(world: World):
    world.videos.playlists[PLAYLIST] = [entry(v) for v in ids("a", "b", "c")]

    added = world.invoke("lists", "add", f"{PLAYLIST}&si=share")
    synced = world.invoke("sync")

    assert added.exit_code == 0, added.output
    assert "youtube:PLdinner" in added.output
    assert synced.exit_code == 0, synced.output
    store = world.store()
    assert sorted(v.video_key for v in store.videos()) == [f"youtube:{v}" for v in ids("a", "b", "c")]
    video = store.video(f"youtube:{ids('a')[0]}")
    assert video.early == {"title": f"Recipe {ids('a')[0]}", "channel": "Some Chef", "duration_s": 300}
    assert video.canonical_url == f"https://www.youtube.com/watch?v={ids('a')[0]}"


def test_resync_adds_only_the_new_videos_and_updates_last_synced(world: World):
    world.videos.playlists[PLAYLIST] = [entry(v) for v in ids("a", "b", "c")]
    world.invoke("lists", "add", PLAYLIST)
    world.invoke("sync")
    first = world.store().saved_lists()[0]

    world.videos.playlists[PLAYLIST] = [entry(v) for v in ids("d", "a", "b", "e", "c")]  # 2 new
    result = world.invoke("sync")

    assert result.exit_code == 0, result.output
    assert "2 new" in result.output
    store = world.store()
    assert len(store.videos()) == 5
    saved = store.saved_lists()[0]
    assert sorted(store.new_in_last_sync(saved.list_key)) == [f"youtube:{v}" for v in ids("d", "e")]
    assert saved.item_count == 5
    assert saved.sync_count == first.sync_count + 1
    assert saved.last_synced is not None and saved.last_synced >= (first.last_synced or "")


def test_the_same_video_in_two_lists_and_two_url_forms_is_one_video_with_two_memberships(world: World):
    shared = ids("s")[0]
    world.videos.playlists[PLAYLIST] = [entry(shared), entry(ids("a")[0])]
    world.videos.playlists[OTHER] = [entry(shared, short=True)]
    world.invoke("lists", "add", PLAYLIST)
    world.invoke("lists", "add", OTHER)

    result = world.invoke("sync")

    assert result.exit_code == 0, result.output
    store = world.store()
    assert len(store.videos()) == 2
    key = f"youtube:{shared}"
    assert sorted(store.memberships(key)) == ["youtube:PLdinner", "youtube:PLquick"]
    assert sorted(store.video_urls(key)) == [
        f"https://www.youtube.com/watch?v={shared}",
        f"https://youtu.be/{shared}?si=x",
    ]


def test_sync_list_option_syncs_only_that_list(world: World):
    world.videos.playlists[PLAYLIST] = [entry(v) for v in ids("a")]
    world.videos.playlists[OTHER] = [entry(v) for v in ids("b")]
    world.invoke("lists", "add", PLAYLIST)
    world.invoke("lists", "add", OTHER)

    result = world.invoke("sync", "--list", OTHER)

    assert result.exit_code == 0, result.output
    assert [v.video_key for v in world.store().videos()] == [f"youtube:{ids('b')[0]}"]


def test_lists_shows_each_list_with_its_count_and_last_sync(world: World):
    world.videos.playlists[PLAYLIST] = [entry(v) for v in ids("a", "b")]
    world.invoke("lists", "add", PLAYLIST)
    before = world.invoke("lists")
    world.invoke("sync")

    after = world.invoke("lists")

    assert before.exit_code == 0, before.output
    assert "never" in before.output
    assert "youtube:PLdinner" in after.output
    assert "2" in after.output
    assert "never" not in after.output


def test_adding_a_list_twice_registers_it_once(world: World):
    world.invoke("lists", "add", PLAYLIST)
    result = world.invoke("lists", "add", "https://m.youtube.com/playlist?list=PLdinner&si=again")

    assert result.exit_code == 0, result.output
    assert "already registered" in result.output
    assert len(world.store().saved_lists()) == 1


def test_an_unsupported_list_url_is_refused(world: World):
    result = world.invoke("lists", "add", "https://www.youtube.com/watch?v=dQw4w9WgXcQ")

    assert result.exit_code == 2
    assert "not a supported Saved List" in result.output
    assert world.store().saved_lists() == []


@pytest.mark.parametrize("list_id", ["WL", "LL", "PLprivate"])
def test_private_lists_ask_for_mp_login_instead_of_crashing(world: World, list_id: str):
    world.videos.private.add(f"https://www.youtube.com/playlist?list={list_id}")
    world.videos.playlists[PLAYLIST] = [entry(v) for v in ids("a")]
    world.invoke("lists", "add", f"https://www.youtube.com/playlist?list={list_id}")
    world.invoke("lists", "add", PLAYLIST)

    result = world.invoke("sync")

    assert result.exit_code == 1
    assert "mp login youtube" in result.output
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)
    # the other list still synced, and the failed one remembers why
    store = world.store()
    assert [v.video_key for v in store.videos()] == [f"youtube:{ids('a')[0]}"]
    failed = next(s for s in store.saved_lists() if s.list_key == f"youtube:{list_id}")
    assert failed.last_synced is None
    assert "mp login youtube" in (failed.last_error or "")


def test_unsupported_entries_are_counted_and_skipped(world: World):
    world.videos.playlists[PLAYLIST] = [
        entry(ids("a")[0]),
        PlaylistEntry(url="https://www.youtube.com/watch?v=bad", title="[Deleted video]"),
    ]
    world.invoke("lists", "add", PLAYLIST)

    result = world.invoke("sync")

    assert result.exit_code == 0, result.output
    assert "1 unsupported" in result.output
    assert len(world.store().videos()) == 1


def test_synced_videos_then_run_through_the_pipeline(world: World):
    from tests.test_pipeline_seam import CANONICAL

    world.videos.playlists[PLAYLIST] = [PlaylistEntry(url=CANONICAL, title="Okra")]
    world.invoke("lists", "add", PLAYLIST)
    world.invoke("sync")

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 1
