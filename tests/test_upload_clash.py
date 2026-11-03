"""Ticket 37: an upload whose name another Mealie recipe already holds."""

import csv

import pytest

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.mealie_http import MealieHttpGateway
from mealie_pipeline.name_clash import distinct_name, find_clash, same_source, slug_of
from tests.mealie_server import FakeMealieServer
from tests.test_pipeline_seam import (
    CANONICAL,
    ITEM_KEY,
    TOKEN,
    URL,
    FlakyImageMealie,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
)
from tests.test_scrape_seam import PAGE_URL, WebWorld

NAME = "Chatpata Bhindi Aloo"


def clashes(world: World) -> list[dict[str, str]]:
    path = world.workspace / "reports" / "upload_clashes.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def existing(mealie: FakeMealie, name: str, org_url: str | None) -> str:
    """A recipe already in Mealie, for example from the recipe-name list import."""
    slug = mealie.create_recipe(name)
    mealie.recipes[slug].update(
        orgURL=org_url, recipeIngredient=[{"note": "1 thing"}], recipeInstructions=[{"text": "Cook."}]
    )
    return slug


# -- pure -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "slug"),
    [
        ("Chatpata Bhindi Aloo", "chatpata-bhindi-aloo"),
        ("Crème Brûlée!", "creme-brulee"),
        ("Bhindi Aloo (Your Food Lab)", "bhindi-aloo-your-food-lab"),
        ("آلو بھنڈی", "آلو-بھنڈی"),
    ],
)
def test_slug_of_matches_mealies_slugs(name, slug):
    assert slug_of(name) == slug


def test_a_clash_is_found_by_slug_or_by_name_but_never_with_the_items_own_recipe():
    summaries = [{"slug": "dal", "name": "Dal", "orgURL": None}, {"slug": "okra-1", "name": "OKRA"}]
    assert find_clash("dal", summaries, set()) is not None
    assert find_clash("Okra", summaries, set()).slug == "okra-1"  # type: ignore[union-attr]
    assert find_clash("Dal", summaries, {"dal"}) is None
    assert find_clash("Paneer", summaries, set()) is None


def test_the_same_source_is_recognised_through_url_normalization():
    page = "https://foodlab.example/bhindi-aloo/?utm_source=yt"
    assert same_source(page, ["https://www.youtube.com/watch?v=x", "https://foodlab.example/bhindi-aloo/"])
    assert same_source("https://youtu.be/de1ppj9L4Hk", [CANONICAL])
    assert not same_source("https://other.example/okra", [CANONICAL, PAGE_URL])
    assert not same_source("", [CANONICAL])


def test_the_distinguishing_name_uses_the_first_free_qualifier_then_a_number():
    assert distinct_name("Dal", ["@yourfoodlab", "x.com"], set()) == "Dal (yourfoodlab)"
    assert distinct_name("Dal", ["", "foodlab.example"], set()) == "Dal (foodlab.example)"
    taken = {"dal-yourfoodlab", "dal-youtube"}
    assert distinct_name("Dal", ["yourfoodlab", "Youtube"], taken) == "Dal (yourfoodlab) 2"


# -- pipeline seam --------------------------------------------------------------------------


def test_a_different_recipe_with_the_same_name_gets_a_distinguishing_name(tmp_path):
    world = World(tmp_path)
    theirs = existing(world.mealie, NAME, "https://www.example-blog.com/bhindi")
    assert world.invoke("add", URL).exit_code == 0

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 2
    assert world.mealie.recipes[theirs]["orgURL"] == "https://www.example-blog.com/bhindi"  # untouched
    ours = next(r for s, r in world.mealie.recipes.items() if s != theirs)
    assert ours["name"] == f"{NAME} (yourfoodlab)"
    assert ours["orgURL"] == CANONICAL
    assert world.store().part(ITEM_KEY).slug == ours["slug"]
    [row] = clashes(world)
    assert row["item_key"] == ITEM_KEY and row["existing_slug"] == theirs
    assert row["decision"] == "different recipe: renamed" and row["uploaded_as"] == f"{NAME} (yourfoodlab)"


