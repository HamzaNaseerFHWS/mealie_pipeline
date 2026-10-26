"""The real ingredient-parser engine, on a few hand-written lines (skipped when the model is unavailable)."""

import pytest

from mealie_pipeline.adapters.ingredient_engine import NlpIngredientEngine


@pytest.fixture(scope="module")
def engine():
    engine = NlpIngredientEngine()
    try:
        engine.parse("1 cup rice")
    except (LookupError, OSError) as err:  # NLTK tagger could not be downloaded (offline)
        pytest.skip(f"ingredient-parser model data unavailable: {err}")
    return engine


@pytest.mark.parametrize(
    ("line", "quantity", "unit", "food"),
    [
        ("250 g okra", 250, "g", "okra"),
        ("1/2 tsp cumin seeds", 0.5, "tsp", "cumin seeds"),
        ("2 cups all-purpose flour", 2, "cup", "all-purpose flour"),
    ],
)
def test_parses_quantity_unit_and_food(engine, line, quantity, unit, food):
    parsed = engine.parse(line)

    assert parsed.quantity == quantity
    assert parsed.unit.rstrip("s") == unit
    assert parsed.food == food


def test_a_line_without_an_amount_has_no_quantity(engine):
    parsed = engine.parse("salt, to taste")

    assert parsed.quantity is None and parsed.food == "salt"
