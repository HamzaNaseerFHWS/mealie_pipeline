"""Ticket 25 at the pipeline seam: `mp tags protein [--apply]` over every recipe in Mealie, and the
Protein Tag on a newly uploaded recipe."""

import csv
import json
from pathlib import Path

import pytest

from mealie_pipeline.adapters.mealie import Recipe, Tag
from mealie_pipeline.errors import MealieHttpError
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

CONFIG = Path(__file__).parents[1] / "config" / "protein_tags.yaml"


class RecordingMealie(FlakyImageMealie):
    """Records every write of the backfill; PATCHes to `failing` slugs answer 500."""

    def __init__(self, *args, **kwargs):
        self.writes: list[tuple[str, str]] = []
        self.failing: set[str] = set()
        super().__init__(*args, **kwargs)
        self.writes.clear()  # the starting catalog is setup, not a write under test

    def create_tag(self, name: str) -> Tag:
        self.writes.append(("create_tag", name))
        return super().create_tag(name)

    def patch_recipe(self, slug: str, payload: Recipe) -> Recipe:
        self.writes.append(("patch", slug))
        if slug in self.failing:
            raise MealieHttpError("PATCH", f"/api/recipes/{slug}", 500, "boom")
        return super().patch_recipe(slug, payload)


class ProteinWorld(World):
    mealie: RecordingMealie


def tags_of(world: ProteinWorld, slug: str) -> list[str]:
    return [t["name"] for t in world.mealie.recipes[slug]["tags"]]


def add_recipe(world: ProteinWorld, name: str, *, lines=(), foods=(), tags=(), locked=False) -> str:
    """Seeds Mealie directly (the setup is not under test): unparsed note lines, parsed Foods, tags."""
    mealie = world.mealie
    slug = mealie.create_recipe(name)
    catalog = {t.name: t for t in mealie.tags.values()}
    ingredients = [{"quantity": 0, "food": None, "note": line, "display": line} for line in lines]
    for food_name in foods:
        food = next((f for f in mealie.foods.values() if f.name == food_name), None) or mealie.create_food(
            food_name
        )
        ingredients.append({"quantity": 1, "food": {"id": food.id, "name": food.name}, "note": ""})
    recipe = mealie.recipes[slug]
    recipe["recipeIngredient"] = ingredients
    recipe["tags"] = [catalog[t].model_dump() for t in tags]
    recipe["settings"]["locked"] = locked
    return slug


@pytest.fixture
def world(tmp_path) -> ProteinWorld:
    world = ProteinWorld(tmp_path)
    (tmp_path / "config" / "protein_tags.yaml").write_text(
        CONFIG.read_text(encoding="utf-8"), encoding="utf-8"
    )
    world.mealie = RecordingMealie(token=TOKEN, tags=["Dinner", "Dessert", "chicken"], foods=["onion"])
    return world


@pytest.fixture
def mixed(world: ProteinWorld) -> dict[str, str]:
    """A pipeline recipe, older imports, one already tagged and one locked."""
    return {
        "karahi": add_recipe(world, "Karahi", foods=["chicken thighs", "onion"], tags=["Dinner"]),
        "dal": add_recipe(world, "Dal Tadka", lines=["1 cup masoor", "2 tbsp ghee"]),
        "cake": add_recipe(world, "Chocolate Cake", lines=["3 eggs", "200 g butter"], tags=["Dessert"]),
        "butter": add_recipe(world, "Butter Chicken", lines=["1 kg chicken"], tags=["chicken"]),
        "nihari": add_recipe(world, "Beef Nihari", lines=["1 kg beef shank"], locked=True),
    }


def rows(world: ProteinWorld) -> dict[str, dict[str, str]]:
    path = world.workspace / "reports" / "protein_tags.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["slug"]: row for row in csv.DictReader(handle)}


