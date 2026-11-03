"""Ticket 39: ingredients-only captions become recipes; Videos with no usable text become stubs."""

import copy
import csv

import pytest

from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.models import ExtractedRecipe, ParsedIngredient
from mealie_pipeline.partial import has_usable_text, ingredient_lines, recipe_kind, stub_name
from mealie_pipeline.settings import VerifySettings
from mealie_pipeline.verify import evaluate
from tests.helpers import classify_as, non_classify_calls, recipe_llm
from tests.test_pipeline_seam import (
    CANONICAL,
    ITEM_KEY,
    MAXRES,
    URL,
    VIDEO_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)
from tests.test_scrape_seam import PAGE_URL, WebWorld, web_recipe

INGREDIENTS_ONLY = (
    "Crispy bhindi aloo 😍\n\nIngredients:\n250 g okra (bhindi)\n2 small onions\n2 tbsp mustard oil\n"
    "1/2 tsp cumin seeds\nSalt, to taste\n\n#okra #bhindi #reels"
)
HASHTAGS_ONLY = "😍🔥🔥 #okra #bhindi #desifood #reels @yourfoodlab"


def ingredients_only_extraction() -> dict:
    recipe = load("llm_extract_okra.json")
    recipe["instructions"] = []
    return recipe


# -- pure: "has usable text" ----------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        INGREDIENTS_ONLY,
        "Ingredients: flour, sugar, eggs, butter",
        "Zutaten:\n- 500 g Muschelnudeln\n- 2 EL Tomatenmark",
        "- 1 cup rice\n- 2 cups water",
        "Heat the oil and fry the onions until golden. Add the chicken and stir well, then add the "
        "tomatoes and simmer for twenty minutes. Season with salt and serve hot with rice.",
    ],
)
def test_text_with_ingredients_or_a_method_is_usable(text):
    assert has_usable_text([text])


@pytest.mark.parametrize(
    "text",
    [
        HASHTAGS_ONLY,
        "",
        "Full recipe on my website, link in bio 👆 Follow @yourfoodlab for more! https://linktr.ee/x",
        "Day 1 of my diet. Who else loves okra? Comment below 👇 #foodie",
        "Best biryani in Lahore 🔥",
    ],
)
def test_hashtags_emoji_and_promo_text_are_not_usable(text):
    assert not has_usable_text([text])


def test_a_pinned_comment_with_the_list_makes_a_hashtag_caption_usable():
    assert has_usable_text([HASHTAGS_ONLY, "Recipe:\n2 cups flour\n1 tsp salt"])


def test_ingredient_lines_counts_amounts_and_bullets_under_a_heading():
    assert ingredient_lines("Ingredients\n• okra\n• potato\n• onion") == 3
    assert ingredient_lines("I made 2 kinds of dal today") == 0


# -- pure: the stub's name ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "caption", "name"),
    [
        ("Crispy Okra Fry | Your Food Lab", "", "Crispy Okra Fry"),
        ("Paneer tikka 😍🔥 #shorts", "", "Paneer tikka"),
        ("", "#reels\n😍 best paneer tikka ever! #food", "Best paneer tikka ever"),
        ("😍🔥", "#food #yum", None),
        ("", "", None),
    ],
)
def test_the_stub_name_comes_from_the_title_or_the_first_caption_line(title, caption, name):
    assert stub_name(title, caption) == name


def test_recipe_kind():
    assert recipe_kind({"ingredients": [1], "instructions": [1]}) == "full"
    assert recipe_kind({"ingredients": [1], "instructions": []}) == "partial"
    assert recipe_kind({"ingredients": [], "instructions": []}) == "stub"


# -- pure: the Gate on a partial recipe -----------------------------------------------------


def _gate(recipe: dict, desc: str, *, partial: bool):
    extracted = ExtractedRecipe.model_validate(recipe)
    parsed = [
        ParsedIngredient(original_text=i.original_line, food_name=i.line, food_id="f", quantity_stated=True)
        for i in extracted.ingredients
    ]
    tags = [{"id": "t", "name": "Dinner", "slug": "dinner"}]
    return evaluate(extracted, parsed, tags, {"desc": desc}, [], VerifySettings(), partial=partial)


def test_the_gate_passes_an_ingredients_only_recipe_whose_ingredients_are_grounded():
    evaluation = _gate(ingredients_only_extraction(), INGREDIENTS_ONLY, partial=True)
    assert evaluation.hard_failures == []
    s2 = next(c for c in evaluation.checks if c.check_id == "S2")
    assert s2.score is None  # left out of the average, not counted as zero


def test_the_gate_fails_an_ingredients_only_recipe_whose_ingredients_are_not_grounded():
    evaluation = _gate(ingredients_only_extraction(), "Crispy bhindi #okra", partial=True)
    assert "H3" in evaluation.hard_failures


def test_without_the_partial_flag_empty_steps_still_fail_h2():
    evaluation = _gate(ingredients_only_extraction(), INGREDIENTS_ONLY, partial=False)
    assert "H2" in evaluation.hard_failures


# -- pipeline seam --------------------------------------------------------------------------


