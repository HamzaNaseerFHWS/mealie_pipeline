"""Ticket 28 at the pipeline seam: a sheet of names -> found pages -> recipes in FakeMealie."""

import csv
import json
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.downloader import FakeImageDownloader
from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_search import FakeWebSearch
from mealie_pipeline.adapters.fake_web import FakeWebFetcher
from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from mealie_pipeline.adapters.llm import LLMError
from mealie_pipeline.adapters.search import SearchHit
from mealie_pipeline.cli import app
from mealie_pipeline.recipe_requests import RecipeRequest, RecipeRequests
from mealie_pipeline.store import StateStore
from mealie_pipeline.url_normalizer import normalize_web
from tests.helpers import fake_adapters
from tests.images import make_jpeg
from tests.web_pages import page, recipe_json

ROOT = Path(__file__).parents[1]
TOKEN = "test-token-1234567890"
IMAGE = "https://img.example/pic.jpg"

KARAHI = "https://karahi.example/chicken-karahi"
DAL = "https://dal.example/dal-tadka"
WRAP = "https://wraps.example/veggie-wrap"

RECIPES = {
    "Chicken Karahi": (
        KARAHI,
        "Chicken Karahi",
        ["500 g chicken", "2 tbsp ghee", "3 tomatoes", "1 tsp salt"],
        ["Heat the ghee in a pan.", "Add the chicken and fry.", "Add the tomatoes and salt and simmer."],
    ),
    "Dal Tadka": (
        DAL,
        "Easy Dal Tadka (Restaurant Style)",  # the page names it differently from the sheet
        ["1 cup toor dal", "1 tbsp ghee", "1 tsp cumin seeds", "1 tsp salt"],
        ["Boil the dal with the salt.", "Heat the ghee and fry the cumin seeds.", "Pour it over the dal."],
    ),
    "Veggie Wrap": (
        WRAP,
        "Veggie Wrap",
        ["2 tortillas", "1 cup hummus", "1 cucumber", "1 tomato"],
        ["Spread the hummus on the tortillas.", "Add the cucumber and the tomato.", "Roll up the wraps."],
    ),
}
PARSES = {
    "500 g chicken": EngineParse(500, 500, "g", "chicken", "", 0.99),
    "2 tbsp ghee": EngineParse(2, 2, "tbsp", "ghee", "", 0.99),
    "3 tomatoes": EngineParse(3, 3, "", "tomatoes", "", 0.99),
    "1 tsp salt": EngineParse(1, 1, "tsp", "salt", "", 0.99),
    "1 cup toor dal": EngineParse(1, 1, "cup", "toor dal", "", 0.99),
    "1 tsp cumin seeds": EngineParse(1, 1, "tsp", "cumin seeds", "", 0.99),
    "2 tortillas": EngineParse(2, 2, "", "tortillas", "", 0.99),
    "1 cup hummus": EngineParse(1, 1, "cup", "hummus", "", 0.99),
    "1 cucumber": EngineParse(1, 1, "", "cucumber", "", 0.99),
    "1 tomato": EngineParse(1, 1, "", "tomato", "", 0.99),
}


def extraction(title: str, ingredients: list[str], steps: list[str]) -> dict:
    """What the LLM returns for a page: every ingredient and step quoted verbatim from it."""
    return {
        "is_recipe": True,
        "name": title,
        "description": "A tasty dish.",
        "language": "en",
        "servings": 4,
        "ingredients": [
            {
                "line": i,
                "original_line": i,
                "quantity_stated": True,
                "evidence": [{"source": "web", "quote": i}],
            }
            for i in ingredients
        ],
        "instructions": [{"text": s, "evidence": [{"source": "web", "quote": s}]} for s in steps],
        "tag_choices": [{"tag": "Dinner", "reason": "a main dish"}],
    }