def test_a_hand_made_recipe_without_a_link_is_a_different_recipe(tmp_path):
    world = World(tmp_path)
    existing(world.mealie, NAME, None)
    world.invoke("add", URL)

    assert world.invoke("run").exit_code == 0
    assert sorted(r["name"] for r in world.mealie.recipes.values()) == [NAME, f"{NAME} (yourfoodlab)"]


def test_the_same_recipe_from_the_name_list_import_is_skipped_not_duplicated(tmp_path):
    world = WebWorld(tmp_path)  # the Video links PAGE_URL, the page the list import already used
    theirs = existing(world.mealie, NAME, PAGE_URL)
    before = dict(world.mealie.recipes[theirs])
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert list(world.mealie.recipes) == [theirs]
    assert world.mealie.recipes[theirs] == before  # never overwritten
    store = world.store()
    assert store.stage_status("part", ITEM_KEY, "upload") == "already_in_mealie"
    assert "already_in_mealie" in result.output
    [row] = clashes(world)
    assert row["decision"] == "same recipe: skipped" and row["existing_url"] == PAGE_URL


def test_an_empty_shell_left_by_an_earlier_failed_upload_is_reused_not_duplicated(tmp_path):
    """The old failure: POST made "Name (1)" (`name-1`), then the PATCH back to "Name" was refused."""
    world = World(tmp_path)
    theirs = existing(world.mealie, NAME, "https://www.example-blog.com/bhindi")
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,classify,linkcheck,scrape,outline,extract,parse,tag,verify")
    shell = world.mealie.create_recipe(NAME)
    assert shell == "chatpata-bhindi-aloo-1"
    world.store().update_part(ITEM_KEY, slug=shell)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 2  # the shell became our recipe; nothing new was created
    ours = next(r for s, r in world.mealie.recipes.items() if s != theirs)
    assert ours["name"] == f"{NAME} (yourfoodlab)" and ours["recipeIngredient"]


def test_the_same_recipe_with_an_empty_shell_removes_only_the_shell(tmp_path):
    world = WebWorld(tmp_path)
    theirs = existing(world.mealie, NAME, PAGE_URL)
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,classify")
    world.mealie.recipes[theirs]["orgURL"] = None  # hides it from the early link check ...
    world.invoke("run", "--stages", "linkcheck,scrape,outline,extract,parse,tag,verify")
    world.mealie.recipes[theirs]["orgURL"] = PAGE_URL  # ... and it is back for the upload
    shell = world.mealie.create_recipe(NAME)
    world.store().update_part(ITEM_KEY, slug=shell)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert list(world.mealie.recipes) == [theirs]


def test_a_same_name_upload_works_against_the_local_mealie_server(tmp_path, httpserver):
    """Against the local Mealie server: the real gateway sees Mealie's own 400 if the clash slips."""
    world = World(tmp_path)
    fake = FakeMealie(token=TOKEN, tags=["Dinner", "Vegan"], foods=["Salt", "onion"], units=["gram"])
    FakeMealieServer(httpserver, fake)
    world.mealie = MealieHttpGateway(  # type: ignore[assignment]
        httpserver.url_for("").rstrip("/"), TOKEN, sleep=lambda _s: None
    )
    existing(fake, NAME, "https://www.example-blog.com/bhindi")
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert sorted(r["name"] for r in fake.recipes.values()) == [NAME, f"{NAME} (yourfoodlab)"]


def test_a_name_taken_after_the_listing_is_renamed_on_mealies_400(tmp_path):
    class StaleListing(FlakyImageMealie):
        """The first listing misses a recipe another client has just made."""

        listings = 0

        def list_recipe_summaries(self):
            self.listings += 1
            summaries = super().list_recipe_summaries()
            return [s for s in summaries if s["slug"] != slug_of(NAME)] if self.listings == 1 else summaries

    world = World(tmp_path)
    world.mealie = StaleListing(
        token=TOKEN, tags=["Dinner", "Vegan"], foods=["Salt", "onion"], units=["gram"]
    )
    existing(world.mealie, NAME, "https://elsewhere.example/okra")
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert sorted(r["name"] for r in world.mealie.recipes.values()) == [NAME, f"{NAME} (yourfoodlab)"]
