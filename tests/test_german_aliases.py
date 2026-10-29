"""Ticket 30: the source's own food names become aliases of the English Foods."""

import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_search import FakeWebSearch
from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from mealie_pipeline.adapters.search import SearchHit
from mealie_pipeline.cli import app
from tests.helpers import fake_adapters
from tests.test_request_import_seam import World
from tests.web_pages import page, recipe_json

PASTA = "https://pasta.example/nudelpfanne"
SOUP = "https://suppe.example/zwiebelsuppe"

# English line, the source's line, the source's food name
PASTA_INGREDIENTS = [
    ("500 g shell pasta", "500 g Muschelnudeln", "Muschelnudeln"),
    ("1 onion", "1 Zwiebel", "Zwiebel"),
    ("2 tbsp tomato paste", "2 EL Tomatenmark", "Tomatenmark"),
    ("1 tsp salt", "1 TL Salz", "Salz"),
]
PASTA_STEPS = [
    "Die Muschelnudeln kochen.",
    "Zwiebel und Tomatenmark anbraten.",
    "Mit Salz würzen und servieren.",
]
# the model translated "Zwiebel" as shallot here; the alias made earlier must still win
SOUP_INGREDIENTS = [
    ("1 shallot", "1 Zwiebel", "Zwiebel"),
    ("500 ml stock", "500 ml Brühe", "Brühe"),
    ("2 tbsp butter", "2 EL Butter", "Butter"),
    ("1 tsp salt", "1 TL Salz", "Salz"),
]
SOUP_STEPS = ["Zwiebel in Butter andünsten.", "Mit Brühe aufgießen.", "Mit Salz abschmecken."]

PARSES = {
    "500 g shell pasta": EngineParse(500, 500, "g", "shell pasta", "", 0.99),
    "1 onion": EngineParse(1, 1, "", "onion", "", 0.99),
    "2 tbsp tomato paste": EngineParse(2, 2, "tbsp", "tomato paste", "", 0.99),
    "1 tsp salt": EngineParse(1, 1, "tsp", "salt", "", 0.99),
    "1 shallot": EngineParse(1, 1, "", "shallot", "", 0.99),
    "500 ml stock": EngineParse(500, 500, "", "stock", "", 0.99),
    "2 tbsp butter": EngineParse(2, 2, "tbsp", "butter", "", 0.99),
}


class CountingMealie(FakeMealie):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.alias_calls: list[tuple[str, str]] = []

    def add_food_alias(self, food_id: str, alias: str):
        self.alias_calls.append((self.foods[food_id].name, alias))
        return super().add_food_alias(food_id, alias)


def german_extraction(title: str, rows: list[tuple[str, str, str]], steps: list[str]) -> dict:
    return {
        "is_recipe": True,
        "name": title,
        "description": "Ein einfaches Gericht.",
        "language": "de",
        "servings": 4,
        "ingredients": [
            {
                "line": line,
                "original_line": original,
                "food_original": food,
                "quantity_stated": True,
                "evidence": [{"source": "web", "quote": original}],
            }
            for line, original, food in rows
        ],
        "instructions": [{"text": s, "evidence": [{"source": "web", "quote": s}]} for s in steps],
        "tag_choices": [{"tag": "Dinner", "reason": "ein Hauptgericht"}],
    }


class GermanWorld(World):
    def __init__(self, tmp_path: Path):
        super().__init__(tmp_path)
        self.mealie = CountingMealie(
            token="test-token-1234567890",
            tags=["Dinner", "Vegan", "Lunch"],
            foods=["Salt", "onion"],
            units=["gram", "tablespoon", "teaspoon", "milliliter"],
        )
        for name, url, title, rows, steps in (
            ("Nudelpfanne", PASTA, "Nudelpfanne", PASTA_INGREDIENTS, PASTA_STEPS),
            ("Zwiebelsuppe", SOUP, "Zwiebelsuppe", SOUP_INGREDIENTS, SOUP_STEPS),
        ):
            self.fetcher.pages[url] = page(
                recipe_json(title, ingredient_lines=[r[1] for r in rows], step_lines=steps), lang="de"
            )
            self.search.hits[name] = [SearchHit(url, title)]
            self.llm.script("extract", german_extraction(title, rows, steps), when_prompt_has=rows[0][1])

    def invoke(self, *args: str):
        adapters = fake_adapters(
            mealie=self.mealie,
            llm=self.llm,
            search=self.search,
            search_fallback=FakeWebSearch(),
            web=self.fetcher,
            images=self.images,
            engine=FakeIngredientEngine({**PARSES, **self.engine_parses}),
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)

    engine_parses: dict = {}


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path) -> GermanWorld:
    return GermanWorld(tmp_path)


