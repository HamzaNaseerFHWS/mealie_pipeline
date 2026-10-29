"""Protein Tags at the pure-module seam: hand-written recipes against `config/protein_tags.yaml`."""

from pathlib import Path

import pytest

from mealie_pipeline.protein import ProteinRules, RecipeText, detect, mealie_recipe_text, tag_key

RULES = ProteinRules.load(Path(__file__).parents[1] / "config" / "protein_tags.yaml")


def parsed(food: str, note: str = "") -> dict:
    """A pipeline ingredient: linked to a Food, with no original text kept."""
    return {"quantity": 1, "food": {"id": "f1", "name": food}, "note": note}


def unparsed(text: str) -> dict:
    """An older import: the whole line sits in `note` (and often `display`), no Food linked."""
    return {"quantity": 0, "food": None, "unit": None, "note": text, "display": text}


def recipe(name: str, *ingredients: dict, tags: tuple[str, ...] = ()) -> dict:
    return {
        "slug": "x",
        "name": name,
        "tags": [{"id": t, "name": t, "slug": t.lower()} for t in tags],
        "recipeIngredient": list(ingredients),
    }


CASES = [
    (
        "a parsed chicken thigh",
        recipe("Weeknight Thighs", parsed("chicken thighs"), parsed("garlic")),
        ["Chicken"],
    ),
    (
        "a note-only murgh",
        recipe("Karahi", unparsed("500g boneless murgh"), unparsed("2 tomatoes")),
        ["Chicken"],
    ),
    (
        "cheese in the name",
        recipe("Grilled Cheese Sandwich", parsed("bread"), parsed("butter")),
        ["Cheese"],
    ),
    ("chana in the name", recipe("Chana Masala", parsed("onion"), parsed("tomato")), ["Chickpeas"]),
    ("dal in the name", recipe("Dal Tadka", parsed("ghee"), parsed("cumin seeds")), ["Lentils"]),
    ("rajma in the name", recipe("Rajma Chawal", parsed("rice"), parsed("onion")), ["Beans"]),
    (
        "eggs in a cake",
        recipe("Chocolate Cake", parsed("eggs"), parsed("butter"), parsed("flour"), parsed("cocoa powder")),
        [],
    ),
    (
        "chicken stock in a vegetable soup",
        recipe("Vegetable Soup", parsed("carrot"), unparsed("1 l chicken stock"), parsed("celery")),
        [],
    ),
    (
        "chicken and chickpeas",
        recipe("Curry", parsed("chicken breast"), unparsed("1 can chickpeas, drained"), parsed("onion")),
        ["Chicken", "Chickpeas"],
    ),
    ("paneer is not cheese", recipe("Paneer Tikka", parsed("paneer"), parsed("yogurt")), ["Paneer"]),
    (
        "German lentil soup with sausages",
        recipe("Linsensuppe mit Würstchen", unparsed("250 g Tellerlinsen"), unparsed("4 Wiener Würstchen")),
        ["Pork", "Lentils"],
    ),
    ("a drink", recipe("Mango Lassi", parsed("mango"), parsed("yogurt"), parsed("milk")), []),
]


@pytest.mark.parametrize(("label", "mealie_recipe", "expected"), CASES, ids=[c[0] for c in CASES])
def test_main_proteins_of_hand_written_recipes(label, mealie_recipe, expected):
    assert list(detect(mealie_recipe_text(mealie_recipe), RULES)) == expected


def test_each_tag_names_the_words_that_triggered_it():
    found = detect(
        RecipeText("Murgh Chana", ["1 kg chicken legs", "1 can chickpeas"]),
        RULES,
    )
    assert found == {"Chicken": ["murgh", "chicken"], "Chickpeas": ["chana", "chickpeas"]}


@pytest.mark.parametrize(
    "line",
    ["fried egg, to serve", "2 eggs (optional)", "boiled eggs for garnish", "Eier zum Garnieren"],
)
def test_optional_garnish_and_to_serve_lines_do_not_count(line):
    assert detect(RecipeText("Fried Rice", ["2 cups rice", line]), RULES) == {}


def test_a_protein_in_the_name_counts_even_when_its_line_is_optional():
    assert list(detect(RecipeText("Egg Fried Rice", ["2 eggs (optional)"]), RULES)) == ["Egg"]


def test_an_existing_dessert_tag_drops_egg_and_cheese_but_not_meat():
    text = RecipeText("Grandma's Special", ["3 eggs", "200 g cheese", "100 g bacon"], tags=["Dessert"])
    assert list(detect(text, RULES)) == ["Pork"]


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("2 tbsp fish sauce", []),
        ("200 g green beans", []),
        ("1 cup chana dal", ["Lentils"]),  # the longer phrase wins over "chana" alone
        ("100 g goat cheese", ["Cheese"]),  # not Lamb & Mutton
        ("Hähnchenbrustfilet", ["Chicken"]),  # German compounds match by their stem
        ("Hühnerbrühe", []),
        ("2 sweet potatoes", []),
        ("eggplant", []),  # whole words only
    ],
)
def test_specific_phrases_beat_generic_words(line, expected):
    assert list(detect(RecipeText("Dish", [line]), RULES)) == expected


def test_old_imports_are_read_from_note_original_text_and_display():
    old = recipe(
        "Something",
        {"note": "", "originalText": "1 lb ground beef", "display": ""},
        {"note": "", "display": "6 large shrimp"},
    )
    assert list(detect(mealie_recipe_text(old), RULES)) == ["Beef", "Seafood"]


@pytest.mark.parametrize(
    ("a", "b"), [("Lamb & Mutton", "lamb mutton"), ("Soy chunks", "soy-chunks"), ("Chicken", " chicken ")]
)
def test_tag_names_match_ignoring_case_spaces_and_punctuation(a, b):
    assert tag_key(a) == tag_key(b)


def test_every_protein_tag_in_the_config_has_words():
    assert list(RULES.tags)[:3] == ["Chicken", "Beef", "Lamb & Mutton"]
    assert all(RULES.tags.values())
