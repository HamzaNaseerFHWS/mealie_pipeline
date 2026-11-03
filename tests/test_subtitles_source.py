"""Ticket 34: existing subtitles as a Source (`[SRC:sub]`); no audio transcription."""

import csv

from mealie_pipeline.adapters.video_source import VideoSourceError, vtt_text
from mealie_pipeline.grounding import evidence_grounded
from mealie_pipeline.models import Evidence
from tests.test_partial_and_stubs import HASHTAGS_ONLY, StubWorld, recipe
from tests.test_pipeline_seam import (
    CANONICAL,
    ITEM_KEY,
    URL,
    VIDEO_KEY,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

ROLLING_VTT = """WEBVTT
Kind: captions
Language: en

00:00:00.000 --> 00:00:02.000 align:start position:0%
today<00:00:00.500><c> we</c><c> make</c>

00:00:02.000 --> 00:00:02.010
today we make

00:00:02.010 --> 00:00:04.000
today we make bhindi aloo
take<00:00:03.000><c> 250 g okra</c>

00:00:04.000 --> 00:00:06.000
take 250 g okra
[Music]

00:00:06.000 --> 00:00:08.000
2 small onions &amp; 2 tbsp mustard oil
"""

SPOKEN = (
    "today we make bhindi aloo\ntake 250 g okra (bhindi)\n2 small onions\n2 tbsp mustard oil\n"
    "1/2 tsp cumin seeds\nSalt, to taste\nfry the okra until crisp and add the onions"
)


def test_caption_clean_up_drops_timings_tags_and_rolling_repeats():
    assert vtt_text(ROLLING_VTT) == (
        "today we make bhindi aloo\ntake 250 g okra\n2 small onions & 2 tbsp mustard oil"
    )


def test_srt_cue_numbers_are_dropped():
    srt = "1\n00:00:01,000 --> 00:00:02,000\nhello\n\n2\n00:00:02,000 --> 00:00:03,000\nworld\n"
    assert vtt_text(srt) == "hello\nworld"


def test_a_quote_from_the_cleaned_captions_is_grounded():
    sources = {"desc": HASHTAGS_ONLY, "sub": vtt_text(ROLLING_VTT)}
    assert evidence_grounded([Evidence(source="sub", quote="take 250 g okra")], sources)


def sub_extraction() -> dict:
    extraction = load("llm_extract_okra.json")
    for item in [*extraction["ingredients"], *extraction["instructions"]]:
        item["evidence"] = [{"source": "sub", "quote": e["quote"]} for e in item["evidence"]]
    extraction["instructions"] = [
        {
            "text": "Fry the okra until crisp.",
            "evidence": [{"source": "sub", "quote": "fry the okra until crisp"}],
        }
    ]
    return extraction


def test_a_video_with_captions_reaches_extract_with_them_and_its_quotes_check_out(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.videos.subtitle_texts[CANONICAL] = SPOKEN
    world.llm.script("extract", sub_extraction())
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    prompt = next(c.prompt for c in world.llm.calls if c.task == "extract")
    assert "[SRC:sub]" in prompt and "take 250 g okra (bhindi)" in prompt
    stored = recipe(world)
    assert len(stored["recipeIngredient"]) == 5  # nothing dropped: every quote is in the subtitles
    assert "link-only" not in [t["name"] for t in stored["tags"]]
    assert world.store().part(ITEM_KEY).verify["outcome"] in ("upload", "upload_review")  # type: ignore[index]


def test_no_captions_means_a_link_only_stub_not_a_failure(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert world.videos.subtitle_calls == [CANONICAL]
    assert "link-only" in [t["name"] for t in recipe(world)["tags"]]


def test_subtitles_are_not_fetched_when_the_description_holds_the_recipe(tmp_path):
    world = StubWorld(tmp_path)
    world.llm.script("extract", load("llm_extract_okra.json"))
    world.invoke("add", URL)

    assert world.invoke("run").exit_code == 0
    assert world.videos.subtitle_calls == []


def test_a_subtitle_error_is_a_warning_and_the_video_still_goes_on(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)

    def broken(url: str) -> str:
        raise VideoSourceError("HTTP Error 429")

    world.videos.subtitles = broken  # type: ignore[method-assign]
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert "subtitles not read" in result.output
    assert world.mealie.recipes  # a stub


def test_requeue_sends_no_text_videos_back_through_scrape_and_renames_the_category(tmp_path):
    world = StubWorld(tmp_path)
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,classify,linkcheck,scrape,outline")
    store = world.store()
    store.record("part", ITEM_KEY, "extract", "failed", "the video has no description or website recipe")
    sheet = tmp_path / "reports" / "youtube_status.csv"
    sheet.parent.mkdir(exist_ok=True)
    with sheet.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerows([["url", "category"], [CANONICAL, "needs_transcription"], ["x", "done"]])

    result = world.invoke("requeue-subtitles")

    assert result.exit_code == 0, result.output
    assert f"requeued {VIDEO_KEY}" in result.output
    assert store.stage_status("video", VIDEO_KEY, "scrape") is None
    assert store.stage_status("part", ITEM_KEY, "extract") is None
    assert "needs_subtitles" in sheet.read_text(encoding="utf-8-sig")
    assert "needs_transcription" not in sheet.read_text(encoding="utf-8-sig")
