"""Ticket 03 at the pipeline seam: batches, status, retry, reset, report, interruption."""

import copy
import csv
import json

import pytest

from mealie_pipeline.errors import MealieHttpError
from mealie_pipeline.pipeline import Pipeline
from mealie_pipeline.settings import load_settings
from tests.helpers import non_classify_calls, recipe_llm
from tests.images import make_jpeg
from tests.test_pipeline_seam import (
    ITEM_KEY,
    TOKEN,
    URL,
    FlakyImageMealie,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]


def watch_url(video_id: str) -> str:
    return f"https://www.youtube.com/watch?v={video_id}"


def add_video(world: World, video_id: str, recipe_name: str) -> str:
    """Registers another fake Video whose description (and so prompt) carries a unique marker."""
    info = copy.deepcopy(load("youtube_info_okra.json"))
    info.update(id=video_id, webpage_url=watch_url(video_id), title=recipe_name)
    info["description"] += f"\nMARKER-{video_id}\n"
    world.videos.infos[watch_url(video_id)] = info
    recipe = load("llm_extract_okra.json")
    recipe["name"] = recipe_name
    world.llm.script("extract", recipe, when_prompt_has=f"MARKER-{video_id}")
    world.images.files[f"https://i.ytimg.com/vi/{video_id}/maxresdefault.jpg"] = make_jpeg(1280)
    return watch_url(video_id)


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


@pytest.fixture
def three(world: World) -> tuple[World, list[str]]:
    world.llm = recipe_llm()  # drop the single-video script; every Video here has its own
    urls = [
        add_video(world, vid, name)
        for vid, name in [("AAAAAAAAAAA", "Dal"), ("BBBBBBBBBBB", "Rice"), ("CCCCCCCCCCC", "Naan")]
    ]
    return world, urls


def names(world: World) -> list[str]:
    return sorted(r["name"] for r in world.mealie.recipes.values())


def pipeline_for(world: World) -> Pipeline:
    settings = load_settings(world.workspace, environ={})
    from tests.helpers import fake_adapters
    from tests.test_pipeline_seam import ENGINE

    adapters = fake_adapters(
        mealie=world.mealie, llm=world.llm, videos=world.videos, images=world.images, engine=ENGINE
    )
    return Pipeline(world.workspace, settings, adapters, world.store())


# -- mp add --file ------------------------------------------------------------------------


def test_add_file_skips_blanks_and_comments_and_reports_duplicates_and_unsupported(world: World):
    file = world.workspace / "urls.txt"
    file.write_text(
        "# my saved recipes\n\n"
        f"{watch_url('AAAAAAAAAAA')}\n"
        "https://youtu.be/AAAAAAAAAAA?si=dup\n"
        "https://example.com/nope\n"
        f"   {watch_url('BBBBBBBBBBB')}   \n",
        encoding="utf-8",
    )

    result = world.invoke("add", "--file", str(file))

    assert result.exit_code == 0, result.output
    assert "already known youtube:AAAAAAAAAAA" in result.output
    assert "unsupported URL" in result.output
    assert "2 added, 1 already known, 1 unsupported" in result.output
    assert [v.video_key for v in world.store().videos()] == ["youtube:AAAAAAAAAAA", "youtube:BBBBBBBBBBB"]


# -- batches and resuming -----------------------------------------------------------------


def test_limit_processes_a_batch_and_the_next_run_continues_where_it_stopped(three):
    world, urls = three
    world.invoke("add", *urls)

    first = world.invoke("run", "--limit", "2")
    assert first.exit_code == 0, first.output
    assert names(world) == ["Dal", "Rice"]

    second = world.invoke("run", "--limit", "2")
    assert second.exit_code == 0, second.output
    assert names(world) == ["Dal", "Naan", "Rice"]

    calls = len(non_classify_calls(world.llm))
    world.invoke("run", "--limit", "2")
    assert len(non_classify_calls(world.llm)) == calls == 3  # each Video was extracted exactly once


def test_one_failing_video_never_stops_the_others(three):
    world, urls = three
    world.llm.script("extract", RuntimeError("kaboom"), when_prompt_has="MARKER-BBBBBBBBBBB")
    # The scripted failure must win over the success script added by add_video.
    world.llm._scripts.insert(0, world.llm._scripts.pop())
    world.invoke("add", *urls)

    result = world.invoke("run")

    assert result.exit_code == 1
    assert names(world) == ["Dal", "Naan"]
    assert "unexpected RuntimeError: kaboom" in result.output
    store = world.store()
    assert store.stage_status("part", "youtube:BBBBBBBBBBB#1", "extract") == "failed"
    assert store.stage_status("part", "youtube:AAAAAAAAAAA#1", "upload") == "done"


