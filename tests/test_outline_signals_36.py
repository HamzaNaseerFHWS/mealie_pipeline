"""Ticket 36: more heading styles, and the title as a sign of several recipes."""

import pytest

from mealie_pipeline.models import VideoMeta
from mealie_pipeline.outline import caption_blocks, detect_signals, only_title, title_signal


def block(heading: str, n: int) -> str:
    return f"{heading}\n{n} cup rice\n2 eggs\n"


@pytest.mark.parametrize(
    "style",
    [
        "Night {n}",
        "NIGHT {n}",
        "Day {n}: Tacos",
        "Option {n} - Pasta",
        "Part {n}",
        "Recipe #{n}",
        "Recipe {n}: Soup",
        "Meal {n}",
        "Number {n}",
        "Rezept {n}",
        "Tag {n}: Suppe",
        "{n}. Mint Chutney",
        "#{n} Curry",
    ],
)
def test_numbered_headings_of_every_style_make_blocks(style):
    caption = "Two dinners!\n\n" + block(style.format(n=1), 1) + "\n" + block(style.format(n=2), 2)
    assert [n for n, _text in caption_blocks(caption).blocks] == [1, 2]


@pytest.mark.parametrize(
    ("title", "signal"),
    [
        ("Budget Meal Prep: 5 Healthy Dinners, Beans, Chicken Soup, Tostadas, Fried Rice", "meal_prep"),
        ("Freezer Meals: Breakfast Burritos, Enchiladas and Lasagna", "freezer_meals"),
        ("Japanese vs Korean Rice Bowl", "versus"),
        ("3 ways to cook eggs", "n_ways"),
        ("5 easy dinners for the week", "n_ways"),
        ("10 Recipes You Need This Summer", "recipes_you_need"),
        ("Pasta recipes you need to try", "recipes_you_need"),
        ("Middle Eastern Feast: Hummus, Falafel and Tabbouleh", "dish_list"),
        ("Hummus, Falafel, Tabbouleh | Chef Ali", "dish_list"),
    ],
)
def test_titles_that_promise_several_recipes(title, signal):
    assert title_signal(title) == signal


@pytest.mark.parametrize(
    "title",
    [
        "Pasta with Romanesco Broccoli and Spinach",
        "Chicken and Rice",
        "Chatpata Bhindi Aloo | Crispy Okra Stir Fry",
        "The best lasagna, ever",
        "Salmon with lemon, garlic butter sauce and crispy roasted baby potatoes",
        "Dal Makhani",
        "One-pot vegan chili",
    ],
)
def test_titles_of_one_dish_do_not_fire(title):
    assert title_signal(title) is None


def test_the_title_signal_joins_the_others_and_can_be_the_only_one():
    meta = VideoMeta(title="Freezer Meals: Burritos, Chili and Lasagna", description="Enjoy!")
    signals = detect_signals(meta, [])
    assert signals == ["title:freezer_meals"]
    assert only_title(signals)
    assert not only_title(["chapters:3", "title:versus"])
    assert not only_title([])


# -- pipeline seam --------------------------------------------------------------------------

from tests.helpers import recipe_llm  # noqa: E402
from tests.test_outline_seam import ChutneyWorld, extraction  # noqa: E402
from tests.test_pipeline_seam import (  # noqa: E402
    CANONICAL,
    TOKEN,
    VIDEO_KEY,
    FlakyImageMealie,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)
from tests.test_scrape_seam import PAGE_URL, WebWorld, web_recipe  # noqa: E402

NIGHTS = """Two dinners for the week!

NIGHT 1
Mint Chutney
1 cup mint
2 green chillies
Blend the mint until smooth.

NIGHT 2
Tamarind Chutney
100 g tamarind
50 g jaggery
Soak the tamarind and strain.
"""


def nights_world(tmp_path) -> ChutneyWorld:
    world = ChutneyWorld(tmp_path)
    world.mealie = FlakyImageMealie(token=TOKEN, tags=["Dinner"], foods=[], units=["gram", "cup"])
    info = load("youtube_info_okra.json")
    info["description"] = NIGHTS
    world.videos.infos[CANONICAL] = info
    world.llm = recipe_llm()
    world.llm.script(
        "outline", {"language": "en", "parts": [{"title": "Mint Chutney"}, {"title": "Tamarind Chutney"}]}
    )
    world.llm.script("extract", extraction("Mint"), when_prompt_has="recipe 1 of 2")
    world.llm.script("extract", extraction("Tamarind"), when_prompt_has="recipe 2 of 2")
    return world


def test_a_night_1_night_2_caption_becomes_two_recipes(tmp_path):
    world = nights_world(tmp_path)
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert sorted(r["name"] for r in world.mealie.recipes.values()) == ["Mint Chutney", "Tamarind Chutney"]
    outline_call = next(c for c in world.llm.calls if c.task == "outline")
    assert "caption_blocks:2" in outline_call.prompt


def test_a_freezer_meals_title_with_one_recipe_page_and_nothing_to_split_goes_to_review(tmp_path):
    world = WebWorld(tmp_path)
    world.info["title"] = "Freezer Meals: Breakfast Burritos, Chili and Lasagna"
    world.llm.script("outline", {"language": "en", "parts": [{"title": "Bhindi Aloo"}]})
    world.llm.script("extract", web_recipe())
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")

    result = world.invoke("run")

    assert not world.mealie.recipes  # never uploaded as one merged recipe
    assert world.store().stage_status("video", VIDEO_KEY, "outline") == "review"
    assert "looks like several recipes, nothing to split on" in result.output
    assert not [c for c in world.llm.calls if c.task == "extract"]
    assert PAGE_URL in world.web.fetched


def test_a_title_signal_with_no_text_at_all_becomes_one_link_only_stub(tmp_path):
    world = WebWorld(tmp_path)
    world.info["title"] = "Japanese vs Korean Rice Bowl"
    world.describe("#ricebowl #japanese #korean 😍")

    result = world.invoke("add", "https://youtu.be/de1ppj9L4Hk")
    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert not [c for c in world.llm.calls if c.task in ("outline", "extract")]
    [stub] = world.mealie.recipes.values()
    assert stub["name"] == "Japanese vs Korean Rice Bowl"
    assert "link-only" in [t["name"] for t in stub["tags"]]
