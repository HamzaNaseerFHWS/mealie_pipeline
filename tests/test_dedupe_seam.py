"""Ticket 18 at the pipeline seam: one Mealie recipe per dish across platforms and earlier imports."""

import copy
import csv
import json

import pytest

from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from tests.helpers import fake_adapters, non_classify_calls
from tests.test_pipeline_seam import ENGINE, World, load
from tests.test_pipeline_seam import clean_environment as clean_environment  # noqa: F401

IG_URL = "https://www.instagram.com/reel/CxOkra12345/"
IG_CANONICAL = "https://www.instagram.com/p/CxOkra12345/"
IG_KEY = "instagram:CxOkra12345"
FB_URL = "https://www.facebook.com/reel/111122223333"
FB_CANONICAL = "https://www.facebook.com/watch/?v=111122223333"
FB_KEY = "facebook:111122223333"

DAL_ENGINE = FakeIngredientEngine(
    {
        "1 cup lentils": EngineParse(1, 1, "cup", "lentils", "", 0.99),
        "2 tbsp ghee": EngineParse(2, 2, "tbsps", "ghee", "", 0.99),
        "1 tsp turmeric": EngineParse(1, 1, "tsps", "turmeric", "", 0.99),
        "salt, to taste": EngineParse(None, None, "", "salt", "to taste", 0.99),
    }
)
DAL_DESCRIPTION = (
    "Comforting dal.\n\nINGREDIENTS\n1 cup lentils\n2 tbsp ghee\n1 tsp turmeric\nSalt, to taste\n"
)


def info(video_id: str, url: str, **extra):
    base = copy.deepcopy(load("youtube_info_okra.json"))
    base.update(id=video_id, webpage_url=url, uploader_id="", channel="yourfoodlab", **extra)
    return base


class DedupeWorld(World):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.videos.infos[IG_CANONICAL] = info("CxOkra12345", IG_CANONICAL)
        self.videos.infos[FB_CANONICAL] = info(
            "111122223333",
            FB_CANONICAL,
            uploader="Your Food Lab",
            upload_date="20240303",
            description="Chatpata Bhindi Aloo. Full recipe in the comments!",  # no ingredient list
        )
        self.engine = ENGINE

    def invoke(self, *args: str, input: str | None = None):
        from typer.testing import CliRunner

        from mealie_pipeline.cli import app

        adapters = fake_adapters(
            mealie=self.mealie, llm=self.llm, videos=self.videos, images=self.images, engine=self.engine
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters, input=input)

    def add_both(self) -> None:
        """What the Instagram and Facebook collectors do: `mp add` only knows YouTube."""
        store = self.store()
        store.add_video(IG_KEY, "instagram", "CxOkra12345", IG_URL, IG_CANONICAL)
        store.add_video(FB_KEY, "facebook", "111122223333", FB_URL, FB_CANONICAL)
        store.close()

    def csv_rows(self, name: str) -> list[dict[str, str]]:
        with (self.workspace / "reports" / name).open(encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))


@pytest.fixture
def world(tmp_path) -> DedupeWorld:
    return DedupeWorld(tmp_path)


def old_import(world: DedupeWorld, org_url: str) -> str:
    slug = world.mealie.create_recipe("Bhindi (old import)")
    world.mealie.patch_recipe(
        slug,
        {"orgURL": org_url, "recipeIngredient": [{"quantity": 0, "note": "okra"}], "rating": 4},
    )
    return slug


def test_a_reel_and_its_copy_become_one_recipe_with_also_on(world: DedupeWorld):
    world.add_both()

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(non_classify_calls(world.llm)) == 1  # the copy costs no extraction
    (recipe,) = world.mealie.recipes.values()
    assert recipe["orgURL"] == IG_CANONICAL and recipe["extras"]["video_key"] == IG_KEY
    assert recipe["extras"]["also_on"] == [FB_CANONICAL]
    assert any(FB_CANONICAL in n["text"] for n in recipe["notes"])
    assert f"duplicate {FB_KEY}: also on {IG_KEY}" in result.output
    rows = {r["video_key"]: r for r in world.csv_rows("dedupe.csv")}
    assert rows[IG_KEY]["role"] == "canonical" and rows[FB_KEY]["role"] == "also_on"
    assert rows[FB_KEY]["canonical_key"] == IG_KEY and rows[FB_KEY]["override"] == ""
    report = {r["video_url"]: r for r in world.csv_rows("report.csv")} if world.invoke("report") else {}
    assert report[IG_CANONICAL]["also_on"] == FB_CANONICAL
    assert report[FB_CANONICAL]["dedupe_status"] == "skipped" and report[FB_CANONICAL]["extract_status"] == ""


