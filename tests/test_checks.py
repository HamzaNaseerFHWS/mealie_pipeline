"""S1, S2, S3, S5 and S6 (pure, table-driven)."""

import pytest

from mealie_pipeline.checks import (
    food_overlap,
    ingredients_vs_steps,
    parse_agreement,
    plausibility,
    quantity_sanity,
)
from mealie_pipeline.models import ParsedIngredient

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


def test_german_steps_count_the_original_names_as_used_and_listed():
    foods = ["shell pasta", "onion", "tomato paste"]
    originals = ["Muschelnudeln", "Zwiebel", "Tomatenmark"]
    steps = ["Die Muschelnudeln kochen.", "Zwiebel und Tomatenmark anbraten."]

    without, _ = ingredients_vs_steps(foods, steps, KNOWN)
    with_originals, details = ingredients_vs_steps(foods, steps, KNOWN, originals)

    assert without == pytest.approx(0.0)
    assert with_originals == pytest.approx(1.0), details


def test_a_step_food_named_only_by_an_original_name_is_not_reported_as_unlisted():
    known = [*KNOWN, "Tomatenmark"]  # the Mealie Food list has the German word as a name or alias

    score, details = ingredients_vs_steps(["tomato paste"], ["Tomatenmark rühren."], known, ["Tomatenmark"])

    assert score == pytest.approx(1.0), details


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


def line(text, status="agreed", suspicious=()):
    return ParsedIngredient(original_text=text, food_name=text, parse_status=status, suspicious=list(suspicious))


@pytest.mark.parametrize(
    ("statuses", "score", "mention"),
    [
        (["agreed", "agreed", "nlp_preferred", "agreed"], 1.0, "4 of 4 lines parsed alike"),
        (["agreed", "agreed", "agreed", "conflict"], 0.75, "conflict: line 3"),
        (["agreed", "unparsed"], 0.5, "unparsed: line 1"),
        (["agreed", "nlp_only", "conflict"], 0.5, "1 of 2 lines"),  # an engine-A-only line is not counted
        (["nlp_only", "nlp_only"], None, "no LLM parse"),
        ([], None, "no LLM parse"),
    ],
)
def test_parse_agreement(statuses, score, mention):
    got, details = parse_agreement([line(f"line {i}", s) for i, s in enumerate(statuses)])

    assert got == (pytest.approx(score) if score is not None else None)
    assert mention in details


@pytest.mark.parametrize(
    ("findings", "score", "mention"),
    [
        ([[], [], [], []], 1.0, "no suspicious lines"),
        ([[], ["5 kilogram of salt is implausibly much"], [], []], 0.75, "line 1: 5 kilogram of salt"),
        ([["a"], ["b"], [], []], 0.5, "2 suspicious lines"),
        ([], None, "no ingredients"),
    ],
)
def test_quantity_sanity(findings, score, mention):
    got, details = quantity_sanity([line(f"line {i}", suspicious=f) for i, f in enumerate(findings)])

    assert got == (pytest.approx(score) if score is not None else None)
    assert mention in details
