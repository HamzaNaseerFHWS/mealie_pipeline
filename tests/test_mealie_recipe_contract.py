"""Contract: recipes, ingredients, lookups and images, identical for every MealieGateway."""

import contextlib
from collections.abc import Iterator

import pytest

from mealie_pipeline.errors import MealieHttpError

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16


@pytest.fixture
def recipe(gateway, unique) -> Iterator[str]:
    """A fresh recipe slug, deleted afterwards even when the test fails."""
    slug = gateway.create_recipe(unique("recipe"))
    try:
        yield slug
    finally:
        with contextlib.suppress(MealieHttpError):
            gateway.delete_recipe(slug)


def test_create_recipe_returns_a_slug_that_can_be_read_back(gateway, unique):
    name = unique("recipe")
    slug = gateway.create_recipe(name)
    try:
        assert slug
        assert gateway.get_recipe(slug)["name"] == name
    finally:
        gateway.delete_recipe(slug)


def test_patch_sets_source_url_description_extras_and_leaves_other_fields(gateway, recipe, unique):
    name = gateway.get_recipe(recipe)["name"]
    gateway.patch_recipe(
        recipe,
        {
            "description": "Crispy okra",
            "orgURL": "https://www.youtube.com/watch?v=abc",
            "extras": {"item_key": "yt:abc#1"},
        },
    )
    stored = gateway.get_recipe(recipe)
    assert stored["name"] == name
    assert stored["description"] == "Crispy okra"
    assert stored["orgURL"] == "https://www.youtube.com/watch?v=abc"
    assert stored["extras"]["item_key"] == "yt:abc#1"


def test_patch_stores_parsed_ingredients_and_tags(gateway, recipe, unique, live_cleanup):
    food = gateway.create_food(unique("food"))
    unit = gateway.create_unit(unique("unit"))
    tag = gateway.create_tag(unique("tag"))
    live_cleanup("foods", food.id)
    live_cleanup("units", unit.id)
    live_cleanup("organizers/tags", tag.id)

    gateway.patch_recipe(
        recipe,
        {
            "recipeIngredient": [
                {
                    "quantity": 2,
                    "unit": {"id": unit.id, "name": unit.name},
                    "food": {"id": food.id, "name": food.name},
                    "note": "finely chopped",
                    "originalText": "2 cups onion, finely chopped",
                    "referenceId": "8c1a6f5e-3b0f-4b8a-9d0e-0e6a1f2b3c4d",
                }
            ],
            "recipeInstructions": [{"text": "Chop the onion."}],
            "tags": [{"id": tag.id, "name": tag.name, "slug": tag.slug}],
        },
    )
    stored = gateway.get_recipe(recipe)
    ingredient = stored["recipeIngredient"][0]
    assert ingredient["quantity"] == 2
    assert ingredient["food"]["id"] == food.id
    assert ingredient["unit"]["id"] == unit.id
    assert ingredient["note"] == "finely chopped"
    assert stored["recipeInstructions"][0]["text"] == "Chop the onion."
    assert [t["id"] for t in stored["tags"]] == [tag.id]


def test_patch_rejects_an_ingredient_with_an_unknown_food_id(gateway, recipe):
    """Mealie never auto-creates foods on PATCH (wayfinder 03)."""
    bad = {
        "recipeIngredient": [
            {"quantity": 1, "food": {"id": "00000000-0000-0000-0000-000000000000", "name": "nope"}}
        ]
    }
    with pytest.raises(MealieHttpError) as err:
        gateway.patch_recipe(recipe, bad)
    assert err.value.status >= 400


def test_patch_rejects_an_ingredient_with_an_unknown_unit_id(gateway, recipe):
    bad = {
        "recipeIngredient": [
            {"quantity": 1, "unit": {"id": "00000000-0000-0000-0000-000000000000", "name": "nope"}}
        ]
    }
    with pytest.raises(MealieHttpError) as err:
        gateway.patch_recipe(recipe, bad)
    assert err.value.status >= 400


def test_ingredient_without_unit_or_quantity_is_stored(gateway, recipe, unique, live_cleanup):
    food = gateway.create_food(unique("food"))
    live_cleanup("foods", food.id)
    gateway.patch_recipe(
        recipe,
        {
            "recipeIngredient": [
                {"quantity": 0, "unit": None, "food": {"id": food.id, "name": food.name}, "note": "to taste"}
            ]
        },
    )
    ingredient = gateway.get_recipe(recipe)["recipeIngredient"][0]
    assert ingredient["food"]["id"] == food.id
    assert ingredient["unit"] is None


def test_find_recipe_by_source_url(gateway, recipe, unique):
    url = f"https://example.com/{unique('src')}"
    gateway.patch_recipe(recipe, {"orgURL": url})
    found = gateway.find_recipe(org_url=url)
    assert found is not None and found["slug"] == recipe
    assert gateway.find_recipe(org_url=url + "-other") is None


def test_find_recipe_by_item_key(gateway, recipe, unique):
    key = unique("key")
    gateway.patch_recipe(recipe, {"extras": {"item_key": key}})
    found = gateway.find_recipe(item_key=key)
    assert found is not None and found["slug"] == recipe
    assert gateway.find_recipe(item_key=key + "-other") is None


def test_deleted_recipe_is_gone(gateway, unique):
    slug = gateway.create_recipe(unique("recipe"))
    gateway.delete_recipe(slug)
    with pytest.raises(MealieHttpError) as err:
        gateway.get_recipe(slug)
    assert err.value.status == 404


def test_upload_image_from_file_succeeds(gateway, recipe, tmp_path):
    image = tmp_path / "cover.png"
    image.write_bytes(PNG)
    gateway.upload_image(recipe, image)


def test_recipe_url_uses_the_group_slug(gateway, recipe):
    group = gateway.whoami().group_slug
    url = gateway.recipe_url(recipe)
    assert url.endswith(f"/g/{group}/r/{recipe}")
