"""Ticket 06 at the pipeline seam: a Video that links to a recipe page imports that page's recipe."""

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.adapters.fake_web import FakeWebFetcher
from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from mealie_pipeline.cli import app
from tests.helpers import fake_adapters
from tests.images import make_jpeg
from tests.test_pipeline_seam import (
    CANONICAL,
    ITEM_KEY,
    VIDEO_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_URL = "https://foodlab.example/bhindi-aloo/"
PAGE_IMAGE = "https://foodlab.example/wp-content/uploads/bhindi-aloo.jpg"
URL = "https://youtu.be/de1ppj9L4Hk"

WEB_ENGINE = FakeIngredientEngine(
    {
        "250 g okra (bhindi)": EngineParse(250, 250, "g", "okra", "bhindi", 0.99),
        "1 potato": EngineParse(1, 1, "", "potato", "", 0.99),
        "2 small onions": EngineParse(2, 2, "", "onions", "small", 0.99),
        "2 tbsp mustard oil": EngineParse(2, 2, "tbsps", "mustard oil", "", 0.99),
        "1/2 tsp cumin seeds": EngineParse(0.5, 0.5, "tsps", "cumin seeds", "", 0.99),
        "Salt, to taste": EngineParse(None, None, "", "salt", "to taste", 0.99),
    }
)


def page(name: str) -> str:
    return (FIXTURES / "web" / name).read_text(encoding="utf-8")


def web_ingredient(text: str, stated: bool = True) -> dict:
    return {
        "line": text,
        "original_line": text,
        "section": None,
        "quantity_stated": stated,
        "evidence": [{"source": "web", "quote": text}],
    }


def web_recipe() -> dict:
    """What the LLM returns when it only normalizes the website recipe."""
    steps = [
        "Wash the okra, dry it well and cut into thick dice.",
        "Heat the oil, add the cumin seeds and the onions and cook until translucent.",
        "Add okra and potato, cover and cook until tender. Season with salt.",
    ]
    return {
        "is_recipe": True,
        "name": "Chatpata Bhindi Aloo",
        "description": "Spicy okra and potato stir-fry.",
        "language": "en",
        "servings": 4,
        "prep_minutes": 10,
        "cook_minutes": 20,
        "total_minutes": 30,
        "ingredients": [
            web_ingredient(t)
            for t in (
                "250 g okra (bhindi)",
                "1 potato",
                "2 small onions",
                "2 tbsp mustard oil",
                "1/2 tsp cumin seeds",
            )
        ]
        + [web_ingredient("Salt, to taste", stated=False)],
        "instructions": [
            {"section": None, "text": t, "evidence": [{"source": "web", "quote": t}]} for t in steps
        ],
        "notes": [],
        "tag_choices": [{"tag": "Dinner", "reason": "main dish"}],
        "missing_info": [],
    }


class WebWorld(World):
    """The World of the earlier tickets plus a page fetcher and pinned comments."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.web = FakeWebFetcher({PAGE_URL: page("wprm_graph.html")})
        self.llm = FakeLLM()
        self.llm.script("extract", web_recipe())
        self.images.files[PAGE_IMAGE] = make_jpeg(1600)
        self.info = copy.deepcopy(load("youtube_info_okra.json"))
        self.info["description"] = f"Full recipe: {PAGE_URL}\nSubscribe for more!"
        self.videos.infos[CANONICAL] = self.info

    def invoke(self, *args: str):
        adapters = fake_adapters(
            mealie=self.mealie,
            llm=self.llm,
            videos=self.videos,
            images=self.images,
            engine=WEB_ENGINE,
            web=self.web,
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)

    def describe(self, text: str) -> None:
        self.info["description"] = text


@pytest.fixture
def world(tmp_path) -> WebWorld:
    return WebWorld(tmp_path)


def run(world: WebWorld, *args: str):
    world.invoke("add", URL)
    return world.invoke("run", *args)


def web_json(world: WebWorld) -> dict:
    path = world.workspace / "data" / "youtube" / "de1ppj9L4Hk" / "web.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_a_description_that_only_links_to_the_blog_imports_the_websites_recipe(world: WebWorld):
    result = run(world)

    assert result.exit_code == 0, result.output
    recipe = next(iter(world.mealie.recipes.values()))
    foods = {f.id: f.name for f in world.mealie.foods.values()}
    assert [foods[i["food"]["id"]] for i in recipe["recipeIngredient"]] == [
        "okra",
        "potato",
        "onion",
        "mustard oil",
        "cumin seeds",
        "Salt",  # the catalog's own spelling is reused
    ]
    assert [i["originalText"] for i in recipe["recipeIngredient"]][0] == "250 g okra (bhindi)"
    assert recipe["recipeInstructions"][2]["text"].startswith("Add okra and potato")

    (call,) = world.llm.calls
    assert "[SRC:web]" in call.prompt and "250 g okra (bhindi)" in call.prompt
    assert call.prompt.index("[SRC:web]") < call.prompt.index("[SRC:desc]")  # the website ranks first
    assert world.web.fetched == [PAGE_URL]

    stored = web_json(world)
    assert stored["link"] == stored["final_url"] == PAGE_URL
    assert stored["link_source"] == "description"
    assert stored["recipes"][0]["extraction_method"] == "json-ld"


def test_the_website_image_is_uploaded_instead_of_the_thumbnail(world: WebWorld):
    run(world)

    slug = next(iter(world.mealie.recipes))
    assert world.mealie.images[slug] == make_jpeg(1600)
    assert world.images.requests[0] == PAGE_IMAGE  # tried first


def test_the_prompt_tells_the_llm_to_keep_the_websites_quantities_and_only_fill_gaps(world: WebWorld):
    run(world)

    (call,) = world.llm.calls
    assert "Keep the website's quantities and wording and only fill gaps" in call.prompt
    system_prompt = (Path(__file__).parents[1] / "prompts" / "extract.md").read_text(encoding="utf-8")
    assert "[SRC:web]" in system_prompt and "follow its" in system_prompt


def test_evidence_from_the_website_is_grounded_so_the_gate_passes(world: WebWorld):
    run(world)

    verify = world.store().part(ITEM_KEY).verify or {}
    assert verify["outcome"] == "upload" and verify["dropped_ingredients"] == []


def test_a_short_link_is_expanded_and_the_final_url_recorded(world: WebWorld):
    world.describe("Recipe: https://bit.ly/3xyz")
    world.web.redirects["https://bit.ly/3xyz"] = PAGE_URL

    result = run(world)

    assert result.exit_code == 0, result.output
    assert world.web.expanded == ["https://bit.ly/3xyz"]
    stored = web_json(world)
    assert (stored["link"], stored["final_url"]) == ("https://bit.ly/3xyz", PAGE_URL)
    assert len(world.mealie.recipes) == 1


def test_a_short_link_that_leads_to_a_shop_is_dropped_after_expansion(world: WebWorld):
    world.describe("Get the pan: https://geni.us/pan")
    world.web.redirects["https://geni.us/pan"] = "https://www.amazon.com/dp/B000123"
    world.llm = FakeLLM()
    world.llm.script("extract", load("llm_extract_okra.json"))
    world.info["description"] += "\n" + load("youtube_info_okra.json")["description"]

    result = run(world)

    assert result.exit_code == 0, result.output
    assert world.web.fetched == []  # nothing fetched: the shop is on the denylist
    assert web_json(world)["reason"] == "no_link"


def test_social_and_affiliate_links_are_never_fetched(world: WebWorld):
    world.describe("Follow https://www.instagram.com/chef and buy https://amzn.to/3abc")
    world.llm = FakeLLM()

    run(world)

    assert world.web.fetched == [] and world.web.expanded == []  # denied outright, not even expanded
    assert web_json(world)["reason"] == "no_link"


def test_the_recipe_link_in_the_creators_pinned_comment_is_used(world: WebWorld):
    world.describe("Today: crispy okra!")
    world.videos.pinned[CANONICAL] = f"Written recipe here: {PAGE_URL}"

    result = run(world)

    assert result.exit_code == 0, result.output
    assert web_json(world)["link_source"] == "comment"


def test_a_blocked_page_is_marked_for_the_browser_fallback_and_the_video_still_imports(world: WebWorld):
    world.describe(f"Recipe: {PAGE_URL}\n" + load("youtube_info_okra.json")["description"])
    world.web.blocked[PAGE_URL] = "needs_browser"
    world.llm = FakeLLM()
    world.llm.script("extract", load("llm_extract_okra.json"))

    result = run(world)

    assert result.exit_code == 0, result.output  # not a failure
    assert "needs_browser" in result.output
    assert web_json(world)["reason"] == "needs_browser"
    assert "[SRC:web]" not in world.llm.calls[0].prompt
    assert len(world.mealie.recipes) == 1  # imported from the description as before
    assert world.store().stage_status("video", VIDEO_KEY, "scrape") == "done"


def test_a_page_with_no_recipe_is_not_used(world: WebWorld):
    world.web.pages[PAGE_URL] = page("no_recipe.html")  # plain article without an ingredient list
    world.describe(f"Recipe: {PAGE_URL}\n" + load("youtube_info_okra.json")["description"])
    world.llm = FakeLLM()
    world.llm.script("extract", load("llm_extract_okra.json"))

    run(world)

    assert web_json(world)["reason"] == "no_recipe"
    assert "[SRC:web]" not in world.llm.calls[0].prompt


def test_unstructured_page_text_that_mentions_ingredients_is_a_lower_priority_web_source(world: WebWorld):
    body = "<p>Ingredients: okra, onions and oil. Cook them all.</p>"
    filler = "<p>A long sentence about cooking okra at home with friends.</p>" * 12
    world.web.pages[PAGE_URL] = f"<html><body><article><h1>Okra</h1>{filler}{body}</article></body></html>"

    run(world)

    call = world.llm.calls[0]
    assert "[SRC:web]" in call.prompt and "unstructured text from the creator's website" in call.prompt
    assert web_json(world)["recipes"][0]["extraction_method"] == "main-text"


def test_the_recipe_closest_to_the_video_title_is_chosen_on_a_multi_recipe_page(world: WebWorld):
    world.web.pages[PAGE_URL] = page("two_recipes.html")
    world.info["title"] = "Fresh Pesto in 2 minutes"
    world.llm = FakeLLM()
    world.llm.script("extract", {"is_recipe": False, "name": "x"})

    run(world)

    stored = web_json(world)
    assert [r["name"] for r in stored["recipes"]] == ["Tomato Sauce", "Pesto"]
    assert stored["chosen"] == 1
    assert "Pesto" in world.llm.calls[0].prompt and "Tomato Sauce" not in world.llm.calls[0].prompt


def test_extract_waits_for_scrape(world: WebWorld):
    world.invoke("add", URL)
    world.invoke("run", "--stages", "metadata,extract")

    assert world.llm.calls == []  # scrape has not run, so the Video is not extracted yet

    world.invoke("run")

    assert len(world.llm.calls) == 1 and len(world.mealie.recipes) == 1


def test_the_page_is_fetched_once_even_if_the_run_is_repeated(world: WebWorld):
    run(world)
    world.invoke("run")
    world.invoke("reset", "extract")
    world.invoke("run", "--mode", "update")

    assert world.web.fetched == [PAGE_URL]  # `reset extract` does not redo `scrape`


def test_a_video_already_in_mealie_is_not_scraped_or_extracted(world: WebWorld):
    slug = world.mealie.create_recipe("Old import")
    world.mealie.patch_recipe(slug, {"orgURL": CANONICAL})

    result = run(world)

    assert result.exit_code == 0, result.output
    assert world.web.fetched == [] and world.web.expanded == [] and world.llm.calls == []
    assert world.store().stage_status("video", VIDEO_KEY, "scrape") is None


def test_report_shows_the_scrape_stage(world: WebWorld):
    run(world)
    world.invoke("report")

    header = (world.workspace / "reports" / "report.csv").read_text(encoding="utf-8-sig").splitlines()[0]
    assert "scrape_status" in header.split(",")