class StubWorld(World):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.llm = recipe_llm()  # no extraction scripted: each test says what extract returns
        self.info = copy.deepcopy(load("youtube_info_okra.json"))
        self.videos.infos[CANONICAL] = self.info
        self.mealie.create_tag("Youtube")

    def caption(self, text: str) -> None:
        self.info["description"] = text


def recipe(world: World) -> dict:
    [only] = world.mealie.recipes.values()
    return only


def tag_names(recipe: dict) -> list[str]:
    return [t["name"] for t in recipe["tags"]]


def test_an_ingredients_only_caption_becomes_a_recipe_without_steps(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(INGREDIENTS_ONLY)
    world.llm.script("extract", ingredients_only_extraction())
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    stored = recipe(world)
    assert len(stored["recipeIngredient"]) == 5
    assert all(i["food"] for i in stored["recipeIngredient"])  # parsed into Foods as usual
    assert stored["recipeInstructions"] == []
    assert stored["orgURL"] == CANONICAL
    assert "partial-recipe" in tag_names(stored)
    assert "partial-recipe" in {t.name for t in world.mealie.tags.values()}  # created once
    assert "(partial-recipe)" in result.output
    assert world.store().part(ITEM_KEY).verify["outcome"] in ("upload", "upload_review")  # type: ignore[index]


def test_a_linked_page_with_a_recipe_wins_over_the_ingredients_only_caption(tmp_path):
    world = WebWorld(tmp_path)
    world.describe(f"Ingredients:\n250 g okra\n1 potato\nFull recipe: {PAGE_URL}")
    world.llm.script("extract", web_recipe())
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    stored = recipe(world)
    assert stored["recipeInstructions"]
    assert "partial-recipe" not in tag_names(stored)
    assert "[SRC:web]" in non_classify_calls(world.llm)[0].prompt


def test_a_hashtags_only_caption_becomes_a_link_only_stub_without_an_extraction_call(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert not [c for c in world.llm.calls if c.task == "extract"]
    stored = recipe(world)
    assert stored["name"] == "Chatpata Bhindi Aloo"  # the title, cleaned of " | Crispy Okra Stir Fry"
    assert stored["recipeIngredient"] == [] and stored["recipeInstructions"] == []
    assert stored["orgURL"] == CANONICAL
    assert world.mealie.images[stored["slug"]]  # the thumbnail
    assert set(tag_names(stored)) >= {"link-only", "Youtube"}
    assert "(link-only)" in result.output
    assert world.store().part(ITEM_KEY).verify["outcome"] == "link_only"  # type: ignore[index]


def test_a_stub_whose_thumbnail_cannot_be_downloaded_still_uploads_and_says_so(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.images.files.pop(MAXRES)
    world.mealie.url_import_fails = True  # nor can Mealie fetch the thumbnail itself
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert recipe(world)["slug"] not in world.mealie.images
    assert "image_missing" in result.output


def test_a_stub_with_no_name_is_held_for_review(tmp_path):
    world = StubWorld(tmp_path)
    world.info["title"] = "😍🔥"
    world.caption(HASHTAGS_ONLY)
    world.invoke("add", URL)

    result = world.invoke("run")

    assert not world.mealie.recipes
    assert world.store().stage_status("part", ITEM_KEY, "extract") == "review"
    assert "REVIEW" in result.output


def test_a_restaurant_video_is_still_skipped(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.llm = FakeLLM()
    world.llm.script("classify", classify_as("restaurant_or_place"))
    world.invoke("add", URL)

    world.invoke("run")

    assert not world.mealie.recipes
    assert world.store().stage_status("video", VIDEO_KEY, "classify") == "skipped"


def test_the_report_shows_partial_and_link_only_outcomes(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.invoke("add", URL)
    world.invoke("run")

    assert world.invoke("report").exit_code == 0
    with (tmp_path / "reports" / "report.csv").open(encoding="utf-8-sig", newline="") as handle:
        [row] = list(csv.DictReader(handle))
    assert row["recipe_kind"] == "link-only" and row["outcome"] == "link_only"


def test_a_stub_is_not_redone_on_the_next_run(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.invoke("add", URL)
    world.invoke("run")
    world.caption(INGREDIENTS_ONLY)  # the caption changed, but nothing upgrades a stub by itself

    world.invoke("run")

    assert recipe(world)["recipeIngredient"] == []
    assert not [c for c in world.llm.calls if c.task == "extract"]


def test_the_pinned_comment_is_a_source_for_an_ingredients_only_recipe(tmp_path):
    world = StubWorld(tmp_path)
    world.caption(HASHTAGS_ONLY)
    world.videos.pinned[CANONICAL] = INGREDIENTS_ONLY
    extraction = ingredients_only_extraction()
    for ingredient in extraction["ingredients"]:
        ingredient["evidence"][0]["source"] = "cmt"
    world.llm.script("extract", extraction)
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert "[SRC:cmt]" in next(c.prompt for c in world.llm.calls if c.task == "extract")
    assert len(recipe(world)["recipeIngredient"]) == 5  # grounded in the comment, so nothing dropped
