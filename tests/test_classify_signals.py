"""Classifier rule signals (pure): which hints `config/classify_rules.yaml` finds in a Video's text."""

from pathlib import Path

import pytest

from mealie_pipeline.classify import ClassifyRules, signals
from mealie_pipeline.models import VideoMeta

RULES = ClassifyRules.load(Path(__file__).parents[1] / "config" / "classify_rules.yaml")


@pytest.mark.parametrize(
    ("title", "description", "pro"),
    [
        ("Crispy Garlic Chicken Recipe", "", {"recipe_word"}),
        ("How to make naan", "", {"recipe_word"}),
        ("Pancakes", "Ingredients:\n200 g flour\n2 eggs", {"ingredients_word", "quantity_unit"}),
        ("Shakshuka", "1/2 tsp cumin, 400 ml tomatoes", {"quantity_unit"}),
        ("Pasta", "Full recipe on my blog!", {"recipe_word", "recipe_link"}),
        ("Lemon cake", "Link in bio for the details", {"recipe_link"}),
        ("Dinner idea", "#easyrecipes #dinner", {"recipe_hashtag"}),
        (
            "Käsespätzle Rezept",
            "Zutaten: 2 EL Öl, 1 Prise Salz",
            {"recipe_word", "ingredients_word", "quantity_unit"},
        ),
        ("Chicken biryani ki tarkeeb", "", {"recipe_word"}),
        ("Nihari", "Ajza: gosht, masala", {"ingredients_word"}),
        ("Chana masala", "samagri: chana, pyaz", {"ingredients_word"}),
        ("Quick dal", "Fry the onions, then simmer for ten minutes", {"cooking_verb"}),
        ("Brownies", "Preheat the oven and whisk the eggs", {"cooking_verb"}),
        ("Kartoffelsuppe", "Zwiebeln anbraten und köcheln lassen", {"cooking_verb"}),
    ],
)
def test_pro_recipe_signals(title: str, description: str, pro: set[str]):
    found = signals(VideoMeta(title=title, description=description), RULES)
    assert set(found.pro) == pro
    assert found.anti == {}


@pytest.mark.parametrize(
    ("title", "description", "anti"),
    [
        ("Best ramen in Tokyo 📍", "", {"location_pin"}),
        ("Hidden gem", "Located in Shoreditch, go now", {"location_pin"}),
        ("This café", "Open daily, 8am - 6pm", {"address_or_hours"}),
        ("Brunch spot", "Find it at 221 Baker Street", {"address_or_hours"}),
        ("Frühstück", "Hauptstraße 12, Öffnungszeiten Mo-Fr", {"address_or_hours"}),
        ("Tasting menu", "", {"menu_or_reservation"}),
        ("Date night", "Reservation needed on weekends", {"menu_or_reservation"}),
        ("Pizza night", "#londoneats #pizza", {"city_eats_hashtag"}),
        ("Burger", "#foodieberlin", {"city_eats_hashtag"}),
        ("Cheap eats", "Only $12 for the whole plate", {"price"}),
        ("Döner", "Kostet 8,50 € pro Stück", {"price"}),
        ("Street food", "Rs. 300 per plate", {"price"}),
        ("New air fryer", "#ad", {"ad_or_sponsored"}),
        ("Knife set", "Sponsored by Blades Inc", {"ad_or_sponsored"}),
        ("Spice box", "Paid partnership with SpiceCo", {"ad_or_sponsored"}),
        ("Pan", "Use code SAVE10 for 10% off", {"ad_or_sponsored"}),
    ],
)
def test_anti_recipe_signals(title: str, description: str, anti: set[str]):
    found = signals(VideoMeta(title=title, description=description), RULES)
    assert set(found.anti) == anti
    assert found.pro == {}


@pytest.mark.parametrize(
    ("title", "description"),
    [
        ("My cat asleep on the sofa", "so cute"),
        ("Holiday vlog", "#travel #summer"),
        ("Sweet treats", "#treats #dessertlover"),  # "#treats" is no "#<city>eats" tag
        ("Unboxing", "What a day"),
    ],
)
def test_neutral_text_has_no_signals(title: str, description: str):
    found = signals(VideoMeta(title=title, description=description), RULES)
    assert (found.pro, found.anti) == ({}, {})


def test_a_signal_keeps_the_text_it_matched():
    found = signals(VideoMeta(title="Ramen 📍 Tokyo", description="Ingredients: 300 g noodles"), RULES)
    assert found.pro["quantity_unit"] == "300 g"
    assert found.anti["location_pin"] == "📍"


def test_rules_are_read_from_yaml(tmp_path: Path):
    path = tmp_path / "classify_rules.yaml"
    path.write_text("pro:\n  tarka: ['\\btarka\\b']\nanti:\n  stall: ['\\bstall\\b']\n", encoding="utf-8")
    found = signals(VideoMeta(title="Tarka from the stall"), ClassifyRules.load(path))
    assert (set(found.pro), set(found.anti)) == ({"tarka"}, {"stall"})
