"""Ticket 05 at the pipeline seam: the `classify` stage, escalation, overrides and `mp review classify`."""

import csv
from typing import Any

import pytest

from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.adapters.llm import LLMError
from tests.helpers import classify_as, non_classify_calls, recipe_llm
from tests.test_pipeline_seam import (
    CANONICAL,
    ITEM_KEY,
    URL,
    VIDEO_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]

OTHER_ID = "BBBBBBBBBBB"
OTHER_KEY = f"youtube:{OTHER_ID}"


@pytest.fixture
def world(tmp_path) -> World:
    w = World(tmp_path)
    w.llm = recipe_llm()
    w.llm.script("extract", load("llm_extract_okra.json"))
    return w


def rows(world: World) -> list[dict[str, str]]:
    path = world.workspace / "reports" / "classification.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def edit_override(world: World, video_key: str, label: str) -> None:
    """What the user does in Excel: fill the `override` cell of one row."""
    path = world.workspace / "reports" / "classification.csv"
    table = rows(world)
    for row in table:
        if row["video_key"] == video_key:
            row["override"] = label
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)


def script(world: World, label: str, confidence: float = 0.95) -> None:
    world.llm = FakeLLM()
    world.llm.script("classify", classify_as(label, confidence))
    world.llm.script("extract", load("llm_extract_okra.json"))


def classify_calls(world: World) -> list[Any]:
    return [c for c in world.llm.calls if c.task == "classify"]


def test_a_recipe_continues_to_mealie_and_is_listed_in_the_classification_csv(world: World):
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 1
    (row,) = rows(world)
    assert (row["video_key"], row["label"], row["confidence"], row["override"]) == (
        VIDEO_KEY,
        "recipe",
        "0.95",
        "",
    )
    assert row["reasons"] == "scripted" and row["url"] == CANONICAL


def test_a_restaurant_is_skipped_with_its_label_and_never_reaches_extract(world: World):
    script(world, "restaurant_or_place")
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}
    assert non_classify_calls(world.llm) == []
    store = world.store()
    assert store.stage_status("video", VIDEO_KEY, "classify") == "skipped"
    assert store.parts() == []
    assert "restaurant_or_place" in result.output
    assert world.invoke("report").exit_code == 0
    with (world.workspace / "reports" / "report.csv").open(encoding="utf-8-sig", newline="") as handle:
        (row,) = list(csv.DictReader(handle))
    assert row["classify_status"] == "skipped" and row["extract_status"] == ""
    assert row["failure_reason"] == ""


def test_an_override_wins_and_the_next_run_does_not_ask_the_llm_again(world: World):
    script(world, "restaurant_or_place")
    world.invoke("add", URL)
    world.invoke("run")
    assert world.mealie.recipes == {}

    edit_override(world, VIDEO_KEY, "recipe")
    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(classify_calls(world)) == 1  # only the first run asked
    assert len(world.mealie.recipes) == 1
    (row,) = rows(world)
    assert (row["label"], row["source"], row["override"]) == ("recipe", "override", "recipe")


def test_an_override_can_also_skip_a_video_the_classifier_passed(world: World):
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,classify")
    edit_override(world, VIDEO_KEY, "not_food")

    world.invoke("run")

    assert world.mealie.recipes == {}
    assert world.store().stage_status("video", VIDEO_KEY, "classify") == "skipped"


def test_an_unknown_override_is_ignored_with_a_warning(world: World):
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,classify")
    edit_override(world, VIDEO_KEY, "banana")

    result = world.invoke("run")

    assert "banana" in result.output and len(world.mealie.recipes) == 1


def test_an_unsure_video_is_asked_again_with_its_subtitles(world: World):
    def answer(prompt: str) -> dict[str, Any]:
        subtitles = "Subtitles (start)" in prompt
        return {
            "items": [
                {
                    "video_key": VIDEO_KEY,
                    "label": "recipe" if subtitles else "uncertain",
                    "confidence": 0.9 if subtitles else 0.4,
                    "reasons": ["the subtitles list ingredients" if subtitles else "caption is thin"],
                }
            ]
        }

    world.llm = FakeLLM()
    world.llm.script("classify", answer)
    world.llm.script("extract", load("llm_extract_okra.json"))
    world.videos.subtitle_texts[CANONICAL] = "first take two onions and fry them"
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    prompts = [c.prompt for c in classify_calls(world)]
    assert len(prompts) == 2 and "first take two onions" in prompts[1]
    assert "Subtitles (start)" not in prompts[0]
    assert all(c.tier == "fast" for c in classify_calls(world))
    (row,) = rows(world)
    assert (row["label"], row["escalated"]) == ("recipe", "yes")
    assert len(world.mealie.recipes) == 1


