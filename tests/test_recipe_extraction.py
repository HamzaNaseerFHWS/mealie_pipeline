"""Structured Recipe Extraction on saved HTML fixtures (pure)."""

from pathlib import Path

import pytest
import yaml

from mealie_pipeline import recipe_extraction
from mealie_pipeline.recipe_extraction import extract_recipes, format_for_prompt, parse_duration

ROOT = Path(__file__).parents[1]
SELECTORS = yaml.safe_load((ROOT / "config" / "site_selectors.yaml").read_text(encoding="utf-8"))


def page(name: str) -> str:
    return (Path(__file__).parent / "fixtures" / "web" / name).read_text(encoding="utf-8")


def extract(name: str):
    return extract_recipes(page(name), f"https://site.example/{name}", SELECTORS)


def test_wordpress_wprm_page_with_a_yoast_graph_is_read_from_json_ld():
    (recipe,) = extract("wprm_graph.html")

    assert recipe.extraction_method == "json-ld"
    assert recipe.name == "Chatpata Bhindi Aloo"
    assert [i.text for i in recipe.ingredients] == [
        "250 g okra (bhindi)",
        "1 potato",
        "2 small onions",
        "2 tbsp mustard oil",
        "1/2 tsp cumin seeds",
        "Salt, to taste",
    ]
    assert [(s.text, s.section) for s in recipe.steps] == [
        ("Wash the okra, dry it well and cut into thick dice.", None),
        ("Heat the oil, add the cumin seeds and the onions and cook until translucent.", None),
        ("Add okra and potato, cover and cook until tender. Season with salt.", "Finish"),  # HowToSection
    ]
    assert (recipe.prep_minutes, recipe.cook_minutes, recipe.total_minutes) == (10, 20, 30)
    assert recipe.yield_text == "3"
    assert recipe.image == "https://foodlab.example/wp-content/uploads/bhindi-aloo.jpg"


def test_a_tasty_recipes_page_without_structured_data_is_read_from_the_card():
    (recipe,) = extract("tasty_card.html")

    assert recipe.extraction_method == "card:tasty"
    assert recipe.name == "Easy Lentil Soup"
    assert recipe.yield_text == "Serves 4"
    assert [i.text for i in recipe.ingredients] == [
        "1 cup red lentils",
        "1 onion, chopped",
        "4 cups vegetable stock",
        "1 tsp cumin",
    ]
    assert [s.text for s in recipe.steps][-1] == "Blend until smooth."
    assert len(recipe.steps) == 3


def test_wprm_card_keeps_ingredient_and_step_sections_and_the_lazy_image():
    (recipe,) = extract("wprm_card_sections.html")

    assert recipe.extraction_method == "card:wprm"
    assert [(i.section, i.text) for i in recipe.ingredients] == [
        ("For the dough", "300 g flour"),
        ("For the dough", "150 ml hot water"),
        ("For the filling", "250 g minced pork"),
        ("For the filling", "1 tbsp soy sauce"),
    ]
    assert [s.section for s in recipe.steps] == ["Dough", "Fill and cook", "Fill and cook"]
    assert recipe.image == "https://dumplings.example/pork.jpg"


def test_a_microdata_page_is_read_without_json_ld():
    (recipe,) = extract("microdata.html")

    assert recipe.extraction_method == "microdata"
    assert recipe.name == "Kartoffelsuppe"
    assert [i.text for i in recipe.ingredients] == ["800 g Kartoffeln", "1 Zwiebel", "1 l Gemüsebrühe"]
    # extruct folds the line breaks of a plain-text method into spaces, so it arrives as one step.
    assert [s.text for s in recipe.steps] == [
        "Kartoffeln und Zwiebel würfeln. Mit der Brühe 25 Minuten kochen. Pürieren und abschmecken."
    ]
    assert (recipe.prep_minutes, recipe.total_minutes) == (15, 45)
    assert recipe.yield_text == "4 Portionen"


def test_a_page_with_no_recipe_falls_back_to_the_main_text():
    (recipe,) = extract("no_recipe.html")

    assert recipe.extraction_method == "main-text"
    assert not recipe.structured
    assert "planning on Sundays" in recipe.text


def test_a_page_with_two_recipe_objects_returns_both():
    recipes = extract("two_recipes.html")

    assert [r.name for r in recipes] == ["Tomato Sauce", "Pesto"]
    assert {r.extraction_method for r in recipes} == {"json-ld"}
    assert [s.text for s in recipes[1].steps] == ["Blend everything until smooth."]  # a plain-string method


def test_recipe_scrapers_is_the_fourth_choice(monkeypatch):
    """Used only when JSON-LD, microdata and the card selectors found nothing."""
    html = "<html><body><p>nothing structured</p></body></html>"
    seen = []

    def fake(html_text, url):
        seen.append(url)
        return [
            recipe_extraction.SourceRecipe(
                name="Scraped",
                ingredients=[recipe_extraction.SourceIngredient(text="1 egg")],
                steps=[recipe_extraction.SourceStep(text="Boil it.")],
                extraction_method="recipe-scrapers",
            )
        ]

    monkeypatch.setattr(recipe_extraction, "_from_recipe_scrapers", fake)

    (recipe,) = extract_recipes(html, "https://x.example/p", SELECTORS)
    assert (recipe.name, recipe.extraction_method, seen) == (
        "Scraped",
        "recipe-scrapers",
        ["https://x.example/p"],
    )
    # ... and it is not consulted when an earlier method already succeeded.
    seen.clear()
    extract("wprm_graph.html")
    assert seen == []


def test_garbage_html_never_raises():
    assert extract_recipes("", "https://x.example", SELECTORS) == []
    assert extract_recipes("<<<not html", "https://x.example", SELECTORS) in (
        [],
        extract_recipes("<<<not html", "https://x.example", SELECTORS),
    )


@pytest.mark.parametrize(
    ("value", "minutes"),
    [
        ("PT10M", 10),
        ("PT1H30M", 90),
        ("PT2H", 120),
        ("P1DT1H", 1500),
        ("pt45m", 45),
        ("10 minutes", None),
        ("", None),
        (None, None),
        ("PT", None),
    ],
)
def test_parse_duration(value, minutes):
    assert parse_duration(value) == minutes


def test_format_for_prompt_lists_sections_ingredients_and_numbered_steps():
    (recipe,) = extract("wprm_card_sections.html")

    text = format_for_prompt(recipe)

    assert text.splitlines()[0] == "Pork Dumplings"
    assert "For the dough:\n300 g flour\n150 ml hot water\nFor the filling:\n250 g minced pork" in text
    assert "Fill and cook:\n2. Fill the wrappers with the pork mixture.\n3. Steam for 12 minutes." in text
    assert "Yield: 24" in text
