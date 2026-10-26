"""The Gate at the pipeline seam: what reaches Mealie, what goes to the Review Queue."""

import copy
import csv

import pytest

from mealie_pipeline.adapters.fake_llm import FakeLLM
from tests.test_pipeline_seam import (
    ITEM_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]

DESC_QUOTE = "Heat the oil in a kadhai, add the cumin seeds and the sliced onions and cook until translucent."


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def ingredient(line, quote=None, stated=True):
    return {
        "line": line,
        "original_line": quote or line,
        "section": None,
        "quantity_stated": stated,
        "evidence": [{"source": "desc", "quote": quote or line}],
    }


def one_step():
    """A single step that mentions only okra, onions and oil: cumin seeds and salt go unused (S2)."""
    text = "Cook the okra and the onions in oil."
    return [{"section": None, "text": text, "evidence": [{"source": "desc", "quote": DESC_QUOTE}]}]


def with_changes(**changes):
    recipe = copy.deepcopy(load("llm_extract_okra.json"))
    recipe.update(changes)
    return recipe


def script(world: World, recipe, **kwargs):
    world.llm = FakeLLM()
    world.llm.script("extract", recipe, **kwargs)


def tasks(world: World):
    return [c.task for c in world.llm.calls]


def run(world: World, *args: str):
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")
    return world.invoke("run", *args)


def stored_verify(world: World) -> dict:
    return world.store().part(ITEM_KEY).verify or {}


# (a) a hallucinated ingredient is dropped and the rest uploads -------------------------------


def test_a_hallucinated_ingredient_is_dropped_and_the_rest_uploads(world: World):
    recipe = load("llm_extract_okra.json")
    recipe["ingredients"].append(ingredient("2 cups saffron"))  # no such quote in the description
    script(world, recipe)

    result = run(world)

    assert result.exit_code == 0, result.output
    stored = next(iter(world.mealie.recipes.values()))
    assert len(stored["recipeIngredient"]) == 5  # the saffron line is gone
    assert "saffron" not in {f.name for f in world.mealie.foods.values()}  # and left no junk Food behind
    verify = stored_verify(world)
    assert verify["dropped_ingredients"] == ["2 cups saffron"]
    assert verify["outcome"] == "upload"
    # Hand-computed: H3 = 1 - 1/6 = 0.8333 (weight 20), S2 = 1 (25), S6 = 1 (15).
    # (20*0.8333 + 25 + 15) / 60 = 94.4, above the judge-skip level of 90.
    assert verify["score"] == 94.4
    assert "judge" not in tasks(world)  # no extra LLM call for a score of 90 or more
    assert [t.name for t in [t for t in world.mealie.tags.values() if t.name == "To Review"]] == []


def test_a_clean_recipe_scores_100_and_never_calls_the_judge(world: World):
    result = run(world)

    assert result.exit_code == 0, result.output
    assert stored_verify(world)["score"] == 100.0
    assert tasks(world) == ["extract"]


# (b) one ingredient goes to review, not Mealie ------------------------------------------------


def test_a_recipe_with_one_ingredient_is_retried_once_then_held_back_for_review(world: World):
    script(world, with_changes(ingredients=[ingredient("250 g okra (bhindi)")]))

    result = run(world)

    assert result.exit_code == 0, result.output
    assert "REVIEW" in result.output and "H2" in result.output
    assert world.mealie.recipes == {}  # nothing uploaded
    # One retry: the second call is the strongest tier and carries the findings.
    assert [c.tier for c in world.llm.calls] == ["strong", "strongest"]
    assert "H2" in world.llm.calls[1].prompt and "failed verification" in world.llm.calls[1].prompt
    store = world.store()
    assert store.stage_status("part", ITEM_KEY, "verify") == "review"
    assert store.stage_status("part", ITEM_KEY, "upload") is None
    verify = stored_verify(world)
    assert verify["outcome"] == "review" and verify["extraction_attempts"] == 2
    assert "H2" in verify["failed_checks"]

    review = (world.workspace / "review" / "youtube_de1ppj9L4Hk_1.md").read_text(encoding="utf-8")
    assert "https://www.youtube.com/watch?v=de1ppj9L4Hk" in review  # the Video link
    assert "not classified yet" in review  # the label
    assert "### desc" in review and "250 g Okra" not in review and "INGREDIENTS" in review  # the Source
    assert "**H2**" in review and "needs at least 2 ingredients" in review  # the failed check
    assert "250 g okra" in review  # the extracted recipe


def test_a_rerun_does_not_retry_or_upload_a_held_back_recipe(world: World):
    script(world, with_changes(ingredients=[ingredient("250 g okra (bhindi)")]))
    run(world)
    calls = len(world.llm.calls)

    again = world.invoke("run")

    assert again.exit_code == 0 and len(world.llm.calls) == calls
    assert world.mealie.recipes == {}