def aliases(world: GermanWorld) -> dict[str, list[str]]:
    return {f.name: f.aliases for f in world.mealie.foods.values() if f.aliases}


def test_a_german_recipe_teaches_the_english_foods_their_german_names(world: GermanWorld):
    world.sheet([["Nudelpfanne", ""]])

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert aliases(world) == {
        "shell pasta": ["muschelnudeln"],
        "onion": ["zwiebel"],
        "tomato paste": ["tomatenmark"],
        "Salt": ["salz"],
    }
    log = (world.workspace / "reports" / "created_aliases.csv").read_text(encoding="utf-8-sig")
    rows = list(csv.reader(log.splitlines()))
    assert sorted(r[0] for r in rows[1:]) == [
        "muschelnudeln -> shell pasta",
        "salz -> Salt",
        "tomatenmark -> tomato paste",
        "zwiebel -> onion",
    ]


def test_german_steps_no_longer_pull_the_score_down_and_the_recipe_is_not_held(world: GermanWorld):
    world.sheet([["Nudelpfanne", ""]])

    world.invoke("run")

    request = world.requests()["Nudelpfanne"]
    assert request.status == "imported", request.reason
    (recipe,) = world.mealie.recipes.values()
    assert recipe["extras"]["score"] >= 80
    assert "To Review" not in [t["name"] for t in recipe["tags"]]
    assert recipe["recipeIngredient"][0]["originalText"] == "500 g Muschelnudeln"
    assert recipe["recipeInstructions"][0]["text"] == "Die Muschelnudeln kochen."


def test_a_later_recipe_links_through_the_alias_instead_of_the_models_translation(world: GermanWorld):
    world.sheet([["Nudelpfanne", ""], ["Zwiebelsuppe", ""]])

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert "shallot" not in {f.name for f in world.mealie.foods.values()}
    soup = next(r for r in world.mealie.recipes.values() if r["name"] == "Zwiebelsuppe")
    onion = next(f for f in world.mealie.foods.values() if f.name == "onion")
    assert soup["recipeIngredient"][0]["food"]["id"] == onion.id
    assert onion.aliases == ["zwiebel"]
    assert world.mealie.alias_calls.count(("onion", "zwiebel")) == 1  # learned once, not once per recipe


def test_an_english_recipe_adds_no_aliases(tmp_path: Path):
    english = GermanWorld(tmp_path)
    english.sheet([["Chicken Karahi", ""]])

    english.invoke("run")

    assert english.mealie.alias_calls == []


def test_an_ingredient_the_page_never_mentions_teaches_no_alias(world: GermanWorld):
    invented = german_extraction("Nudelpfanne", PASTA_INGREDIENTS, PASTA_STEPS)
    invented["ingredients"].append(
        {
            "line": "1 tsp pepper",
            "original_line": "1 TL Pfeffer",
            "food_original": "Pfeffer",
            "quantity_stated": True,
            "evidence": [{"source": "web", "quote": "1 TL Pfeffer"}],  # not on the page
        }
    )
    world.llm.script("extract", invented, when_prompt_has="500 g Muschelnudeln")
    world.engine_parses = {"1 tsp pepper": EngineParse(1, 1, "tsp", "pepper", "", 0.99)}
    world.sheet([["Nudelpfanne", ""]])

    world.invoke("run")

    assert "pfeffer" not in [a for names in aliases(world).values() for a in names]
    assert "pepper" not in {f.name for f in world.mealie.foods.values()}


def test_a_dry_run_writes_no_aliases(world: GermanWorld):
    world.sheet([["Nudelpfanne", ""]])

    world.invoke("run", "--dry-run")

    assert world.mealie.alias_calls == []
    assert not (world.workspace / "reports" / "created_aliases.csv").exists()