def test_the_reel_already_in_mealie_resolves_the_whole_group_to_that_recipe(world: DedupeWorld):
    slug = old_import(world, IG_CANONICAL)
    before = json.dumps(world.mealie.recipes, sort_keys=True)
    world.add_both()

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert non_classify_calls(world.llm) == []  # neither Video costs an AI call
    assert json.dumps(world.mealie.recipes, sort_keys=True) == before  # and nothing is written
    assert world.images.requests == []
    world.invoke("report")
    by_url = {r["video_url"]: r for r in world.csv_rows("report.csv")}
    assert by_url[IG_CANONICAL]["linkcheck_status"] == "already_in_mealie"
    assert by_url[IG_CANONICAL]["mealie_url"].endswith(f"/g/home/r/{slug}")
    assert by_url[IG_CANONICAL]["also_on"] == FB_CANONICAL  # the copy is recorded as also_on of it
    assert by_url[FB_CANONICAL]["dedupe_status"] == "skipped"
    assert by_url[FB_CANONICAL]["linkcheck_status"] == ""


def test_upgrade_existing_adds_also_on_to_the_old_recipe(world: DedupeWorld):
    slug = old_import(world, IG_CANONICAL)
    world.add_both()

    result = world.invoke("run", "--upgrade-existing")

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes[slug]["extras"]["also_on"] == [FB_CANONICAL]


def test_the_user_splits_a_group_in_the_csv_and_both_videos_proceed(world: DedupeWorld):
    world.videos.infos[FB_CANONICAL]["description"] = load("youtube_info_okra.json")["description"]
    world.add_both()
    world.invoke("run", "--stages", "metadata,classify,dedupe")
    path = world.workspace / "reports" / "dedupe.csv"
    rows = world.csv_rows("dedupe.csv")
    assert {r["video_key"] for r in rows} == {IG_KEY, FB_KEY}
    for row in rows:
        row["override"] = "split" if row["video_key"] == FB_KEY else ""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 2
    assert {r["extras"]["video_key"] for r in world.mealie.recipes.values()} == {IG_KEY, FB_KEY}
    assert all("also_on" not in r["extras"] for r in world.mealie.recipes.values())
    assert world.store().stage_status("video", FB_KEY, "dedupe") == "done"


def test_a_sibling_that_went_on_anyway_is_split_again_when_the_foods_differ(world: DedupeWorld):
    world.videos.infos[FB_CANONICAL] = info(
        "111122223333",
        FB_CANONICAL,
        uploader="Your Food Lab",
        upload_date="20240303",
        description=DAL_DESCRIPTION,
    )
    dal = copy.deepcopy(load("llm_extract_okra.json"))
    dal["ingredients"] = [
        {"line": line, "original_line": line, "quantity_stated": "salt" not in line,
         "evidence": [{"source": "desc", "quote": line.capitalize() if "salt" in line else line}]}
        for line in ("1 cup lentils", "2 tbsp ghee", "1 tsp turmeric", "salt, to taste")
    ]  # fmt: skip
    world.llm.script("extract", dal, when_prompt_has="Comforting dal")
    world.llm._scripts.insert(0, world.llm._scripts.pop())  # the first matching script wins
    world.engine = FakeIngredientEngine({**ENGINE.parses, **DAL_ENGINE.parses})
    world.add_both()
    # Both are extracted before `dedupe` ever ran, so both "went on anyway".
    world.invoke("run", "--stages", "metadata,classify,linkcheck,scrape,extract")

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    store = world.store()
    # Equal Sources: the lowest Video Key (Facebook) is the canonical one, Instagram the sibling.
    assert (store.stage_detail("video", IG_KEY, "dedupe") or "").startswith("split after parsing")
    assert f"{IG_KEY}: not the same dish as {FB_KEY}" in result.output
    assert all("also_on" not in r["extras"] for r in world.mealie.recipes.values())  # the group fell apart