def test_the_retry_can_rescue_a_recipe(world: World):
    script(world, with_changes(ingredients=[ingredient("250 g okra (bhindi)")]))
    world.llm.script("extract", load("llm_extract_okra.json"), when_prompt_has="failed verification")
    world.llm._scripts.insert(0, world.llm._scripts.pop())  # the retry script must be tried first

    result = run(world)

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 1
    assert stored_verify(world)["extraction_attempts"] == 2
    assert stored_verify(world)["outcome"] == "upload"


# (c) a 70-score recipe uploads with To Review -----------------------------------------------


def test_a_recipe_scoring_between_60_and_79_uploads_with_the_review_tag(world: World):
    steps = one_step()
    script(world, with_changes(instructions=steps))
    world.llm.script(
        "judge",
        {"problems": [{"severity": "major", "field": "steps", "description": "no temperature given"}]},
    )

    result = run(world)

    assert result.exit_code == 0, result.output
    # Hand-computed: cumin seeds and salt are never used in the single step, so S2 = 1 - 2/5 = 0.6.
    # (20*1 + 25*0.6 + 15*1) / 60 = 83.3: below 90, so the judge runs; one `major` costs 15 -> 68.3.
    verify = stored_verify(world)
    assert verify["score"] == 68.3
    assert verify["outcome"] == "upload_review"
    assert "S2" in verify["failed_checks"] and "S7" in verify["failed_checks"]
    assert tasks(world) == ["extract", "judge"]
    assert world.llm.calls[1].tier == "strong"
    recipe = next(iter(world.mealie.recipes.values()))
    assert [t["name"] for t in recipe["tags"]] == ["Dinner", "Vegan", "To Review"]
    assert [t.name for t in world.mealie.tags.values()].count("To Review") == 1


def test_the_review_tag_that_already_exists_is_reused_not_created_again(world: World):
    existing = world.mealie.create_tag("To Review")
    steps = one_step()
    script(world, with_changes(instructions=steps))
    world.llm.script("judge", {"problems": [{"severity": "major", "field": "steps", "description": "x"}]})

    run(world)

    recipe = next(iter(world.mealie.recipes.values()))
    assert recipe["tags"][-1]["id"] == existing.id
    assert [t.name for t in world.mealie.tags.values()].count("To Review") == 1


def test_a_blocker_from_the_judge_sends_the_recipe_to_review_after_one_retry(world: World):
    steps = one_step()
    script(world, with_changes(instructions=steps))
    world.llm.script(
        "judge", {"problems": [{"severity": "blocker", "field": "ingredients", "description": "x"}]}
    )

    result = run(world)

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}  # 83.3 - 30 = 53.3 < 60, twice
    assert tasks(world) == ["extract", "judge", "extract", "judge"]
    assert stored_verify(world)["outcome"] == "review"


def test_an_unavailable_judge_never_blocks_the_recipe(world: World):
    from mealie_pipeline.adapters.llm import LLMError

    steps = one_step()
    script(world, with_changes(instructions=steps))
    world.llm.script("judge", LLMError("boom"))

    result = run(world)

    assert result.exit_code == 0, result.output
    assert stored_verify(world)["score"] == 83.3 and len(world.mealie.recipes) == 1


# other hard checks and the dry run ------------------------------------------------------------


def test_more_than_20_percent_ungrounded_ingredients_fails_h3(world: World):
    recipe = load("llm_extract_okra.json")
    recipe["ingredients"] += [ingredient("2 cups saffron"), ingredient("1 kg gold leaf")]  # 2 of 7 = 29%
    script(world, recipe)

    result = run(world)

    assert "REVIEW" in result.output and "H3" in stored_verify(world)["failed_checks"]
    assert world.mealie.recipes == {}


def test_dry_run_reports_what_would_go_to_review_and_writes_no_payload_for_it(world: World):
    script(world, with_changes(ingredients=[ingredient("250 g okra (bhindi)")]))

    result = run(world, "--dry-run")

    assert result.exit_code == 0, result.output
    assert "would go to the Review Queue" in result.output
    assert not (world.workspace / "work" / "payloads").exists()
    assert world.mealie.recipes == {} and "judge" not in tasks(world)


# report and status ----------------------------------------------------------------------------


def test_report_and_status_show_the_gate(world: World):
    script(world, with_changes(ingredients=[ingredient("250 g okra (bhindi)")]))
    run(world)

    world.invoke("report")
    with (world.workspace / "reports" / "report.csv").open(encoding="utf-8-sig", newline="") as handle:
        (row,) = list(csv.DictReader(handle))
    status = world.invoke("status").output

    assert (row["verify_status"], row["upload_status"]) == ("review", "")
    assert (row["outcome"], row["extraction_attempts"]) == ("review", "2")
    assert "H2" in row["failed_checks"] and row["score"]
    assert row["failure_reason"].startswith("verify:")
    assert "1 in the Review Queue, 1 extracted a second time" in status
