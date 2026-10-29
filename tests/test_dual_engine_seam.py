"""Ticket 09 at the pipeline seam: two ingredient parsers, their disagreements, and what the Gate does."""

import copy
import csv

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from mealie_pipeline.cli import app
from tests.helpers import fake_adapters
from tests.test_pipeline_seam import (
    ENGINE,
    ITEM_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]

# What the LLM says about each line of the okra recipe (engine B).
LLM_PARSES = {
    "250 g okra": {"quantity": 250, "unit": "gram", "food": "okra"},
    "2 small onions": {"quantity": 2, "food": "onion", "note": "small"},
    "2 tbsp mustard oil": {"quantity": 2, "unit": "tablespoon", "food": "mustard oil"},
    "1/2 tsp cumin seeds": {"quantity": 0.5, "unit": "teaspoon", "food": "cumin seeds"},
    "salt, to taste": {"food": "salt", "note": "to taste"},
}


class DualWorld(World):
    """The okra world with a replaceable engine A."""

    engine: FakeIngredientEngine = ENGINE

    def invoke(self, *args: str):
        adapters = fake_adapters(
            mealie=self.mealie, llm=self.llm, videos=self.videos, images=self.images, engine=self.engine
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)


@pytest.fixture
def world(tmp_path) -> DualWorld:
    return DualWorld(tmp_path)


def script(world: DualWorld, **changes: dict) -> None:
    """Scripts the extraction with `LLM_PARSES` (overridden per line by `changes`) on each ingredient."""
    recipe = copy.deepcopy(load("llm_extract_okra.json"))
    for ingredient in recipe["ingredients"]:
        ingredient["llm_parse"] = changes.get(ingredient["line"], LLM_PARSES[ingredient["line"]])
    world.llm = FakeLLM()
    world.llm.script("extract", recipe)


def run(world: DualWorld):
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")
    return world.invoke("run")


def verify_of(world: DualWorld) -> dict:
    return world.store().part(ITEM_KEY).verify or {}


def parsed_of(world: DualWorld) -> dict[str, dict]:
    return {p["original_text"]: p for p in world.store().part(ITEM_KEY).parsed or []}


def check(verify: dict, check_id: str) -> dict:
    return next(c for c in verify["checks"] if c["id"] == check_id)


def test_engines_that_agree_upload_with_full_parse_agreement(world: DualWorld):
    script(world)

    assert run(world).exit_code == 0
    statuses = {t: p["parse_status"] for t, p in parsed_of(world).items()}
    assert set(statuses.values()) == {"agreed"}
    assert check(verify_of(world), "S3")["score"] == 1.0
    assert check(verify_of(world), "S5")["score"] == 1.0
    assert len(world.mealie.recipes) == 1


def test_a_line_where_nlp_is_sure_takes_nlp_and_one_where_it_is_not_takes_the_llm(world: DualWorld):
    world.engine = FakeIngredientEngine(
        {
            **ENGINE.parses,
            # NLP reads 2 tbsp with confidence .99, the LLM says 3: NLP wins.
            "2 tbsp mustard oil": EngineParse(2, 2, "tbsps", "mustard oil", "", 0.99),
            # NLP reads 1/2 tsp but is unsure of the amount, the LLM says 1/4: the LLM wins, flagged.
            "1/2 tsp cumin seeds": EngineParse(0.5, 0.5, "tsps", "cumin seeds", "", 0.99, {"quantity": 0.5}),
        }
    )
    script(
        world,
        **{
            "2 tbsp mustard oil": {"quantity": 3, "unit": "tablespoon", "food": "mustard oil"},
            "1/2 tsp cumin seeds": {"quantity": 0.25, "unit": "teaspoon", "food": "cumin seeds"},
        },
    )

    assert run(world).exit_code == 0
    recipe = next(iter(world.mealie.recipes.values()))
    quantities = {i["originalText"]: i["quantity"] for i in recipe["recipeIngredient"]}
    assert quantities["2 tbsp mustard oil"] == 2  # engine A
    assert quantities["1/2 tsp cumin seeds"] == 0.25  # engine B
    statuses = {t: p["parse_status"] for t, p in parsed_of(world).items()}
    assert statuses["2 tbsp mustard oil"] == "nlp_preferred"
    assert statuses["1/2 tsp cumin seeds"] == "conflict"
    # Hand-computed: S3 = 4 alike of 5 lines = 0.8, every other check scores 1. With the default
    # weights (H3 20, S2 25, S3 15, S5 10, S6 15) the score is (85 - 15 * 0.2) / 85 = 96.5.
    assert check(verify_of(world), "S3")["score"] == pytest.approx(0.8)
    assert "1/2 tsp cumin seeds" in check(verify_of(world), "S3")["details"]
    assert verify_of(world)["score"] == 96.5


