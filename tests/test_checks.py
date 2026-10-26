"""S1, S2 and S6 (pure, table-driven)."""

import pytest

from mealie_pipeline.checks import food_overlap, ingredients_vs_steps, plausibility

KNOWN = ["okra", "onion", "oil", "salt", "garlic", "water"]


@pytest.mark.parametrize(
    ("foods", "steps", "score", "mentions"),
    [
        (["okra", "onions", "mustard oil"], ["Cut the okra.", "Fry the onions in oil."], 1.0, ""),
        (["okra", "garlic"], ["Cut the okra."], 0.5, "never used in a step: garlic"),
        (["okra", "salt"], ["Cut the okra.", "Add salt."], 1.0, ""),
        (
            ["okra", "onion"],
            ["Cut the okra and onion, then add salt."],
            0.5,
            "used in a step but not listed: salt",
        ),
        (
            ["okra", "mustard oil"],
            ["Heat the oil.", "Add the okra."],
            1.0,
            "",
        ),  # "oil" is covered by "mustard oil"
        (["okra", "garlic", "ginger", "chilli"], ["Boil water."], 0.0, "never used"),  # clamps at zero
        ([], ["Cut."], 0.0, "no ingredients"),
    ],
)
def test_ingredients_vs_steps(foods, steps, score, mentions):
    got, details = ingredients_vs_steps(foods, steps, KNOWN)

    assert got == pytest.approx(score)
    assert mentions in details


@pytest.mark.parametrize(
    ("servings", "prep", "cook", "total", "score", "mention"),
    [
        (4, 10, 20, 30, 1.0, "plausible"),
        (None, None, None, None, 1.0, "plausible"),  # nothing given is fine
        (0, None, None, None, 0.5, "servings 0"),
        (500, None, None, None, 0.5, "servings 500"),
        (4, 30, None, 20, 0.5, "less than prep"),
        (4, 10, 40, 30, 0.5, "less than cook"),
        (4, None, None, 2000, 0.5, "over 24 hours"),
        (0, 30, None, 20, 0.0, "servings"),  # two problems: 1 - 2*0.5
    ],
)
def test_plausibility(servings, prep, cook, total, score, mention):
    got, details = plausibility(servings, prep, cook, total)

    assert got == pytest.approx(score)
    assert mention in details


def test_food_overlap_is_a_jaccard_score():
    score, _ = food_overlap({"okra", "onion", "salt"}, {"okra", "onion", "garlic"})

    assert score == pytest.approx(0.5)  # 2 shared of 4 distinct
    assert food_overlap(set(), set())[0] == 0.0