class World:
    def __init__(self, tmp_path: Path):
        self.workspace = tmp_path
        (tmp_path / ".env").write_text(
            f"MEALIE_URL=http://fake:9000\nMEALIE_TOKEN={TOKEN}\n", encoding="utf-8"
        )
        (tmp_path / "config").mkdir()
        for name in ("recipe_sites.yaml", "site_selectors.yaml", "units.yaml"):
            shutil.copy(ROOT / "config" / name, tmp_path / "config" / name)
        self.mealie = FakeMealie(
            token=TOKEN,
            tags=["Dinner", "Vegan", "Lunch"],
            foods=["Salt"],
            units=["gram", "tablespoon", "teaspoon", "cup"],
        )
        self.llm = FakeLLM()
        self.search = FakeWebSearch()
        self.fetcher = FakeWebFetcher()
        self.images = FakeImageDownloader({IMAGE: make_jpeg(800)})
        for name, (url, title, ingredients, steps) in RECIPES.items():
            self.fetcher.pages[url] = page(
                recipe_json(title, ingredient_lines=ingredients, step_lines=steps), lang="en"
            )
            self.search.hits[name] = [SearchHit(url, title)]
            self.llm.script("extract", extraction(title, ingredients, steps), when_prompt_has=ingredients[0])

    def invoke(self, *args: str):
        adapters = fake_adapters(
            mealie=self.mealie,
            llm=self.llm,
            search=self.search,
            search_fallback=FakeWebSearch(),
            web=self.fetcher,
            images=self.images,
            engine=FakeIngredientEngine(PARSES),
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)

    def sheet(self, rows: list[list[str]], header: str = "name,url") -> None:
        path = self.workspace / "recipes.csv"
        path.write_text(header + "\n" + "\n".join(",".join(r) for r in rows) + "\n", encoding="utf-8")
        assert self.invoke("requests", "add", "--file", str(path)).exit_code == 0

    def requests(self) -> dict[str, RecipeRequest]:
        return {r.name: r for r in RecipeRequests(StateStore(self.workspace / "pipeline.db")).all()}

    def store(self) -> StateStore:
        return StateStore(self.workspace / "pipeline.db")


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def one_tomato(food: str) -> str:
    """The wrap and the karahi share one Food for tomato(es): whichever spelling was created first."""
    return "tomato" if food.startswith("tomato") else food


def recipes_by_name(world: World) -> dict[str, dict]:
    return {r["name"]: r for r in world.mealie.recipes.values()}


# (a) a 3-name sheet becomes 3 Mealie recipes -------------------------------------------------


def test_a_three_name_sheet_becomes_three_parsed_tagged_recipes(world: World):
    world.sheet([["Chicken Karahi", ""], ["Dal Tadka", ""], ["Veggie Wrap", ""]])

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    recipes = recipes_by_name(world)
    assert sorted(recipes) == ["Chicken Karahi", "Easy Dal Tadka (Restaurant Style)", "Veggie Wrap"]
    karahi = recipes["Chicken Karahi"]
    assert karahi["orgURL"] == KARAHI
    assert [t["name"] for t in karahi["tags"]] == ["Dinner"]
    foods = {f.id: f.name for f in world.mealie.foods.values()}
    units = {u.id: u.name for u in world.mealie.units.values()}
    assert [
        (i["quantity"], units.get((i["unit"] or {}).get("id", "")), one_tomato(foods[i["food"]["id"]]))
        for i in karahi["recipeIngredient"]
    ] == [(500, "gram", "chicken"), (2, "tablespoon", "ghee"), (3, None, "tomato"), (1, "teaspoon", "Salt")]
    assert len(karahi["recipeInstructions"]) == 3
    assert world.mealie.images[karahi["slug"]] == make_jpeg(800)  # the page's own image
    assert {r.status for r in world.requests().values()} == {"imported"}
    assert "3 imported" in result.output


def test_extras_carry_the_request_and_the_pages_name_wins_over_the_requested_one(world: World):
    world.sheet([["Dal Tadka", ""]])

    world.invoke("run")

    (recipe,) = world.mealie.recipes.values()
    request = world.requests()["Dal Tadka"]
    assert recipe["name"] == "Easy Dal Tadka (Restaurant Style)"
    assert recipe["extras"]["requested_name"] == "Dal Tadka"
    assert recipe["extras"]["request_row"] == "R2C1"
    assert recipe["extras"]["source"] == "web-search"
    assert recipe["extras"]["item_key"] == request.item_key and request.item_key
    assert request.item_key.startswith("web:") and request.item_key.endswith("#1")
    assert recipe["extras"]["score"] == 100.0  # the Quality Score
    assert any("Dal Tadka" in n["text"] for n in recipe["notes"])  # "Requested as ..."