def test_a_video_still_unsure_without_subtitles_waits_for_review_and_does_not_continue(world: World):
    script(world, "uncertain", 0.3)
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}
    assert len(classify_calls(world)) == 1  # no subtitles: no second try
    assert rows(world)[0]["label"] == "uncertain"


def test_a_batch_that_misses_a_key_is_retried_once_and_then_the_missing_one_is_uncertain(world: World):
    world.llm = FakeLLM()
    world.llm.script(
        "classify",
        {"items": [{"video_key": VIDEO_KEY, "label": "recipe", "confidence": 0.9, "reasons": ["ok"]}]},
    )
    world.videos.infos[f"https://www.youtube.com/watch?v={OTHER_ID}"] = load("youtube_info_okra.json")
    world.invoke("add", URL, f"https://youtu.be/{OTHER_ID}")

    world.invoke("run", "--stages", "metadata,classify")

    assert len(classify_calls(world)) == 2  # the first try plus one retry
    assert {r["video_key"]: r["label"] for r in rows(world)} == {VIDEO_KEY: "recipe", OTHER_KEY: "uncertain"}


def test_a_duplicated_key_counts_as_missing(world: World):
    world.llm = FakeLLM()
    item = {"video_key": VIDEO_KEY, "label": "recipe", "confidence": 0.9, "reasons": []}
    world.llm.script("classify", {"items": [item, item]})
    world.invoke("add", URL)

    world.invoke("run", "--stages", "metadata,classify")

    assert len(classify_calls(world)) == 2
    assert rows(world)[0]["label"] == "uncertain"


def test_videos_are_classified_in_batches_of_the_configured_size(world: World):
    (world.workspace / "config" / "settings.yaml").write_text(
        "classify:\n  batch_size: 2\n", encoding="utf-8"
    )
    ids = ["AAAAAAAAAAA", OTHER_ID, "CCCCCCCCCCC"]
    for vid in ids:
        world.videos.infos[f"https://www.youtube.com/watch?v={vid}"] = load("youtube_info_okra.json")
    world.invoke("add", *[f"https://youtu.be/{v}" for v in ids])

    world.invoke("run", "--stages", "metadata,classify")

    assert [c.prompt.count("### video_key:") for c in classify_calls(world)] == [2, 1]


def test_a_failed_classifier_call_fails_those_videos_and_retry_asks_again(world: World):
    world.llm = FakeLLM()
    world.llm.script("classify", LLMError("claude failed: boom"))
    world.invoke("add", URL)

    failed = world.invoke("run")

    assert failed.exit_code == 1 and "boom" in failed.output
    assert world.store().stage_status("video", VIDEO_KEY, "classify") == "failed"
    script(world, "recipe")
    assert world.invoke("retry", VIDEO_KEY).exit_code == 0
    assert world.invoke("run").exit_code == 0
    assert len(world.mealie.recipes) == 1


def test_review_shows_the_video_and_the_choice_becomes_an_override(world: World):
    script(world, "uncertain", 0.3)
    world.invoke("add", URL)
    world.invoke("run")

    review = world.invoke("review", "classify", input="r\n")

    assert review.exit_code == 0, review.output
    for shown in ("Chatpata", "Classifier: uncertain (0.30)", "scripted"):
        assert shown in review.output
    assert rows(world)[0]["override"] == "recipe"

    world.invoke("run")
    assert len(world.mealie.recipes) == 1
    assert world.store().part(ITEM_KEY).slug


def test_review_skip_saves_nothing_and_decided_videos_are_not_shown_again(world: World):
    script(world, "uncertain", 0.3)
    world.invoke("add", URL)
    world.invoke("run")

    skipped = world.invoke("review", "classify", input="s\n")
    assert skipped.exit_code == 0 and rows(world)[0]["override"] == ""
    world.invoke("review", "classify", input="n\n")
    again = world.invoke("review", "classify")

    assert rows(world)[0]["override"] == "not_food"
    assert "Nothing to review" in again.output


def test_recipe_requests_are_not_classified_and_pass_straight_through(world: World):
    world.invoke("add", URL)
    store = world.store()
    store.add_video("web:abc", "web", "abc", "https://example.com/r", "https://example.com/r")
    store.set_metadata("web:abc", {"title": "Dal", "webpage_url": "https://example.com/r"})
    store.record("video", "web:abc", "metadata", "done")

    world.invoke("run", "--stages", "metadata,classify")

    store = world.store()
    assert store.stage_status("video", "web:abc", "classify") is None
    assert store.video("web:abc").classification is None
    assert [r["video_key"] for r in rows(world)] == [VIDEO_KEY]
