import threading

from mealie_pipeline.store import StateStore


def test_the_store_survives_reopening_and_keeps_its_data(tmp_path):
    path = tmp_path / "pipeline.db"
    store = StateStore(path)
    store.add_video("youtube:a", "youtube", "a", "u", "c")
    store.close()

    reopened = StateStore(path)  # migrations are applied again without error

    assert [v.video_key for v in reopened.videos()] == ["youtube:a"]


def test_adding_the_same_video_twice_registers_it_once(tmp_path):
    store = StateStore(tmp_path / "pipeline.db")

    assert store.add_video("youtube:a", "youtube", "a", "u1", "c") is True
    assert store.add_video("youtube:a", "youtube", "a", "u2", "c") is False


def test_next_batch_waits_for_the_previous_stage_and_skips_finished_or_failed(tmp_path):
    store = StateStore(tmp_path / "pipeline.db")
    for vid in "abc":
        store.add_video(f"youtube:{vid}", "youtube", vid, "u", "c")
        store.ensure_part(f"youtube:{vid}")
    store.record("part", "youtube:a#1", "extract", "done")
    store.record("part", "youtube:b#1", "extract", "done")
    store.record("part", "youtube:b#1", "parse", "failed", "boom")

    assert store.next_batch("part", "parse", "extract") == ["youtube:a#1"]
    assert store.next_batch("part", "parse", "extract", limit=0) == []
    assert store.next_batch("part", "extract", None, limit=1) == ["youtube:c#1"]


def test_the_store_uses_wal_and_a_long_lock_wait_so_two_runs_can_share_it(tmp_path):
    store = StateStore(tmp_path / "pipeline.db")

    assert store.db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert store.db.execute("PRAGMA busy_timeout").fetchone()[0] >= 30_000


def test_two_stores_on_one_file_can_write_at_the_same_time(tmp_path):
    path = tmp_path / "pipeline.db"
    StateStore(path).close()
    errors: list[Exception] = []

    def writer(prefix: str) -> None:
        store = StateStore(path)
        try:
            for n in range(100):
                store.add_video(f"youtube:{prefix}{n}", "youtube", f"{prefix}{n}", "u", "c")
        except Exception as err:  # noqa: BLE001  (the test reports whatever went wrong)
            errors.append(err)
        finally:
            store.close()

    threads = [threading.Thread(target=writer, args=(p,)) for p in "ab"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(StateStore(path).videos()) == 200


def test_videos_added_before_saved_lists_existed_keep_their_url(tmp_path):
    path = tmp_path / "pipeline.db"
    store = StateStore(path)
    store.db.execute("PRAGMA user_version = 5")  # as if the database predates migration 6
    store.db.executescript(
        "DROP TABLE list_members; DROP TABLE video_urls; DROP TABLE saved_lists; DROP TABLE creator_websites;"
        " ALTER TABLE videos DROP COLUMN early_json;"
        " ALTER TABLE videos DROP COLUMN classification_json;"  # migration 7 came later still
        " ALTER TABLE recipe_parts DROP COLUMN outline_json;"  # and migration 9
        " INSERT INTO videos (video_key, platform, video_id, url, canonical_url, added_at)"
        " VALUES ('youtube:a', 'youtube', 'a', 'https://youtu.be/a', 'c', '2026-01-01');"
    )
    store.db.commit()
    store.close()

    reopened = StateStore(path)

    assert reopened.video_urls("youtube:a") == ["https://youtu.be/a"]
    assert reopened.video("youtube:a").early is None
    assert reopened.saved_lists() == []