def test_the_extraction_call_gets_only_the_page_and_keeps_its_wording(world: World):
    world.sheet([["Veggie Wrap", ""]])

    world.invoke("run")

    (call,) = [c for c in world.llm.calls if c.task == "extract"]
    assert "[SRC:web]" in call.prompt and "1 cup hummus" in call.prompt
    assert "[SRC:desc]" not in call.prompt  # no video, no description
    assert "Keep the website's quantities and wording" in call.prompt
    assert "Requested recipe name: Veggie Wrap" in call.prompt and "Never quote it as Evidence" in call.prompt


# (b) already in Mealie -----------------------------------------------------------------------


def test_a_page_already_in_mealie_makes_no_llm_call_and_no_write(world: World):
    slug = world.mealie.create_recipe("My old karahi")
    world.mealie.patch_recipe(slug, {"orgURL": "https://www.karahi.example/chicken-karahi/?utm_source=ig"})
    world.sheet([["Chicken Karahi", ""]])

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    request = world.requests()["Chicken Karahi"]
    assert request.status == "already_in_mealie"
    assert request.mealie_url == world.mealie.recipe_url(slug)
    assert [c for c in world.llm.calls] == []
    assert list(world.mealie.recipes) == [slug]
    assert world.mealie.recipes[slug]["name"] == "My old karahi"  # untouched
    assert world.fetcher.fetched.count(KARAHI) <= 1  # only the search's own read, no import read


# (c) a page failing the Gate goes to review --------------------------------------------------


def test_a_page_failing_the_gate_goes_to_review_and_is_not_uploaded(world: World):
    world.llm = FakeLLM()
    thin = extraction("Veggie Wrap", ["2 tortillas"], ["Roll up the wraps."])
    world.llm.script("extract", thin)
    world.sheet([["Veggie Wrap", ""]])

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}
    request = world.requests()["Veggie Wrap"]
    assert request.status == "review" and "H2" in (request.reason or "")
    item_key = request.item_key or ""
    review = (world.workspace / "review" / f"{item_key.replace(':', '_').replace('#', '_')}.md").read_text(
        encoding="utf-8"
    )
    assert WRAP in review and "[desc]" not in review and "### web" in review and "2 tortillas" in review
    assert "REVIEW" in result.output and "requests: 1 review" in result.output


# (d) re-running the sheet makes no new writes ------------------------------------------------


def test_rerunning_makes_no_new_writes_and_no_new_calls(world: World):
    world.sheet([["Chicken Karahi", ""], ["Veggie Wrap", ""]])
    world.invoke("run")
    snapshot = json.dumps(world.mealie.recipes, sort_keys=True)
    llm_calls, queries, foods = len(world.llm.calls), len(world.search.queries), len(world.mealie.foods)

    again = world.invoke("run")

    assert again.exit_code == 0, again.output
    assert json.dumps(world.mealie.recipes, sort_keys=True) == snapshot
    assert (len(world.llm.calls), len(world.search.queries), len(world.mealie.foods)) == (
        llm_calls,
        queries,
        foods,
    )
    assert {r.status for r in world.requests().values()} == {"imported"}


# (e) a row with a url column skips the search ------------------------------------------------


def test_a_row_with_a_url_skips_the_search_and_still_imports(world: World):
    world.sheet([["Chicken Karahi", KARAHI]])

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    assert world.search.queries == []
    assert world.requests()["Chicken Karahi"].status == "imported"
    (recipe,) = world.mealie.recipes.values()
    assert recipe["extras"]["source"] == "sheet-url"


# options and edge cases ----------------------------------------------------------------------


