"""The pipeline seam for ticket 02: `mp add` + `mp run` on fakes, asserting on Mealie and the store."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.downloader import FakeImageDownloader
from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_video_source import FakeVideoSource
from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from mealie_pipeline.adapters.llm import LLMError, UsageLimited
from mealie_pipeline.cli import app
from mealie_pipeline.errors import MealieHttpError
from mealie_pipeline.store import StateStore
from tests.helpers import fake_adapters, non_classify_calls, recipe_llm
from tests.images import make_jpeg

FIXTURES = Path(__file__).parent / "fixtures"
TOKEN = "test-token-1234567890"
URL = "https://youtu.be/de1ppj9L4Hk?si=tracking"
VIDEO_KEY = "youtube:de1ppj9L4Hk"
ITEM_KEY = f"{VIDEO_KEY}#1"
MAXRES = "https://i.ytimg.com/vi/de1ppj9L4Hk/maxresdefault.jpg"
CANONICAL = "https://www.youtube.com/watch?v=de1ppj9L4Hk"

ENGINE = FakeIngredientEngine(
    {
        "250 g okra": EngineParse(250, 250, "g", "okra", "", 0.99),
        "2 small onions": EngineParse(2, 2, "", "onions", "small", 0.99),
        "2 tbsp mustard oil": EngineParse(2, 2, "tbsps", "mustard oil", "", 0.99),
        "1/2 tsp cumin seeds": EngineParse(0.5, 0.5, "tsps", "cumin seeds", "", 0.99),
        "salt, to taste": EngineParse(None, None, "", "salt", "to taste", 0.99),
    }
)


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FlakyImageMealie(FakeMealie):
    """A Mealie whose image endpoints can be switched off."""

    file_upload_fails = False
    url_import_fails = False

    def upload_image(self, slug: str, path: Path) -> None:
        if self.file_upload_fails:
            raise MealieHttpError("PUT", f"/api/recipes/{slug}/image", 500, "boom")
        super().upload_image(slug, path)

    def set_image_from_url(self, slug: str, url: str) -> None:
        if self.url_import_fails:
            raise MealieHttpError("POST", f"/api/recipes/{slug}/image", 400, "not an image")
        super().set_image_from_url(slug, url)


class World:
    """A temp workspace plus a full set of fakes, driven through the `mp` CLI."""

    def __init__(self, tmp_path: Path):
        self.workspace = tmp_path
        (tmp_path / ".env").write_text(
            f"MEALIE_URL=http://fake:9000\nMEALIE_TOKEN={TOKEN}\n", encoding="utf-8"
        )
        (tmp_path / "config").mkdir()
        (tmp_path / "config" / "units.yaml").write_text(
            (Path(__file__).parents[1] / "config" / "units.yaml").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        self.mealie = FlakyImageMealie(
            token=TOKEN,
            tags=["Dinner", "Vegan", "Breakfast"],
            foods=["Salt", "onion"],
            units=["gram", "tablespoon"],
        )
        self.llm = recipe_llm()
        self.llm.script("extract", load("llm_extract_okra.json"))
        self.images = FakeImageDownloader({MAXRES: make_jpeg(1280)})
        self.videos = FakeVideoSource({CANONICAL: load("youtube_info_okra.json")})

    def invoke(self, *args: str):
        adapters = fake_adapters(
            mealie=self.mealie, llm=self.llm, videos=self.videos, images=self.images, engine=ENGINE
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)

    def store(self) -> StateStore:
        return StateStore(self.workspace / "pipeline.db")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def test_one_video_becomes_one_parsed_tagged_recipe_with_image(world: World):
    assert world.invoke("add", URL).exit_code == 0
    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 1
    recipe = next(iter(world.mealie.recipes.values()))
    assert recipe["name"] == "Chatpata Bhindi Aloo"
    assert recipe["orgURL"] == CANONICAL
    assert recipe["extras"]["item_key"] == ITEM_KEY
    assert recipe["extras"]["video_key"] == VIDEO_KEY
    assert recipe["extras"]["platform"] == "youtube"
    assert (recipe["extras"]["part"], recipe["extras"]["of"]) == (1, 1)
    assert recipe["prepTime"] == "PT10M" and recipe["performTime"] == "PT20M"
    assert recipe["totalTime"] == "PT30M"
    assert [t["name"] for t in recipe["tags"]] == ["Dinner", "Vegan"]  # "Made Up Tag" is dropped
    assert len(recipe["recipeInstructions"]) == 3

    foods = {f.id: f.name for f in world.mealie.foods.values()}
    units = {u.id: u.name for u in world.mealie.units.values()}
    lines = [
        (i["quantity"], units.get((i["unit"] or {}).get("id", "")), foods[i["food"]["id"]], i["note"])
        for i in recipe["recipeIngredient"]
    ]
    assert lines == [
        (250, "gram", "okra", ""),
        (2, None, "onion", "small"),  # reused the catalog's "onion", not a new "onions"
        (2, "tablespoon", "mustard oil", ""),
        (0.5, "teaspoon", "cumin seeds", ""),  # "teaspoon" did not exist and was created
        (0, None, "Salt", "to taste"),  # reused the catalog's capitalised "Salt"
    ]
    assert world.mealie.images[recipe["slug"]] == make_jpeg(1280)
    assert f"/g/home/r/{recipe['slug']}" in result.output


def test_new_foods_and_units_are_logged_with_the_video_they_came_from(world: World):
    world.invoke("add", URL)
    world.invoke("run")

    foods = (world.workspace / "reports" / "created_foods.csv").read_text(encoding="utf-8-sig").splitlines()
    assert foods[0] == "name,first_video_key,created_at"
    assert [row.split(",")[:2] for row in foods[1:]] == [
        ["okra", VIDEO_KEY],
        ["mustard oil", VIDEO_KEY],
        ["cumin seeds", VIDEO_KEY],
    ]
    units = (world.workspace / "reports" / "created_units.csv").read_text(encoding="utf-8-sig").splitlines()
    assert [row.split(",")[:2] for row in units[1:]] == [["teaspoon", VIDEO_KEY]]


def test_a_second_run_makes_no_new_writes_and_no_new_llm_calls(world: World):
    world.invoke("add", URL)
    world.invoke("run")
    before = {slug: json.dumps(r, sort_keys=True) for slug, r in world.mealie.recipes.items()}
    food_count, llm_calls, metadata_calls = (
        len(world.mealie.foods),
        len(non_classify_calls(world.llm)),
        len(world.videos.calls),
    )

    again = world.invoke("run")
    world.invoke("add", URL)  # adding the same Video again registers nothing

    assert again.exit_code == 0, again.output
    assert {slug: json.dumps(r, sort_keys=True) for slug, r in world.mealie.recipes.items()} == before
    assert len(world.mealie.foods) == food_count
    assert (len(non_classify_calls(world.llm)), len(world.videos.calls)) == (llm_calls, metadata_calls)
    assert len(world.store().videos()) == 1


def test_the_store_records_slug_and_link_and_every_stage_done(world: World):
    world.invoke("add", URL)
    world.invoke("run")

    store = world.store()
    part = store.part(ITEM_KEY)
    assert part.slug in world.mealie.recipes
    assert part.mealie_url == f"http://fake-mealie:9000/g/home/r/{part.slug}"
    assert store.stage_status("video", VIDEO_KEY, "metadata") == "done"
    for stage in ("extract", "parse", "tag", "verify", "upload"):
        assert store.stage_status("part", ITEM_KEY, stage) == "done"


def test_the_llm_is_asked_for_existing_tags_only_using_the_description(world: World):
    world.invoke("add", URL)
    world.invoke("run")

    (call,) = non_classify_calls(world.llm)
    assert call.task == "extract" and call.tier == "strong"
    assert "[SRC:desc]" in call.prompt and "250 g okra (bhindi)" in call.prompt
    assert call.schema["$defs"]["TagChoice"]["properties"]["tag"]["enum"] == ["Breakfast", "Dinner", "Vegan"]


def test_dry_run_writes_the_payload_and_touches_nothing_in_mealie(world: World):
    world.invoke("add", URL)
    result = world.invoke("run", "--dry-run")

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}
    assert len(world.mealie.foods) == 2 and len(world.mealie.units) == 2  # nothing created
    payload = json.loads(
        (world.workspace / "work" / "payloads" / "youtube_de1ppj9L4Hk_1.json").read_text(encoding="utf-8")
    )
    assert payload["name"] == "Chatpata Bhindi Aloo"
    assert payload["extras"]["item_key"] == ITEM_KEY
    assert [i["food"]["name"] for i in payload["recipeIngredient"]] == [
        "okra",
        "onion",
        "mustard oil",
        "cumin seeds",
        "Salt",
    ]
    # A later real run still uploads it.
    assert world.invoke("run").exit_code == 0
    assert len(world.mealie.recipes) == 1


def test_file_upload_fails_but_mealie_fetching_the_url_works(world: World):
    world.mealie.file_upload_fails = True
    world.invoke("add", URL)
    result = world.invoke("run")

    slug = next(iter(world.mealie.recipes))
    assert result.exit_code == 0, result.output
    assert world.mealie.images[slug] == MAXRES


def test_when_both_image_routes_fail_the_recipe_stays_and_is_marked_image_missing(world: World):
    world.mealie.file_upload_fails = world.mealie.url_import_fails = True
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 0, result.output  # a warning, not a failure
    assert len(world.mealie.recipes) == 1
    assert "image_missing" in result.output
    assert world.store().part(ITEM_KEY).warnings == ["image_missing"]


def test_a_missing_maxres_thumbnail_falls_back_to_hqdefault(world: World):
    hq = "https://i.ytimg.com/vi/de1ppj9L4Hk/hqdefault.jpg"
    world.images = FakeImageDownloader({hq: make_jpeg(480)})
    world.invoke("add", URL)
    world.invoke("run")

    assert world.mealie.images[next(iter(world.mealie.recipes))] == make_jpeg(480)


def test_a_description_without_a_recipe_fails_that_item_and_uploads_nothing(world: World):
    world.llm = recipe_llm()
    world.llm.script("extract", {"is_recipe": False, "name": "Vlog"})
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 1
    assert world.mealie.recipes == {}
    assert world.store().stage_status("part", ITEM_KEY, "extract") == "failed"
    assert "does not contain a recipe" in result.output


def test_no_matching_tag_fails_the_item(world: World):
    recipe = load("llm_extract_okra.json")
    recipe["tag_choices"] = [{"tag": "Made Up Tag", "reason": "x"}]
    world.llm = recipe_llm()
    world.llm.script("extract", recipe)
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 1
    assert world.mealie.recipes == {}
    assert world.store().stage_status("part", ITEM_KEY, "tag") == "failed"


def test_an_llm_error_fails_only_that_item_and_the_next_run_does_not_retry_it(world: World):
    world.llm = recipe_llm()
    world.llm.script("extract", LLMError("claude failed: boom"))
    world.invoke("add", URL)
    first = world.invoke("run")
    second = world.invoke("run")

    assert first.exit_code == 1 and "claude failed: boom" in first.output
    assert second.exit_code == 0 and len(non_classify_calls(world.llm)) == 1


def test_a_usage_limit_stops_the_run_and_leaves_the_item_pending(world: World):
    world.llm = recipe_llm()
    world.llm.script("extract", UsageLimited("usage limit reached"))
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 1 and "usage limit" in result.output
    assert world.store().stage_status("part", ITEM_KEY, "extract") == "pending"


def test_upload_fails_the_item_when_the_read_back_differs(world: World):
    class Lossy(FlakyImageMealie):
        def get_recipe(self, slug: str):
            recipe = super().get_recipe(slug)
            recipe["recipeIngredient"] = recipe["recipeIngredient"][:-1]
            return recipe

    world.mealie = Lossy(token=TOKEN, tags=["Dinner", "Vegan"], foods=["Salt"], units=["gram"])
    world.invoke("add", URL)
    result = world.invoke("run")

    assert result.exit_code == 1
    assert "ingredient count 4, expected 5" in result.output
    assert world.store().stage_status("part", ITEM_KEY, "upload") == "failed"


def test_a_recipe_already_in_mealie_under_the_item_key_is_recorded_not_duplicated(world: World):
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,linkcheck,scrape,extract,parse,tag")
    slug = world.mealie.create_recipe("Chatpata Bhindi Aloo")
    world.mealie.patch_recipe(
        slug, {"extras": {"item_key": ITEM_KEY}, "recipeIngredient": [{"quantity": 1, "note": "x"}]}
    )

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 1
    assert world.store().part(ITEM_KEY).slug == slug


def test_unsupported_urls_are_reported(world: World):
    result = world.invoke("add", "https://example.com/not-a-video")
    assert result.exit_code == 0 and "unsupported URL" in result.output  # reported, not fatal
