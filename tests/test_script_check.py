"""The script check: pure table tests, then the retry and review hold at the pipeline seam."""

import copy
from typing import Literal

import pytest

from mealie_pipeline.models import Evidence, ExtractedIngredient, ExtractedRecipe, ExtractedStep
from mealie_pipeline.script_check import script_problems
from tests.helpers import non_classify_calls, recipe_llm
from tests.test_pipeline_seam import (
    ITEM_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]


Language = Literal["en", "de", "ur", "hi"]


def make(
    language: Language = "en",
    name="Bhindi masala",
    description="",
    steps=("Cook the okra.",),
    lines=("2 tbsp oil",),
):
    quote = [Evidence(source="desc", quote="x")]
    return ExtractedRecipe(
        is_recipe=True,
        name=name,
        description=description,
        language=language,
        ingredients=[
            ExtractedIngredient(line=line, original_line=line, quantity_stated=True, evidence=quote)
            for line in lines
        ],
        instructions=[ExtractedStep(text=text, evidence=quote) for text in steps],
    )


@pytest.mark.parametrize(
    ("recipe", "expected"),
    [
        (make(), []),
        (make("de", name="Gefüllte Paprika", steps=("Die Paprika füllen.",)), []),
        (make("hi", steps=("Pyaaz ko tel mein bhoonein.",)), []),
        (make("hi", name="भिंडी मसाला"), ["name contains Devanagari"]),
        (make("ur", steps=("Okra ko pakayein.", "پیاز ڈالیں")), ["step 2 contains Arabic-script"]),
        (make("hi", description="भिंडी"), ["description contains Devanagari"]),
        (make("en", name="भिंडी"), []),  # only Urdu/Hindi recipes are held to Roman letters in the text
        (make(lines=("2 tbsp oil", "1 चम्मच जीरा")), ["ingredient 2 `line` contains Devanagari"]),
        (make("de", lines=("500 g Mehl",)), []),  # German letters are Latin: not this check's business
    ],
)
def test_script_problems(recipe, expected):
    found = script_problems(recipe)
    assert len(found) == len(expected)
    for want, got in zip(expected, found, strict=True):
        assert got.startswith(want)


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def hindi_script(recipe):
    bad = copy.deepcopy(recipe)
    bad["language"] = "hi"
    bad["name"] = "भिंडी मसाला"
    return bad


def run(world: World):
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")
    return world.invoke("run")


def extract_calls(world: World):
    return [c for c in non_classify_calls(world.llm) if c.task == "extract"]


def test_a_wrong_script_is_retried_once_with_the_problem_stated_and_the_retry_uploads(world: World):
    good = load("llm_extract_okra.json")
    world.llm = recipe_llm()
    world.llm.script("extract", good, when_prompt_has="wrong script")
    world.llm.script("extract", hindi_script(good))
    world.llm._scripts.insert(0, world.llm._scripts.pop(-2))  # the retry script is tried first

    result = run(world)

    assert result.exit_code == 0, result.output
    calls = extract_calls(world)
    assert len(calls) == 2
    assert "Devanagari" in calls[1].prompt
    assert len(world.mealie.recipes) == 1


def test_a_wrong_script_after_the_retry_goes_to_review_and_nothing_is_uploaded(world: World):
    world.llm = recipe_llm()
    world.llm.script("extract", hindi_script(load("llm_extract_okra.json")))

    result = run(world)

    assert result.exit_code == 0, result.output
    assert len(extract_calls(world)) == 2
    assert not world.mealie.recipes
    assert world.store().part(ITEM_KEY) is not None
    assert "wrong script" in result.output