def test_dry_run_writes_the_payload_with_the_request_extras_and_touches_nothing_in_mealie(world: World):
    world.sheet([["Dal Tadka", ""]])

    result = world.invoke("run", "--dry-run")

    assert result.exit_code == 0, result.output
    assert world.mealie.recipes == {}
    files = list((world.workspace / "work" / "payloads").glob("web_*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["extras"]["requested_name"] == "Dal Tadka" and payload["orgURL"] == DAL
    assert world.invoke("run").exit_code == 0  # a real run afterwards still imports it
    assert len(world.mealie.recipes) == 1


def test_limit_applies_to_requests_too(world: World):
    world.sheet([["Chicken Karahi", ""], ["Dal Tadka", ""], ["Veggie Wrap", ""]])

    world.invoke("run", "--limit", "1")

    statuses = [r.status for r in world.requests().values()]
    assert sorted(statuses) == ["imported", "pending", "pending"]
    world.invoke("run", "--limit", "1")
    assert sorted(r.status for r in world.requests().values()) == ["imported", "imported", "pending"]


def test_stages_find_only_finds_and_does_not_import(world: World):
    world.sheet([["Chicken Karahi", ""]])

    world.invoke("run", "--stages", "find")

    assert world.requests()["Chicken Karahi"].status == "found"
    assert world.mealie.recipes == {} and world.llm.calls == []


def test_two_names_that_find_the_same_page_make_one_recipe_and_both_are_imported(world: World):
    world.search.hits["Karahi Chicken"] = world.search.hits["Chicken Karahi"]
    world.sheet([["Chicken Karahi", ""], ["Karahi Chicken", ""]])

    world.invoke("run")

    assert len(world.mealie.recipes) == 1
    requests = world.requests()
    assert requests["Chicken Karahi"].status == requests["Karahi Chicken"].status == "imported"
    assert requests["Chicken Karahi"].mealie_url == requests["Karahi Chicken"].mealie_url


def test_a_failed_import_shows_on_the_request_and_retry_imports_it(world: World):
    good = world.llm
    world.llm = FakeLLM()
    world.llm.script("extract", LLMError("claude failed: boom"))
    world.sheet([["Veggie Wrap", ""]])
    failed = world.invoke("run")
    request = world.requests()["Veggie Wrap"]
    assert failed.exit_code == 1 and request.status == "failed"
    assert "extract: claude failed: boom" in (request.last_error or "")

    world.llm = good
    assert world.invoke("retry", request.item_key or "").exit_code == 0
    fixed = world.invoke("run")

    assert fixed.exit_code == 0, fixed.output
    assert world.requests()["Veggie Wrap"].status == "imported"
    assert len(world.mealie.recipes) == 1


def test_requests_csv_has_the_final_status_link_score_and_reason(world: World):
    world.sheet([["Chicken Karahi", ""], ["Unobtainium Stew", ""]])
    world.invoke("run")

    with (world.workspace / "reports" / "requests.csv").open(encoding="utf-8-sig", newline="") as fh:
        rows = {r["name"]: r for r in csv.DictReader(fh)}

    karahi = rows["Chicken Karahi"]
    assert (karahi["status"], karahi["chosen_url"]) == ("imported", KARAHI)
    assert karahi["mealie_url"].startswith("http://fake-mealie:9000/g/home/r/")
    assert float(karahi["score"]) == 100.0 and karahi["reason"] == "imported"
    assert rows["Unobtainium Stew"]["status"] == "not_found" and rows["Unobtainium Stew"]["reason"]


def test_mp_requests_shows_the_final_counts(world: World):
    world.sheet([["Chicken Karahi", ""], ["Unobtainium Stew", ""]])
    world.invoke("run")

    out = world.invoke("requests").output

    assert "imported" in out and "not_found" in out


# URL Normalizer: `web` ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "variant",
    [
        "https://karahi.example/chicken-karahi",
        "https://www.karahi.example/chicken-karahi/",
        "http://karahi.example/chicken-karahi?utm_source=ig&utm_medium=social",
        "https://karahi.example/chicken-karahi#comments",
        "karahi.example/chicken-karahi",
        "https://m.karahi.example/chicken-karahi?fbclid=abc",
    ],
)
def test_the_same_page_with_or_without_www_slash_or_tracking_is_one_key(variant):
    base = normalize_web("https://karahi.example/chicken-karahi")

    got = normalize_web(variant)

    assert got is not None and base is not None
    assert (got.platform, got.video_id) == ("web", base.video_id)
    assert got.video_key == f"web:{base.video_id}" and len(base.video_id) == 12


def test_different_pages_and_meaningful_parameters_give_different_keys():
    a = normalize_web("https://karahi.example/recipe?id=1")
    b = normalize_web("https://karahi.example/recipe?id=2")
    c = normalize_web("https://karahi.example/other")

    assert a and b and c and len({a.video_id, b.video_id, c.video_id}) == 3


def test_the_canonical_url_keeps_the_real_host_but_drops_tracking():
    got = normalize_web("https://www.karahi.example/chicken-karahi/?utm_source=ig&page=2#top")

    assert got is not None and got.canonical_url == "https://www.karahi.example/chicken-karahi/?page=2"


@pytest.mark.parametrize("bad", ["", "not a url", "https://localhost/x", "ftp://x.example/y"])
def test_garbage_is_not_a_page(bad):
    assert normalize_web(bad) is None
