"""The real ingredient-parser engine, on a few hand-written lines (skipped when the model is unavailable)."""

import pytest

from mealie_pipeline.adapters.ingredient_engine import NlpIngredientEngine, read_quantity


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


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (2, (2.0, 2.0)),
        ("2", (2.0, 2.0)),
        ("half", (0.5, 0.5)),
        ("1.5-2", (1.5, 2.0)),
        ("1,5-2", (1.5, 2.0)),
        ("2–3", (2.0, 3.0)),
        ("few", (None, None)),
        ("", (None, None)),
        ("3-#1$2-4", (None, None)),
        (None, (None, None)),
    ],
)
def test_read_quantity_never_raises_on_text_amounts(value, expected):
    assert read_quantity(value) == expected


@pytest.mark.parametrize(
    ("line", "quantity", "note_has"),
    [
        ("a few sprigs of mint", None, "few"),
        ("half an onion", 0.5, ""),
        ("1.5-2 cups flour", 1.5, ""),
    ],
)
def test_lines_the_parser_returns_text_amounts_for_do_not_crash(engine, line, quantity, note_has):
    parsed = engine.parse(line)

    assert parsed.quantity == quantity
    assert note_has in parsed.note


def test_a_line_without_an_amount_has_no_quantity(engine):
    parsed = engine.parse("salt, to taste")

    assert parsed.quantity is None and parsed.food == "salt"
