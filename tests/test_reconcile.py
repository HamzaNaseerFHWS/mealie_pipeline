"""Table tests for Reconcile (pure): two ingredient parses of one line become one, with a parse status."""

from pathlib import Path

import pytest
import yaml

from mealie_pipeline.adapters.ingredient_engine import EngineParse
from mealie_pipeline.matching import UnitNormalizer
from mealie_pipeline.models import LlmParse
from mealie_pipeline.reconcile import reconcile

SYNONYMS = yaml.safe_load((Path(__file__).parents[1] / "config" / "units.yaml").read_text(encoding="utf-8"))
UNIT_KEY = UnitNormalizer(SYNONYMS).canonical


def nlp(amount, unit_text, food_text, note="", confidence=0.99, **confidences):
    """`confidences` by field, e.g. `quantity=0.6`; fields not named get `confidence`."""
    return EngineParse(amount, amount, unit_text, food_text, note, confidence, confidences)


def nlp_range(low, high, unit, food, note="", confidence=0.99):
    return EngineParse(low, high, unit, food, note, confidence)


def llm(quantity=None, unit=None, food=None, note=None, quantity_max=None):
    return LlmParse(quantity=quantity, quantity_max=quantity_max, unit=unit, food=food, note=note)


@pytest.mark.parametrize(
    ("line", "a", "b", "status", "expected"),
    [
        # Both engines read the same thing; spellings of one unit and food are the same.
        (
            "2 tbsp mustard oil",
            nlp(2, "tbsps", "mustard oil"),
            llm(2, "tablespoon", "mustard oil"),
            "agreed",
            (2, 2, "tbsps", "mustard oil", ""),
        ),
        (
            "1–2 tbsp ghee",
            nlp_range(1, 2, "tbsp", "ghee"),
            llm(1, "tbsp", "ghee", quantity_max=2),
            "agreed",
            (1, 2, "tbsp", "ghee", ""),
        ),
        (
            "½ cup yogurt",
            nlp(0.5, "cup", "yogurt"),
            llm(0.5, "cups", "yoghurt"),
            "agreed",
            (0.5, 0.5, "cup", "yogurt", ""),
        ),
        (
            "1 1/2 tsp cumin seeds",
            nlp(1.5, "tsp", "cumin seeds"),
            llm(1.5, "teaspoon", "cumin seed"),
            "agreed",
            (1.5, 1.5, "tsp", "cumin seeds", ""),
        ),
        (
            "1/3 cup sugar",
            nlp(1 / 3, "cup", "sugar"),
            llm(0.33, "cup", "sugar"),
            "agreed",
            (1 / 3, 1 / 3, "cup", "sugar", ""),
        ),
        (
            "salt, to taste",
            nlp(None, "", "salt", "to taste"),
            llm(food="salt", note="to taste"),
            "agreed",
            (None, None, "", "salt", "to taste"),
        ),
        # The size word stays out of the food and goes into the note (the LLM's note fills a gap).
        (
            "1 large onion",
            nlp(1, "", "onion", "large"),
            llm(1, None, "onion", "large"),
            "agreed",
            (1, 1, "", "onion", "large"),
        ),
        (
            "1 large onion, sliced",
            nlp(1, "", "onion"),
            llm(1, None, "onion", "large, sliced"),
            "agreed",
            (1, 1, "", "onion", "large, sliced"),
        ),
        # One field differs and NLP is sure of it: NLP wins.
        (
            "2 tbsp oil",
            nlp(2, "tbsp", "oil", quantity=0.95),
            llm(1, "tbsp", "oil"),
            "nlp_preferred",
            (2, 2, "tbsp", "oil", ""),
        ),
        (
            "3 cloves garlic",
            nlp(3, "cloves", "garlic", unit=0.97),
            llm(3, None, "garlic"),
            "nlp_preferred",
            (3, 3, "cloves", "garlic", ""),
        ),
        # One field differs but NLP is unsure of that field: the LLM's reading, flagged.
        (
            "2 tbsp oil",
            nlp(2, "tbsp", "oil", quantity=0.6),
            llm(1, "tbsp", "oil", "to fry"),
            "conflict",
            (1, 1, "tbsp", "oil", "to fry"),
        ),
        # Two fields differ: never NLP, whatever its confidence.
        (
            "1 cup chopped tomatoes",
            nlp(1, "cup", "chopped tomatoes"),
            llm(2, None, "tomato", "chopped"),
            "conflict",
            (2, 2, "", "tomato", "chopped"),
        ),
        # Neither engine found a food: the line stays as a note.
        ("a little love", nlp(None, "", ""), llm(), "unparsed", (None, None, "", "", "a little love")),
        # Only one engine read a food: the other one disagrees on the food.
        (
            "2 green chillies",
            nlp(2, "", "", food=0.4),
            llm(2, None, "green chilli"),
            "conflict",
            (2, 2, "", "green chilli", ""),
        ),
        # No LLM parse at all (an extraction from before ticket 09): engine A alone.
        ("250 g okra", nlp(250, "g", "okra"), None, "nlp_only", (250, 250, "g", "okra", "")),
    ],
)
def test_reconcile(line, a, b, status, expected):
    result = reconcile(line, a, b, UNIT_KEY)

    quantity, quantity_max, unit, food, note = expected
    assert result.status == status
    assert (result.unit, result.food, result.note) == (unit, food, note)
    if quantity is None:
        assert (result.quantity, result.quantity_max) == (None, None)
    else:
        assert [result.quantity, result.quantity_max] == pytest.approx([quantity, quantity_max])


def test_conflict_names_the_fields_that_differ():
    result = reconcile("1 cup tomatoes", nlp(1, "cup", "tomatoes"), llm(2, None, "tomato"), UNIT_KEY)

    assert result.differing == ("quantity", "unit")


def test_a_lower_bar_for_nlp_comes_from_the_caller():
    result = reconcile(
        "2 tbsp oil",
        nlp(2, "tbsp", "oil", quantity=0.8),
        llm(1, "tbsp", "oil"),
        UNIT_KEY,
        nlp_confidence=0.75,
    )

    assert result.status == "nlp_preferred"
