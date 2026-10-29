"""Table tests for the Sanity Checks (pure): lines whose amount, unit or food cannot be right."""

import pytest

from mealie_pipeline.sanity import check_line
from mealie_pipeline.settings import ParseSettings

UNIT_WORDS = {"cup", "cups", "tablespoon", "tbsp", "teaspoon", "tsp", "clove", "cloves", "g", "gram"}


@pytest.mark.parametrize(
    ("quantity", "unit", "food", "finding"),
    [
        # Implausible quantity for the unit, or for a seasoning in that unit
        (5, "kilogram", "salt", "5 kilogram of salt is implausibly much"),
        (500, "gram", "salt", "500 gram of salt is implausibly much"),
        (25, "tablespoon", "olive oil", "25 tablespoon is more than 20"),
        (8000, "gram", "flour", "8000 gram is more than 5000"),
        # A unit used as the food
        (1, "", "cup", '"cup" is a unit, not a food'),
        (2, "", "Tbsp", '"Tbsp" is a unit, not a food'),
        (2, "", "cloves", '"cloves" is a unit, not a food'),
        # A count unit with a liquid
        (2, "piece", "water", "a liquid (water) counted in piece"),
        (3, "", "coconut milk", "a liquid (coconut milk) counted without a unit"),
        (1, "slice", "lemon juice", "a liquid (lemon juice) counted in slice"),
    ],
)
def test_a_suspicious_line_is_flagged(quantity, unit, food, finding):
    assert finding in check_line(quantity, unit, food, ParseSettings(), UNIT_WORDS)


@pytest.mark.parametrize(
    ("quantity", "unit", "food"),
    [
        (1, "teaspoon", "salt"),
        (20, "gram", "salt"),
        (2, "tablespoon", "olive oil"),
        (500, "gram", "flour"),
        (5, "kilogram", "potatoes"),
        (1, "teaspoon", "cloves"),  # cloves the spice, measured in a real unit
        (2, "cup", "water"),
        (2, "", "eggs"),
        (0, "", "oil"),  # "oil, as required": no amount, nothing counted
        (2, "", "milk powder"),  # not a liquid: the last word is the food
        (None, "", "salt"),
    ],
)
def test_a_plausible_line_is_not_flagged(quantity, unit, food):
    assert check_line(quantity, unit, food, ParseSettings(), UNIT_WORDS) == []


def test_limits_come_from_settings():
    cfg = ParseSettings(max_quantity={"tablespoon": 4})

    assert check_line(5, "tablespoon", "butter", cfg, UNIT_WORDS) == ["5 tablespoon is more than 4"]
