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
