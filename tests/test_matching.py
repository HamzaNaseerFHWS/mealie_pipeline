"""Table tests for the Unit Normalizer and Food Matcher (pure)."""

from pathlib import Path

import pytest
import yaml

from mealie_pipeline.adapters.mealie import Food, Unit
from mealie_pipeline.matching import FoodMatcher, UnitNormalizer

SYNONYMS = yaml.safe_load((Path(__file__).parents[1] / "config" / "units.yaml").read_text(encoding="utf-8"))

UNITS = [
    Unit(id="u-g", name="gram", abbreviation="g", plural_name="grams"),
    Unit(id="u-tbsp", name="tablespoon", abbreviation="tbsp"),
    Unit(id="u-cup", name="cup"),
]
FOODS = [
    Food(id="f-salt", name="Salt"),
    Food(id="f-onion", name="onion", plural_name="onions"),
    Food(id="f-tomato", name="tomato"),
    Food(id="f-cumin-seeds", name="cumin seeds"),
    Food(id="f-cumin-powder", name="cumin powder"),
    Food(id="f-turmeric", name="turmeric", aliases=["haldi"]),
    Food(id="f-chilli", name="green chilli"),
]


@pytest.mark.parametrize(
    ("text", "kind", "unit_id", "new_name"),
    [
        ("gram", "exact", "u-g", ""),
        ("Grams", "alias", "u-g", ""),  # synonym table: grams -> gram
        ("g", "alias", "u-g", ""),
        ("tbsps", "alias", "u-tbsp", ""),
        ("TBSP.", "alias", "u-tbsp", ""),
        ("cups", "alias", "u-cup", ""),
        ("", "none", None, ""),
        ("teaspoon", "new", None, "teaspoon"),  # a known synonym whose unit is missing: create canonical
        ("tsps", "new", None, "teaspoon"),
        ("handfuls", "new", None, "handful"),
        ("bucketful", "new", None, "bucketful"),
    ],
)
def test_unit_normalizer(text, kind, unit_id, new_name):
    match = UnitNormalizer(SYNONYMS).match(text, UNITS)

    assert match.kind == kind
    assert (match.unit.id if match.unit else None) == unit_id
    assert match.new_name == new_name


@pytest.mark.parametrize(
    ("name", "kind", "food_id", "new_name"),
    [
        ("salt", "exact", "f-salt", ""),  # case-insensitive, keeps the catalog's "Salt"
        ("Onions", "plural", "f-onion", ""),
        ("haldi", "alias", "f-turmeric", ""),
        ("tomatoes", "singular", "f-tomato", ""),
        ("green chillies", "fuzzy", "f-chilli", ""),
        ("green chilli", "exact", "f-chilli", ""),
        ("cumin seeds", "exact", "f-cumin-seeds", ""),
        ("cumin seed", "singular", "f-cumin-seeds", ""),
        ("dry mango powder", "new", None, "dry mango powder"),
        ("kasuri methi", "new", None, "kasuri methi"),
        ("Ginger Garlic Paste", "new", None, "ginger garlic paste"),
    ],
)
def test_food_matcher(name, kind, food_id, new_name):
    match = FoodMatcher().match(name, FOODS)

    assert match.kind == kind
    assert (match.food.id if match.food else None) == food_id
    assert match.new_name == new_name


@pytest.mark.parametrize(
    ("name", "original", "kind", "food_id", "new_alias", "new_name"),
    [
        ("onions", "Zwiebel", "plural", "f-onion", "zwiebel", ""),  # the English match learns the word
        ("turmeric", "Kurkuma", "exact", "f-turmeric", "kurkuma", ""),
        ("shell pasta", "Muschelnudeln", "new", None, "muschelnudeln", "shell pasta"),  # so does a new Food
    ],
)
def test_original_name_is_offered_as_an_alias_for_the_english_match(
    name, original, kind, food_id, new_alias, new_name
):
    match = FoodMatcher().match(name, FOODS, original)

    assert match.kind == kind
    assert (match.food.id if match.food else None) == food_id
    assert match.new_alias == new_alias
    assert match.new_name == new_name


def test_a_food_that_already_knows_the_original_name_wins_over_the_english_translation():
    foods = [*FOODS, Food(id="f-shell", name="shell pasta", aliases=["Muschelnudeln"])]

    match = FoodMatcher().match("pasta", foods, "muschelnudeln")

    assert match.food is not None
    assert (match.kind, match.food.id, match.new_alias) == ("alias", "f-shell", "")


@pytest.mark.parametrize(
    "original",
    [
        "",
        "onion",
        "Onion",
        "a b c d e f",
        "Schnittlauch oder Petersilie",
        "Tomate(n)",
        "Pita/Fladenbrot",
        "2 Zwiebeln",
    ],
)
def test_no_alias_for_an_empty_equal_or_sentence_like_original(original):
    assert FoodMatcher().match("onion", FOODS, original).new_alias == ""


def test_a_fuzzy_english_match_is_never_taught_an_alias():
    match = FoodMatcher().match("green chillies", FOODS, "Grüne Chilis")

    assert (match.kind, match.new_alias) == ("fuzzy", "")


def test_fuzzy_match_reuses_a_near_identical_name():
    match = FoodMatcher().match("tomatto", FOODS)  # a typo scoring above the fuzzy threshold

    assert (match.kind, match.food.id if match.food else None) == ("fuzzy", "f-tomato")


@pytest.mark.parametrize("name", ["cumin powder", "turmeric powder", "coriander seeds", "mustard oil"])
def test_fuzzy_never_merges_foods_that_differ_by_a_distinguishing_word(name):
    foods = [*FOODS, Food(id="f-turmeric-root", name="turmeric root"), Food(id="f-mustard", name="mustard")]
    match = FoodMatcher().match(name, foods)

    assert match.kind in ("exact", "new")
    if match.kind == "new":
        assert match.food is None


def test_glossary_maps_a_desi_name_before_matching():
    match = FoodMatcher({"haldi powder": "turmeric"}).match("haldi powder", FOODS)

    assert (match.kind, match.food.id if match.food else None) == ("exact", "f-turmeric")