def set_override(world: ProteinWorld, slug: str, value: str) -> None:
    path = world.workspace / "reports" / "protein_tags.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields, table = reader.fieldnames, list(reader)
    for row in table:
        if row["slug"] == slug:
            row["override"] = value
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or [])
        writer.writeheader()
        writer.writerows(table)


def test_the_dry_run_writes_the_csv_and_changes_nothing(world: ProteinWorld, mixed):
    before = json.dumps(world.mealie.recipes, sort_keys=True)

    result = world.invoke("tags", "protein")

    assert result.exit_code == 0, result.output
    assert world.mealie.writes == []
    assert json.dumps(world.mealie.recipes, sort_keys=True) == before
    report = rows(world)
    assert set(report) == set(mixed.values())
    karahi = report[mixed["karahi"]]
    assert (karahi["name"], karahi["current_tags"], karahi["proposed_tags"]) == (
        "Karahi",
        "Dinner",
        "Chicken",
    )
    assert karahi["triggers"] == "Chicken: chicken"
    assert karahi["link"] == f"http://fake-mealie:9000/g/home/r/{mixed['karahi']}"
    assert karahi["override"] == ""
    assert report[mixed["dal"]]["proposed_tags"] == "Lentils"
    assert report[mixed["cake"]]["proposed_tags"] == ""
    assert report[mixed["butter"]]["result"] == "unchanged"  # it already has "chicken"
    assert report[mixed["nihari"]]["result"] == "locked (skipped)"
    assert "2 recipes would gain a Protein Tag" in result.output


def test_apply_adds_protein_tags_and_keeps_every_existing_tag(world: ProteinWorld, mixed):
    result = world.invoke("tags", "protein", "--apply")

    assert result.exit_code == 0, result.output
    assert tags_of(world, mixed["karahi"]) == ["Dinner", "chicken"]  # reuses "chicken", no duplicate
    assert tags_of(world, mixed["dal"]) == ["Lentils"]
    assert tags_of(world, mixed["cake"]) == ["Dessert"]
    assert tags_of(world, mixed["butter"]) == ["chicken"]
    assert sorted(t.name for t in world.mealie.tags.values()) == ["Dessert", "Dinner", "Lentils", "chicken"]
    assert [w for w in world.mealie.writes if w[0] == "create_tag"] == [("create_tag", "Lentils")]
    assert sorted(w[1] for w in world.mealie.writes if w[0] == "patch") == sorted(
        [mixed["karahi"], mixed["dal"]]
    )
    assert "2 recipes gained a Protein Tag" in result.output
    assert rows(world)[mixed["dal"]]["result"] == "added: Lentils"


def test_a_missing_protein_tag_is_created_once_for_many_recipes(world: ProteinWorld):
    for name in ("Dal Makhani", "Dal Fry", "Masoor Dal"):
        add_recipe(world, name)

    world.invoke("tags", "protein", "--apply")

    assert [w for w in world.mealie.writes if w[0] == "create_tag"] == [("create_tag", "Lentils")]


def test_a_second_apply_makes_no_writes(world: ProteinWorld, mixed):
    world.invoke("tags", "protein", "--apply")
    world.mealie.writes.clear()

    result = world.invoke("tags", "protein", "--apply")

    assert result.exit_code == 0, result.output
    assert world.mealie.writes == []
    assert "0 recipes gained a Protein Tag" in result.output


def test_an_override_removing_a_proposed_tag_wins_and_is_kept(world: ProteinWorld, mixed):
    world.invoke("tags", "protein")
    set_override(world, mixed["dal"], "-Lentils")
    set_override(world, mixed["cake"], "+Egg")

    world.invoke("tags", "protein", "--apply")

    assert tags_of(world, mixed["dal"]) == []
    assert tags_of(world, mixed["cake"]) == ["Dessert", "Egg"]
    report = rows(world)
    assert report[mixed["dal"]]["override"] == "-Lentils"  # still there for the next run
    assert report[mixed["cake"]]["override"] == "+Egg"


