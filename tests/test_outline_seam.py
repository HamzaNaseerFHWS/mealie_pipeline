"""Ticket 12 at the pipeline seam: a Video with three recipes becomes three independent Mealie recipes."""

from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from tests.helpers import fake_adapters, recipe_llm
from tests.images import make_jpeg
from tests.test_pipeline_seam import (
    CANONICAL,
    TOKEN,
    VIDEO_KEY,
    FlakyImageMealie,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
    load,
)

__all__ = ["clean_environment"]

DESCRIPTION = """Three chutneys!

1. Mint Chutney
1 cup mint
2 green chillies
Blend the mint until smooth.

2. Tamarind Chutney
100 g tamarind
50 g jaggery
Soak the tamarind and strain.

3. Coconut Chutney
1 coconut
2 tbsp curd
Grind the coconut with curd.
"""
STEPS = {
    "Mint": (["1 cup mint", "2 green chillies"], "Blend the mint until smooth."),
    "Tamarind": (["100 g tamarind", "50 g jaggery"], "Soak the tamarind and strain."),
    "Coconut": (["1 coconut", "2 tbsp curd"], "Grind the coconut with curd."),
}
ENGINE = FakeIngredientEngine(
    {
        "1 cup mint": EngineParse(1, 1, "cups", "mint", "", 0.99),
        "100 g tamarind": EngineParse(100, 100, "g", "tamarind", "", 0.99),
        "1 coconut": EngineParse(1, 1, "", "coconut", "", 0.99),
        "2 green chillies": EngineParse(2, 2, "", "green chillies", "", 0.99),
        "50 g jaggery": EngineParse(50, 50, "g", "jaggery", "", 0.99),
        "2 tbsp curd": EngineParse(2, 2, "tbsps", "curd", "", 0.99),
    }
)


def extraction(name: str, quote_from: str | None = None) -> dict:
    """An extraction of one chutney; `quote_from` makes its ingredient quote another chutney's text."""
    ingredients, step = STEPS[name]
    cited = STEPS[quote_from][0][0] if quote_from else ingredients[0]
    return {
        "is_recipe": True,
        "name": f"{name} Chutney",
        "language": "en",
        "servings": 4,
        "total_minutes": 10,
        "ingredients": [
            {
                "line": line,
                "original_line": line,
                "quantity_stated": True,
                "evidence": [{"source": "desc", "quote": cited if index == 0 else line}],
            }
            for index, line in enumerate(ingredients)
        ],
        "instructions": [{"text": step, "evidence": [{"source": "desc", "quote": step}]}],
        "tag_choices": [{"tag": "Dinner", "reason": "x"}],
    }


class ChutneyWorld(World):
    def invoke(self, *args: str, input: str | None = None):
        from typer.testing import CliRunner

        from mealie_pipeline.cli import app

        adapters = fake_adapters(
            mealie=self.mealie, llm=self.llm, videos=self.videos, images=self.images, engine=ENGINE
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters, input=input)


def make_world(tmp_path, *, mint_for_tamarind: bool) -> ChutneyWorld:
    world = ChutneyWorld(tmp_path)
    world.mealie = FlakyImageMealie(
        token=TOKEN, tags=["Dinner"], foods=[], units=["gram", "cup", "tablespoon"]
    )
    info = load("youtube_info_okra.json")
    info["description"] = DESCRIPTION
    info["chapters"] = [
        {"title": "Mint", "start_time": 0, "end_time": 100},
        {"title": "Tamarind", "start_time": 100, "end_time": 300},
        {"title": "Coconut", "start_time": 300, "end_time": 412},
    ]
    world.videos.infos[CANONICAL] = info
    world.videos.frame_image = make_jpeg(640)
    world.llm = recipe_llm()
    world.llm.script(
        "outline",
        {
            "language": "en",
            "parts": [
                {"title": "Mint Chutney", "start_s": 0, "end_s": 100},
                {"title": "Tamarind Chutney", "start_s": 100, "end_s": 300},
                {"title": "Coconut Chutney", "start_s": 300, "end_s": 412},
            ],
        },
    )
    world.llm.script("extract", extraction("Mint"), when_prompt_has="recipe 1 of 3")
    bad = extraction("Tamarind", "Mint" if mint_for_tamarind else None)
    world.llm.script("extract", bad, when_prompt_has="recipe 2 of 3")
    world.llm.script("extract", extraction("Coconut"), when_prompt_has="recipe 3 of 3")
    return world


def test_one_failing_part_does_not_block_its_siblings(tmp_path):
    world = make_world(tmp_path, mint_for_tamarind=True)  # part 2 quotes part 1's text
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")

    world.invoke("run")

    recipes = {r["name"]: r for r in world.mealie.recipes.values()}
    assert sorted(recipes) == ["Coconut Chutney", "Mint Chutney"]
    store = world.store()
    assert store.stage_status("part", f"{VIDEO_KEY}#2", "upload") != "done"
    assert [store.stage_status("part", f"{VIDEO_KEY}#{n}", "upload") for n in (1, 3)] == ["done", "done"]
    assert recipes["Coconut Chutney"]["orgURL"] == f"{CANONICAL}&t=300s"
    assert (recipes["Mint Chutney"]["extras"]["part"], recipes["Mint Chutney"]["extras"]["of"]) == (1, 3)
    assert "Tamarind Chutney" in recipes["Mint Chutney"]["notes"][-1]["text"]
    assert world.videos.frame_calls == [(CANONICAL, 0), (CANONICAL, 300)]
    assert (
        "1/3 uploaded" not in world.invoke("status").output
        and "2/3 uploaded" in world.invoke("status").output
    )


def test_the_sibling_notes_link_to_each_other_once_every_part_is_uploaded(tmp_path):
    world = make_world(tmp_path, mint_for_tamarind=False)
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    recipes = {r["name"]: r for r in world.mealie.recipes.values()}
    assert len(recipes) == 3
    text = recipes["Mint Chutney"]["notes"][-1]["text"]
    assert f"[Tamarind Chutney]({world.mealie.recipe_url(recipes['Tamarind Chutney']['slug'])})" in text
    assert "3/3 uploaded" in world.invoke("status").output


def test_rerunning_the_outline_after_upload_keeps_the_parts(tmp_path):
    world = make_world(tmp_path, mint_for_tamarind=False)
    world.invoke("add", "https://youtu.be/de1ppj9L4Hk")
    world.invoke("run")

    world.invoke("reset", "outline")
    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 3
    assert len(world.store().video_parts(VIDEO_KEY)) == 3