def test_a_cancel_mid_batch_finishes_the_current_item_and_a_rerun_uploads_nothing_twice(three):
    world, urls = three
    world.invoke("add", *urls)
    pipeline = pipeline_for(world)
    for url in urls:
        from mealie_pipeline.url_normalizer import normalize

        n = normalize(url)
        assert n
        pipeline.add(n.canonical_url, url, n.platform, n.video_id)

    interrupted = pipeline.run(should_stop=lambda: len(world.mealie.recipes) >= 1)

    assert interrupted.stopped and "Interrupted" in interrupted.stopped
    assert len(world.mealie.recipes) == 1  # the item in progress finished, nothing more started

    resumed = world.invoke("run")

    assert resumed.exit_code == 0, resumed.output
    assert names(world) == ["Dal", "Naan", "Rice"]
    assert len(non_classify_calls(world.llm)) == 3
    slugs = [r["slug"] for r in world.mealie.recipes.values()]
    assert len(slugs) == len(set(slugs))


def test_an_item_left_running_by_a_crash_is_picked_up_again(three):
    world, urls = three
    world.invoke("add", urls[0])
    store = world.store()
    store.record("video", "youtube:AAAAAAAAAAA", "metadata", "running")  # as if the process died

    assert world.invoke("run").exit_code == 0
    assert names(world) == ["Dal"]


# -- status -------------------------------------------------------------------------------


def test_status_shows_the_stage_table_totals_and_recent_errors(three):
    world, urls = three
    world.llm.script("extract", LLMErrorFor("MARKER-BBBBBBBBBBB"), when_prompt_has="MARKER-BBBBBBBBBBB")
    world.llm._scripts.insert(0, world.llm._scripts.pop())
    world.invoke("add", *urls)
    world.invoke("run")

    out = world.invoke("status").output

    assert "Videos: 3" in out and "Recipe Parts: 3" in out
    lines = {
        cells[0]: cells
        for cells in (line.replace("│", " ").split() for line in out.splitlines())
        if cells[:1] and cells[0] in ("metadata", "extract", "upload")
    }
    assert lines["metadata"][1:] == [
        "0",
        "0",
        "3",
        "0",
        "0",
        "0",
    ]  # pending running done failed skipped review
    assert lines["extract"][1:] == ["0", "0", "2", "1", "0", "0"]
    assert lines["upload"][1:] == ["0", "0", "2", "0", "0", "0"]
    assert "Recent errors" in out and "youtube:BBBBBBBBBBB#1 [extract]" in out and "claude failed" in out


def LLMErrorFor(_marker: str):  # noqa: N802
    from mealie_pipeline.adapters.llm import LLMError

    return LLMError("claude failed: boom")


def test_status_on_an_empty_workspace_does_not_crash(world: World):
    result = world.invoke("status")

    assert result.exit_code == 0 and "Videos: 0" in result.output


# -- retry and reset ----------------------------------------------------------------------


class PatchBreaks(FlakyImageMealie):
    broken = True

    def patch_recipe(self, slug, payload):
        if self.broken:
            raise MealieHttpError("PATCH", f"/api/recipes/{slug}", 500, "disk full")
        return super().patch_recipe(slug, payload)


def test_a_failed_upload_is_retried_successfully_once_mealie_is_fixed(world: World):
    world.mealie = PatchBreaks(token=TOKEN, tags=["Dinner", "Vegan"], foods=["Salt"], units=["gram"])
    world.invoke("add", URL)
    failed = world.invoke("run")
    assert failed.exit_code == 1 and "disk full" in failed.output
    assert (
        world.invoke("run").exit_code == 0
        and world.store().stage_status("part", ITEM_KEY, "upload") == "failed"
    )

    world.mealie.broken = False
    retry = world.invoke("retry", ITEM_KEY)
    assert retry.exit_code == 0, retry.output
    fixed = world.invoke("run")

    assert fixed.exit_code == 0, fixed.output
    assert len(world.mealie.recipes) == 1  # the half-created shell from the failed attempt was reused
    assert world.store().stage_status("part", ITEM_KEY, "upload") == "done"
    assert len(non_classify_calls(world.llm)) == 1  # only upload was redone, not the paid extraction


def test_retry_by_video_key_and_with_an_explicit_stage(world: World):
    world.invoke("add", URL)
    world.invoke("run")

    result = world.invoke("retry", "youtube:de1ppj9L4Hk", "--stage", "tag")

    assert result.exit_code == 0, result.output
    store = world.store()
    assert store.stage_status("part", ITEM_KEY, "extract") == "done"
    assert [store.stage_status("part", ITEM_KEY, s) for s in ("tag", "verify", "upload")] == [
        None,
        None,
        None,
    ]