def test_block_keeps_a_recipe_free_of_protein_tags(world: ProteinWorld, mixed):
    world.invoke("tags", "protein")
    set_override(world, mixed["karahi"], "block")

    world.invoke("tags", "protein", "--apply")

    assert tags_of(world, mixed["karahi"]) == ["Dinner"]
    assert rows(world)[mixed["karahi"]]["result"] == "blocked"


def test_a_locked_recipe_is_skipped_and_reported(world: ProteinWorld, mixed):
    result = world.invoke("tags", "protein", "--apply")

    assert tags_of(world, mixed["nihari"]) == []
    assert ("patch", mixed["nihari"]) not in world.mealie.writes
    assert "Beef" not in {t.name for t in world.mealie.tags.values()}  # not created for a skipped recipe
    assert rows(world)[mixed["nihari"]]["result"] == "locked (skipped)"
    assert f"locked: {mixed['nihari']}" in result.output


def test_a_failed_patch_is_reported_and_the_run_goes_on(world: ProteinWorld, mixed):
    world.mealie.failing.add(mixed["karahi"])

    result = world.invoke("tags", "protein", "--apply")

    assert result.exit_code == 1
    assert tags_of(world, mixed["dal"]) == ["Lentils"]
    assert rows(world)[mixed["karahi"]]["result"].startswith("failed:")
    assert f"failed: {mixed['karahi']}" in result.output


def test_llm_check_sends_only_ambiguous_recipes_in_batches_and_keeps_listed_names(world: ProteinWorld):
    clear = add_recipe(world, "Karahi", foods=["chicken thighs", "onion"])
    unclear = [add_recipe(world, f"Mystery Stew {n}", foods=["meat"]) for n in range(21)]
    world.llm = recipe_llm()
    world.llm.script(
        "protein_tags",
        {"recipes": [{"slug": unclear[0], "tags": ["beef", "Unicorn"]}]},
        when_prompt_has=unclear[0],
    )
    world.llm.script("protein_tags", {"recipes": []})

    result = world.invoke("tags", "protein", "--llm-check")

    assert result.exit_code == 0, result.output
    assert [c.task for c in world.llm.calls] == ["protein_tags", "protein_tags"]  # 20 + 1
    assert all(c.tier == "fast" for c in world.llm.calls)
    sent = "".join(c.prompt for c in world.llm.calls)
    assert all(slug in sent for slug in unclear) and clear not in sent
    enum = world.llm.calls[0].schema["properties"]["recipes"]["items"]["properties"]["tags"]["items"]["enum"]
    assert enum[:2] == ["Chicken", "Beef"] and "Unicorn" not in enum
    report = rows(world)
    assert (report[unclear[0]]["proposed_tags"], report[unclear[0]]["triggers"]) == ("Beef", "Beef: llm")
    assert report[clear]["proposed_tags"] == "Chicken"


def test_mp_status_shows_how_many_recipes_gained_a_protein_tag(world: ProteinWorld, mixed):
    world.invoke("tags", "protein", "--apply")

    result = world.invoke("status")

    assert "Protein Tags: 2 recipes gained one" in result.output


def test_a_newly_uploaded_chicken_recipe_carries_the_chicken_tag(world: ProteinWorld):
    world.mealie = RecordingMealie(token=TOKEN, tags=["Dinner", "Vegan", "Chicken"], foods=["Salt", "onion"])
    recipe = load("llm_extract_okra.json")
    recipe["name"] = "Chicken Bhindi"
    recipe["tag_choices"] = [{"tag": "Dinner", "reason": "a main"}]
    world.llm = recipe_llm()
    world.llm.script("extract", recipe)
    world.invoke("add", URL)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    (uploaded,) = world.mealie.recipes.values()
    assert [t["name"] for t in uploaded["tags"]] == ["Dinner", "Chicken"]
