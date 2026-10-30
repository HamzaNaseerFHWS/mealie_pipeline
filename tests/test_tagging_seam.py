"""Ticket 10 at the pipeline seam: Rule Tags, contradictions, the tag fallback and suggested tags."""

import csv

import pytest

from tests.helpers import recipe_llm
from tests.test_pipeline_seam import (
    TOKEN,
    URL,
    FlakyImageMealie,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]

# "okra" stands in for meat: it is the fixture recipe's main Food (placeholder tag names, as in the config).
RULES = """
food_groups:
  meat: [okra]
  egg: [egg]
rules:
  - {tag: Vegetarian, when: {no_foods_in: [meat]}}
  - {tag: Quick, when: {max_total_minutes: 30}}
  - {tag: Ghost, when: {max_total_minutes: 30}}
contradictions:
  - {tag: Vegetarian, foods_in: [meat]}
"""


@pytest.fixture
def world(tmp_path) -> World:
    world = World(tmp_path)
    (tmp_path / "config" / "tag_rules.yaml").write_text(RULES, encoding="utf-8")
    world.mealie = FlakyImageMealie(
        token=TOKEN,
        tags=["Dinner", "Vegetarian", "Quick"],
        foods=["Salt", "onion"],
        units=["gram", "tablespoon"],
    )
    return world


def script(world: World, *choices: str) -> None:
    recipe = load("llm_extract_okra.json")
    recipe["tag_choices"] = [{"tag": c, "reason": "x"} for c in choices]
    world.llm = recipe_llm()
    world.llm.script("extract", recipe)


def uploaded_tags(world: World) -> list[str]:
    (recipe,) = world.mealie.recipes.values()
    return [t["name"] for t in recipe["tags"]]


def test_a_tag_the_llm_invents_is_not_applied_and_lands_in_suggested_tags(world: World):
    script(world, "Dinner", "Made Up Tag")
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert "Made Up Tag" not in uploaded_tags(world)
    rows = list(
        csv.DictReader((world.workspace / "reports" / "suggested_tags.csv").open(encoding="utf-8-sig"))
    )
    assert [r["name"] for r in rows] == ["Made Up Tag"]
    assert not [t for t in world.mealie.tags.values() if t.name == "Made Up Tag"]


def test_a_vegetarian_tag_on_a_meat_recipe_is_removed_and_flagged(world: World):
    script(world, "Dinner", "vegetarian")
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    # Rule tags first; the "Ghost" rule names a missing tag, so it is skipped.
    assert uploaded_tags(world) == ["Quick", "Dinner"]
    assert "removed tag 'Vegetarian'" in result.output


def test_a_rule_tag_that_the_llm_also_chose_is_applied_once_with_the_existing_spelling(world: World):
    script(world, "Dinner", "quick!")
    world.invoke("add", URL)

    world.invoke("run")

    assert uploaded_tags(world) == ["Quick", "Dinner"]


def test_when_nothing_applies_to_review_is_created_once_and_applied(world: World):
    script(world, "Made Up Tag")
    (world.workspace / "config" / "tag_rules.yaml").write_text("rules: []\n", encoding="utf-8")
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert uploaded_tags(world) == ["To Review"]
    assert [t.name for t in world.mealie.tags.values()].count("To Review") == 1
    extract_calls = [c for c in world.llm.calls if c.task == "extract"]
    assert len(extract_calls) == 2  # one retry, then the fallback


def test_the_payload_never_sets_a_category(world: World):
    script(world, "Dinner")
    world.invoke("add", URL)

    world.invoke("run")

    (recipe,) = world.mealie.recipes.values()
    assert not recipe.get("recipeCategory")