def test_a_line_neither_engine_can_find_a_food_in_sends_the_recipe_to_review(world: DualWorld):
    world.engine = FakeIngredientEngine({**ENGINE.parses, "salt, to taste": EngineParse(None, None, "", "", "", 0.1)})
    script(world, **{"salt, to taste": {"note": "to taste"}})

    result = run(world)

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}
    verify = verify_of(world)
    assert verify["outcome"] == "review"
    assert "H4" in verify["failed_checks"]
    assert "salt, to taste" in check(verify, "H4")["details"]
    assert parsed_of(world)["salt, to taste"]["parse_status"] == "unparsed"


def test_an_implausible_quantity_is_flagged_and_lowers_the_sanity_score(world: DualWorld):
    world.engine = FakeIngredientEngine(
        {**ENGINE.parses, "2 tbsp mustard oil": EngineParse(25, 25, "tbsps", "mustard oil", "", 0.99)}
    )
    script(world, **{"2 tbsp mustard oil": {"quantity": 25, "unit": "tablespoon", "food": "mustard oil"}})

    assert run(world).exit_code == 0
    assert parsed_of(world)["2 tbsp mustard oil"]["suspicious"] == ["25 tablespoon is more than 20"]
    assert check(verify_of(world), "S5")["score"] == pytest.approx(0.8)


def test_the_extraction_without_llm_parses_still_uploads_on_engine_a_alone(world: DualWorld):
    world.llm = FakeLLM()
    world.llm.script("extract", load("llm_extract_okra.json"))

    assert run(world).exit_code == 0
    assert {p["parse_status"] for p in parsed_of(world).values()} == {"nlp_only"}
    assert check(verify_of(world), "S3")["score"] is None


def test_steps_link_to_their_ingredients_through_reference_ids(world: DualWorld):
    script(world)

    assert run(world).exit_code == 0
    recipe = next(iter(world.mealie.recipes.values()))
    ids = {i["referenceId"]: i["originalText"] for i in recipe["recipeIngredient"]}
    linked = {r["referenceId"] for s in recipe["recipeInstructions"] for r in s["ingredientReferences"]}
    assert linked and linked <= set(ids)
    step = next(s for s in recipe["recipeInstructions"] if "mustard oil" in s["text"].lower())
    assert "2 tbsp mustard oil" in {ids[r["referenceId"]] for r in step["ingredientReferences"]}


def test_the_report_counts_lines_per_parse_status_and_suspicious_lines(world: DualWorld):
    world.engine = FakeIngredientEngine(
        {**ENGINE.parses, "2 tbsp mustard oil": EngineParse(25, 25, "tbsps", "mustard oil", "", 0.99)}
    )
    script(world, **{"2 tbsp mustard oil": {"quantity": 3, "unit": "tablespoon", "food": "mustard oil"}})
    run(world)

    assert world.invoke("report").exit_code == 0
    path = world.workspace / "reports" / "report.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        (row,) = list(csv.DictReader(handle))
    assert (row["lines_agreed"], row["lines_nlp_preferred"], row["lines_conflict"]) == ("4", "1", "0")
    assert (row["lines_unparsed"], row["suspicious_lines"]) == ("0", "1")
