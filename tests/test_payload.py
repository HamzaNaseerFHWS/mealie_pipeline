"""Table tests for the pure Mealie payload builder."""

import pytest

from mealie_pipeline.models import ExtractedRecipe, ParsedIngredient
from mealie_pipeline.payload import build_payload, iso_duration


@pytest.mark.parametrize(
    ("minutes", "expected"),
    [(None, None), (0, None), (5, "PT5M"), (60, "PT1H"), (90, "PT1H30M"), (125, "PT2H5M")],
)
def test_iso_duration(minutes, expected):
    assert iso_duration(minutes) == expected


def ingredient(name, section=None, **extra):
    return ParsedIngredient(
        original_text=f"1 {name}", section=section, quantity=1, food_id=f"id-{name}", food_name=name, **extra
    )


def build(parsed, **recipe_fields):
    recipe = ExtractedRecipe.model_validate(
        {
            "is_recipe": True,
            "name": "Sauce",
            "instructions": [
                {"section": "Sauce", "text": "Mix.", "evidence": []},
                {"section": "Sauce", "text": "Cook.", "evidence": []},
                {"section": "Dough", "text": "Knead.", "evidence": []},
            ],
            "notes": ["Keeps 3 days."],
            **recipe_fields,
        }
    )
    ids = iter(f"ref-{n}" for n in range(100))
    return build_payload(
        recipe,
        parsed,
        [{"id": "t1", "name": "Dinner", "slug": "dinner"}],
        org_url="https://www.youtube.com/watch?v=abc",
        item_key="youtube:abc#1",
        video_key="youtube:abc",
        platform="youtube",
        new_id=lambda: next(ids),
    )


def test_section_title_goes_on_the_first_ingredient_of_each_section_only():
    payload = build(
        [
            ingredient("a", "For the sauce"),
            ingredient("b", "For the sauce"),
            ingredient("c", "For the dough"),
            ingredient("d"),
        ]
    )

    assert [i["title"] for i in payload["recipeIngredient"]] == ["For the sauce", None, "For the dough", None]
    assert [i["referenceId"] for i in payload["recipeIngredient"]] == ["ref-0", "ref-1", "ref-2", "ref-3"]


def test_ingredient_fields_follow_the_mealie_shape():
    payload = build([ingredient("onion", unit_id="u1", unit_name="cup", note="diced")])

    assert payload["recipeIngredient"][0] == {
        "quantity": 1,
        "unit": {"id": "u1", "name": "cup"},
        "food": {"id": "id-onion", "name": "onion"},
        "note": "diced",
        "originalText": "1 onion",
        "title": None,
        "referenceId": "ref-0",
    }


def test_unit_is_null_without_a_unit():
    assert build([ingredient("salt")])["recipeIngredient"][0]["unit"] is None


def test_provenance_times_notes_and_steps():
    payload = build(
        [ingredient("salt")], servings=4, yield_text="4 servings", prep_minutes=15, cook_minutes=75
    )

    assert payload["orgURL"] == "https://www.youtube.com/watch?v=abc"
    assert payload["extras"] == {
        "item_key": "youtube:abc#1",
        "video_key": "youtube:abc",
        "part": 1,
        "of": 1,
        "platform": "youtube",
        "pipeline_version": payload["extras"]["pipeline_version"],
    }
    assert payload["extras"]["pipeline_version"]
    assert (payload["prepTime"], payload["performTime"]) == ("PT15M", "PT1H15M")
    assert "totalTime" not in payload
    assert (payload["recipeServings"], payload["recipeYield"]) == (4, "4 servings")
    assert payload["notes"] == [{"title": "", "text": "Keeps 3 days."}]
    assert [s["title"] for s in payload["recipeInstructions"]] == ["Sauce", "", "Dough"]
    assert payload["tags"] == [{"id": "t1", "name": "Dinner", "slug": "dinner"}]