def test_retry_with_nothing_failed_says_so(world: World):
    world.invoke("add", URL)
    world.invoke("run")

    result = world.invoke("retry", ITEM_KEY)

    assert result.exit_code == 1 and "nothing failed" in result.output


def test_reset_extract_then_run_in_update_mode_patches_the_same_recipe(world: World):
    world.invoke("add", URL)
    world.invoke("run")
    slug = next(iter(world.mealie.recipes))
    improved = load("llm_extract_okra.json")
    improved["name"] = "Bhindi Aloo, improved"
    world.llm = recipe_llm()
    world.llm.script("extract", improved)

    assert world.invoke("reset", "extract").exit_code == 0
    skipped = world.invoke("run")  # default mode: the recipe already in Mealie is left alone
    assert skipped.exit_code == 0 and world.mealie.recipes[slug]["name"] == "Chatpata Bhindi Aloo"

    world.invoke("reset", "extract")
    updated = world.invoke("run", "--mode", "update")

    assert updated.exit_code == 0, updated.output
    assert list(world.mealie.recipes) == [slug]  # still one recipe, same slug
    assert world.mealie.recipes[slug]["name"] == "Bhindi Aloo, improved"
    assert len(world.mealie.recipes[slug]["recipeIngredient"]) == 5


def test_reset_failed_only_leaves_finished_items_alone(three):
    world, urls = three
    world.llm.script("extract", LLMErrorFor(""), when_prompt_has="MARKER-BBBBBBBBBBB")
    world.llm._scripts.insert(0, world.llm._scripts.pop())
    world.invoke("add", *urls)
    world.invoke("run")
    calls = len(non_classify_calls(world.llm))

    world.llm._scripts.pop(0)  # the problem is fixed
    result = world.invoke("reset", "extract", "--failed-only")
    again = world.invoke("run")

    assert result.exit_code == 0 and again.exit_code == 0, again.output
    assert len(non_classify_calls(world.llm)) == calls + 1  # only the failed Video was extracted again
    assert names(world) == ["Dal", "Naan", "Rice"]


def test_reset_rejects_an_unknown_stage(world: World):
    result = world.invoke("reset", "bake")

    assert result.exit_code == 2 and "unknown stage" in result.output


# -- report -------------------------------------------------------------------------------


def test_report_has_one_row_per_recipe_part_and_one_per_video_without_parts(three):
    world, urls = three
    world.videos.infos.pop(watch_url("CCCCCCCCCCC"))  # metadata will fail for the third Video
    world.invoke("add", *urls)
    world.invoke("run")

    result = world.invoke("report")

    assert result.exit_code == 0, result.output
    with (world.workspace / "reports" / "report.csv").open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert list(rows[0]) == [
        "item_key", "video_url", "platform", "video_label", "link_source", "metadata_status",
        "classify_status",
        "linkcheck_status",
        "scrape_status",
        "extract_status",
        "parse_status",
        "tag_status", "verify_status", "upload_status", "score", "outcome", "failed_checks",
        "extraction_attempts", "failure_reason", "mealie_slug", "mealie_url", "created_foods",
        "tags", "warnings", "lines_agreed", "lines_nlp_preferred", "lines_conflict", "lines_unparsed",
        "suspicious_lines",
    ]  # fmt: skip
    by_video = {r["video_url"]: r for r in rows}
    assert len(rows) == 3
    dal = by_video[watch_url("AAAAAAAAAAA")]
    assert dal["item_key"] == "youtube:AAAAAAAAAAA#1"
    assert dal["platform"] == "youtube"
    assert [
        dal[f"{s}_status"]
        for s in ("metadata", "linkcheck", "scrape", "extract", "parse", "tag", "verify", "upload")
    ] == ["done"] * 8
    assert dal["mealie_slug"] == "dal" and dal["mealie_url"].endswith("/g/home/r/dal")
    assert dal["tags"] == "Dinner;Vegan"
    assert dal["created_foods"] == "3"  # okra, mustard oil, cumin seeds were first created for Video A
    assert by_video[watch_url("BBBBBBBBBBB")]["created_foods"] == "0"
    broken = by_video[watch_url("CCCCCCCCCCC")]
    assert broken["item_key"] == "" and broken["metadata_status"] == "failed"
    assert broken["failure_reason"].startswith("metadata:")


def test_the_report_is_valid_json_free_text_with_unicode(world: World):
    world.invoke("add", URL)
    world.invoke("run")
    world.invoke("report")

    text = (world.workspace / "reports" / "report.csv").read_bytes()

    assert text.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM so Excel opens it correctly
    json.dumps(text.decode("utf-8-sig"))
