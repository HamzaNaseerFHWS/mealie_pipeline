"""Ticket 22 at the pipeline seam: a Video whose link is already in Mealie is never done twice."""

import copy
import csv
import json

import pytest

from tests.test_pipeline_seam import (
    ITEM_KEY,
    URL,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
)

__all__ = ["clean_environment"]

# The same Video as URL, with other tracking parameters and a timestamp.
OLD_IMPORT_URL = "https://www.youtube.com/watch?v=de1ppj9L4Hk&si=other&t=95s"


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def old_import(world: World, org_url: str | None = OLD_IMPORT_URL, **extra) -> str:
    """A recipe the user imported earlier (badly parsed: one text ingredient, a rating, comments)."""
    slug = world.mealie.create_recipe("Bhindi (old import)")
    world.mealie.patch_recipe(
        slug,
        {
            "orgURL": org_url,
            "recipeIngredient": [{"quantity": 0, "note": "250 g okra, 2 onions, salt"}],
            "recipeInstructions": [{"text": "Cook everything."}],
            "rating": 4,
            "dateAdded": "2024-03-01",
            "comments": [{"text": "Made it twice!"}],
            "extras": {"imported_by": "mealie"},
            **extra,
        },
    )
    return slug


def snapshot(world: World) -> str:
    return json.dumps(world.mealie.recipes, sort_keys=True)


def report_rows(world: World) -> list[dict[str, str]]:
    world.invoke("report")
    path = world.workspace / "reports" / "report.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_a_video_already_in_mealie_costs_no_llm_call_and_no_mealie_write(world: World):
    slug = old_import(world)
    before, foods, tags, units = (
        snapshot(world),
        len(world.mealie.foods),
        len(world.mealie.tags),
        len(world.mealie.units),
    )
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert world.llm.calls == []  # zero LLM calls
    assert snapshot(world) == before  # the old recipe is untouched and nothing new exists
    assert (len(world.mealie.foods), len(world.mealie.tags), len(world.mealie.units)) == (foods, tags, units)
    assert world.images.requests == []
    assert "already_in_mealie" in result.output and f"/g/home/r/{slug}" in result.output
    assert "1 already in Mealie (skipped), 0 existing recipes upgraded" in result.output

    (row,) = report_rows(world)
    assert row["linkcheck_status"] == "already_in_mealie"
    assert row["mealie_url"] == f"http://fake-mealie:9000/g/home/r/{slug}"
    assert (row["extract_status"], row["upload_status"]) == ("", "")  # every later stage skipped


def test_a_rerun_after_the_skip_does_nothing_more(world: World):
    old_import(world)
    world.invoke("add", URL)
    world.invoke("run")

    again = world.invoke("run")

    assert again.exit_code == 0 and world.llm.calls == []
    assert "already_in_mealie" not in again.output  # nothing left to process


def test_status_counts_the_skipped_videos(world: World):
    old_import(world)
    world.invoke("add", URL)
    world.invoke("run")

    out = world.invoke("status").output

    assert "Already in Mealie: 1   Upgraded existing: 0" in out


def test_a_recipe_with_the_same_name_but_no_link_is_not_matched(world: World):
    world.mealie.create_recipe("Chatpata Bhindi Aloo")  # no orgURL: names are never matched
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.llm.calls) == 1
    assert len(world.mealie.recipes) == 2


def test_the_link_is_checked_again_right_before_upload(world: World):
    world.invoke("add", URL)
    first = world.invoke("run", "--stages", "metadata,linkcheck,extract,parse,tag,verify")
    assert first.exit_code == 0, first.output
    assert len(world.llm.calls) == 1 and world.mealie.recipes == {}
    slug = old_import(world)  # it appears in Mealie after extraction, before upload
    before = snapshot(world)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert snapshot(world) == before  # no upload, no write
    assert world.store().stage_status("part", ITEM_KEY, "upload") == "already_in_mealie"
    assert f"/g/home/r/{slug}" in result.output
    assert report_rows(world)[0]["upload_status"] == "already_in_mealie"


def test_the_pre_upload_check_lists_mealie_once_per_batch(world: World):
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,linkcheck,extract,parse,tag,verify")
    calls = []
    original = world.mealie.list_recipe_summaries
    world.mealie.list_recipe_summaries = lambda: (calls.append(1), original())[1]  # type: ignore[method-assign]

    world.invoke("run")

    assert len(calls) == 1  # the linkcheck batch was empty (no listing); the upload batch lists once


def test_the_recipe_the_pipeline_uploaded_is_not_mistaken_for_an_old_import(world: World):
    world.invoke("add", URL)
    world.invoke("run")
    slug = next(iter(world.mealie.recipes))
    world.mealie.recipes[slug]["name"] = "Edited by hand"

    assert world.invoke("reset", "linkcheck").exit_code == 0
    again = world.invoke("run", "--mode", "update")

    assert again.exit_code == 0, again.output
    assert "already_in_mealie" not in again.output
    assert world.mealie.recipes[slug]["name"] == "Chatpata Bhindi Aloo"  # updated in place, same recipe
    assert len(world.mealie.recipes) == 1


# -- --upgrade-existing ----------------------------------------------------------------------


def test_default_mode_never_writes_to_a_recipe_the_pipeline_did_not_create(world: World):
    old_import(world)
    before = snapshot(world)
    world.invoke("add", URL)

    world.invoke("run")
    world.invoke("run", "--mode", "update")  # even update mode only touches the pipeline's own recipes

    assert snapshot(world) == before


def test_upgrade_existing_patches_the_old_import_in_place(world: World):
    slug = old_import(world, tags=[{"id": "t-old", "name": "Family Favourite", "slug": "family-favourite"}])
    original = copy.deepcopy(world.mealie.recipes[slug])
    world.invoke("add", URL)

    result = world.invoke("run", "--upgrade-existing")

    assert result.exit_code == 0, result.output
    assert list(world.mealie.recipes) == [slug]  # no second copy
    upgraded = world.mealie.recipes[slug]
    # Kept: name, rating, comments, dateAdded, source link and the old extras.
    for field in ("name", "rating", "comments", "dateAdded", "orgURL"):
        assert upgraded[field] == original[field]
    assert upgraded["extras"]["imported_by"] == "mealie"
    assert upgraded["extras"]["item_key"] == ITEM_KEY
    # Replaced: parsed ingredients and steps; tags are added to, not replaced.
    assert len(upgraded["recipeIngredient"]) == 5
    assert all(i["food"]["id"] in world.mealie.foods for i in upgraded["recipeIngredient"])
    assert [t["name"] for t in upgraded["tags"]] == ["Family Favourite", "Dinner", "Vegan"]
    assert len(upgraded["recipeInstructions"]) == 3
    assert slug not in world.mealie.images  # the image is left alone
    assert world.store().stage_status("part", ITEM_KEY, "upload") == "upgraded_existing"
    assert "1 existing recipes upgraded" in result.output
    assert report_rows(world)[0]["upload_status"] == "upgraded_existing"
    assert "Upgraded existing: 1" in world.invoke("status").output


def test_an_upgraded_recipe_is_not_upgraded_again_on_the_next_run(world: World):
    slug = old_import(world)
    world.invoke("add", URL)
    world.invoke("run", "--upgrade-existing")
    after = snapshot(world)
    calls = len(world.llm.calls)

    again = world.invoke("run", "--upgrade-existing")

    assert again.exit_code == 0 and snapshot(world) == after and len(world.llm.calls) == calls
    assert world.store().part(ITEM_KEY).slug == slug
