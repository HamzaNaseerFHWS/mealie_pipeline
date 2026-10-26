"""The `find` stage at the pipeline seam: `mp requests add`, then `mp run --stages find`."""

import csv
import shutil
from pathlib import Path

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.fake_search import FakeWebSearch
from mealie_pipeline.adapters.fake_web import FakeWebFetcher
from mealie_pipeline.adapters.search import SearchHit
from mealie_pipeline.cli import app
from mealie_pipeline.recipe_requests import RecipeRequest, RecipeRequests
from mealie_pipeline.store import StateStore
from tests.helpers import fake_adapters
from tests.web_pages import page, recipe_json, text_only_page

ROOT = Path(__file__).parents[1]
TOKEN = "test-token-1234567890"

KARAHI_A = "https://karahi-blog.example/chicken-karahi/"
WRAP_1 = "https://wraps-one.example/veggie-wrap"
WRAP_2 = "https://wraps-two.example/veggie-wrap"
DAL = "https://dal-blog.example/dal-tadka"
SOUP_DE = "https://suppen.example/linsensuppe"
SOUP_EN = "https://soups.example/linsensuppe"
FALLBACK_ONLY = "https://fallback.example/chicken-biryani"

PAGES = {
    KARAHI_A: page(recipe_json("Chicken Karahi"), lang=None),
    WRAP_1: page(recipe_json("Veggie Wrap"), lang="en"),
    WRAP_2: page(recipe_json("Veggie Wrap"), lang="en"),
    DAL: page(recipe_json("Dal Tadka"), lang="en"),
    SOUP_DE: page(recipe_json("Linsensuppe"), lang="de"),
    SOUP_EN: page(recipe_json("Linsensuppe"), lang="en"),
    FALLBACK_ONLY: page(recipe_json("Chicken Biryani"), lang="en"),
    "https://roundup.example/25-karahi": page(recipe_json("Karahi"), recipe_json("Biryani")),
    "https://thin.example/words": text_only_page("Ingredients: chicken. Method: cook."),
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
        self.search = FakeWebSearch()
        self.fallback = FakeWebSearch()
        self.fetcher = FakeWebFetcher(PAGES)

    def invoke(self, *args: str):
        adapters = fake_adapters(search=self.search, search_fallback=self.fallback, web=self.fetcher)
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)

    def sheet(self, rows: list[list[str]], header: str = "name,url,language,notes") -> None:
        text = header + "\n" + "\n".join(",".join(r) for r in rows) + "\n"
        path = self.workspace / "recipes.csv"
        path.write_text(text, encoding="utf-8")
        result = self.invoke("requests", "add", "--file", str(path))
        assert result.exit_code == 0, result.output

    def requests(self) -> dict[str, RecipeRequest]:
        return {r.name: r for r in RecipeRequests(StateStore(self.workspace / "pipeline.db")).all()}

    def find(self, *extra: str):
        return self.invoke("run", "--stages", "find", *extra)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def world(tmp_path) -> World:
    return World(tmp_path)


def hits(*urls_titles: tuple[str, str]) -> list[SearchHit]:
    return [SearchHit(u, t) for u, t in urls_titles]


def test_three_requests_end_found_not_found_and_needs_choice(world: World):
    world.search.hits = {
        "Chicken Karahi": hits(
            ("https://www.pinterest.com/pin/1", "Chicken Karahi"),
            ("https://www.youtube.com/watch?v=x", "Chicken Karahi video"),
            ("https://roundup.example/25-karahi", "25 Best Karahi Recipes"),
            (KARAHI_A, "Authentic Chicken Karahi Recipe"),
        ),
        "Veggie Wrap": hits((WRAP_1, "Veggie Wrap"), (WRAP_2, "Veggie Wrap")),
    }
    world.sheet(
        [["Chicken Karahi", "", "", ""], ["Veggie Wrap", "", "", ""], ["Unobtainium Stew", "", "", ""]]
    )

    result = world.find()

    assert result.exit_code == 0, result.output
    requests = world.requests()
    assert requests["Chicken Karahi"].status == "found"
    assert requests["Chicken Karahi"].chosen_url == KARAHI_A
    assert requests["Chicken Karahi"].score == pytest.approx(0.925)
    assert requests["Veggie Wrap"].status == "needs_choice"
    assert requests["Unobtainium Stew"].status == "not_found"
    assert "no pages" in (requests["Unobtainium Stew"].reason or "")
    # Pinterest, YouTube and the "25 Best" listicle were dropped without being fetched.
    assert world.fetcher.fetched == [KARAHI_A, WRAP_1, WRAP_2]
    assert "1 found, 1 need a choice, 1 not found" in result.output


def test_choices_file_and_review_page_for_the_unsure_request(world: World):
    world.search.hits = {"Veggie Wrap": hits((WRAP_1, "Veggie Wrap"), (WRAP_2, "Veggie Wrap"))}
    world.sheet([["Veggie Wrap", "", "", ""]])
    world.find()

    with (world.workspace / "reports" / "request_choices.csv").open(encoding="utf-8-sig", newline="") as fh:
        (row,) = list(csv.DictReader(fh))
    assert (row["name"], row["position"], row["choice"]) == ("Veggie Wrap", "R2C1", "")
    assert row["1_url"] == WRAP_1 and row["2_url"] == WRAP_2 and row["3_url"] == ""
    assert row["1_title"] == "Veggie Wrap" and "ingredient 1" in row["1_ingredients"]
    review = (world.workspace / "review" / "request-R2C1.md").read_text(encoding="utf-8")
    assert WRAP_1 in review and WRAP_2 in review and "choice" in review


def write_choice(world: World, value: str) -> None:
    path = world.workspace / "reports" / "request_choices.csv"
    with path.open(encoding="utf-8-sig", newline="") as fh:
        rows = list(csv.DictReader(fh))
        fields = list(rows[0])
    rows[0]["choice"] = value
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.parametrize(
    ("choice", "status", "url"),
    [
        ("2", "found", WRAP_2),
        ("1", "found", WRAP_1),
        (" 2 ", "found", WRAP_2),
        ("https://my.example/the-one", "found", "https://my.example/the-one"),
        ("skip", "not_found", None),
        ("SKIP", "not_found", None),
    ],
)
def test_the_users_choice_wins_on_the_next_run(world: World, choice, status, url):
    world.search.hits = {"Veggie Wrap": hits((WRAP_1, "Veggie Wrap"), (WRAP_2, "Veggie Wrap"))}
    world.sheet([["Veggie Wrap", "", "", ""]])
    world.find()
    write_choice(world, choice)
    queries = len(world.search.queries)

    result = world.find()

    assert result.exit_code == 0, result.output
    request = world.requests()["Veggie Wrap"]
    assert (request.status, request.chosen_url) == (status, url)
    assert len(world.search.queries) == queries  # applying a choice never searches again
    assert not (world.workspace / "reports" / "request_choices.csv").exists()  # nothing left to choose
    assert not list((world.workspace / "review").glob("request-*.md"))


def test_a_choice_that_is_not_understood_is_reported_and_the_request_keeps_waiting(world: World):
    world.search.hits = {"Veggie Wrap": hits((WRAP_1, "Veggie Wrap"), (WRAP_2, "Veggie Wrap"))}
    world.sheet([["Veggie Wrap", "", "", ""]])
    world.find()
    write_choice(world, "maybe")

    result = world.find()

    assert "not understood" in result.output
    assert world.requests()["Veggie Wrap"].status == "needs_choice"
    assert (world.workspace / "reports" / "request_choices.csv").exists()


def test_a_request_with_a_url_skips_the_search_and_is_checked_to_be_a_recipe_page(world: World):
    world.sheet([["Dal Tadka", DAL, "", ""], ["Thin Page", "https://thin.example/words", "", ""]])

    result = world.find()

    assert result.exit_code == 0, result.output
    requests = world.requests()
    assert (requests["Dal Tadka"].status, requests["Dal Tadka"].chosen_url) == ("found", DAL)
    assert requests["Thin Page"].status == "not_found"
    assert "not a single recipe page" in (requests["Thin Page"].reason or "")
    assert world.search.queries == [] and world.fallback.queries == []


def test_the_german_name_is_searched_in_german_and_the_german_page_wins(world: World):
    world.search.hits = {"Linsensuppe": hits((SOUP_EN, "Linsensuppe"), (SOUP_DE, "Linsensuppe"))}
    world.sheet([["Linsensuppe", "", "", ""]])

    world.find()

    assert world.search.queries == [("Linsensuppe Rezept", "de")]
    request = world.requests()["Linsensuppe"]
    assert (request.status, request.chosen_url) == ("found", SOUP_DE)


def test_the_sheets_language_and_notes_steer_the_query(world: World):
    world.sheet([["Rajma", "", "hi", "vegetarian punjabi"]])

    world.find()

    assert world.search.queries == [("Rajma recipe vegetarian punjabi", "hi")]


# -- fallback order ---------------------------------------------------------------------------


def test_a_ddgs_error_triggers_the_claude_fallback_for_that_name_only(world: World):
    world.search.fail = "ddgs: Ratelimit"
    world.fallback.hits = {"Chicken Biryani": hits((FALLBACK_ONLY, "Chicken Biryani"))}
    world.sheet([["Chicken Biryani", "", "", ""]])

    result = world.find()

    assert result.exit_code == 0, result.output
    assert world.requests()["Chicken Biryani"].chosen_url == FALLBACK_ONLY
    assert [q for q, _ in world.fallback.queries] == ["Chicken Biryani recipe"]
    assert "1 with the Claude fallback" in result.output


def test_no_valid_candidate_from_ddgs_triggers_the_fallback(world: World):
    world.search.hits = {"Chicken Biryani": hits(("https://roundup.example/25-karahi", "Biryani ideas"))}
    world.fallback.hits = {"Chicken Biryani": hits((FALLBACK_ONLY, "Chicken Biryani"))}
    world.sheet([["Chicken Biryani", "", "", ""]])

    world.find()

    assert world.requests()["Chicken Biryani"].chosen_url == FALLBACK_ONLY
    assert len(world.fallback.queries) == 1


def test_the_fallback_is_not_used_when_ddgs_already_found_a_page(world: World):
    world.search.hits = {"Chicken Karahi": hits((KARAHI_A, "Chicken Karahi"))}
    world.sheet([["Chicken Karahi", "", "", ""]])

    world.find()

    assert world.fallback.queries == []


def test_both_sources_finding_nothing_gives_not_found_with_the_reasons(world: World):
    world.search.hits = {"Soup": hits(("https://thin.example/words", "Soup"))}
    world.sheet([["Soup", "", "", ""]])

    result = world.find()

    request = world.requests()["Soup"]
    assert result.exit_code == 0 and request.status == "not_found"
    assert "thin.example/words: not a single recipe page" in (request.reason or "")
    assert len(world.fallback.queries) == 1


def test_an_outage_of_both_sources_leaves_every_request_pending_and_says_so(world: World):
    world.search.fail = "ddgs: Ratelimit"
    world.fallback.fail = "claude WebSearch: boom"
    world.sheet([["Chicken Karahi", "", "", ""], ["Veggie Wrap", "", "", ""]])

    result = world.find()

    assert result.exit_code == 1
    assert "Every search source failed" in result.output and "stay pending" in result.output
    assert {r.status for r in world.requests().values()} == {"pending"}
    assert len(world.search.queries) == 1  # it stopped at the first request instead of failing them all


def test_a_failing_fallback_after_a_healthy_empty_search_is_just_not_found(world: World):
    world.fallback.fail = "claude WebSearch: boom"
    world.sheet([["Unobtainium Stew", "", "", ""]])

    result = world.find()

    assert result.exit_code == 0
    request = world.requests()["Unobtainium Stew"]
    assert request.status == "not_found" and "fallback search unavailable" in (request.reason or "")


# -- running it again, limits --------------------------------------------------------------------


def test_rerunning_does_not_search_again_and_retry_puts_a_request_back(world: World):
    world.search.hits = {"Chicken Karahi": hits((KARAHI_A, "Chicken Karahi"))}
    world.sheet([["Chicken Karahi", "", "", ""]])
    world.find()
    world.find()
    assert len(world.search.queries) == 1

    world.invoke("requests", "retry", "Chicken Karahi")
    world.find()

    assert len(world.search.queries) == 2


def test_limit_caps_how_many_requests_are_searched(world: World):
    world.sheet([["A Soup", "", "", ""], ["B Soup", "", "", ""], ["C Soup", "", "", ""]])

    world.find("--limit", "2")

    assert [r.status for r in world.requests().values()] == ["not_found", "not_found", "pending"]


def test_requests_csv_shows_the_result_after_find(world: World):
    world.search.hits = {"Chicken Karahi": hits((KARAHI_A, "Chicken Karahi"))}
    world.sheet([["Chicken Karahi", "", "", ""]])
    world.find()

    with (world.workspace / "reports" / "requests.csv").open(encoding="utf-8-sig", newline="") as fh:
        (row,) = list(csv.DictReader(fh))

    assert (row["status"], row["chosen_url"]) == ("found", KARAHI_A)
    assert float(row["score"]) == pytest.approx(0.925)


def test_unknown_stage_lists_find_among_the_stages(world: World):
    result = world.invoke("run", "--stages", "bake")

    assert result.exit_code == 2 and "find" in result.output


def test_find_never_touches_mealie_or_the_llm(world: World):
    world.search.hits = {"Chicken Karahi": hits((KARAHI_A, "Chicken Karahi"))}
    world.sheet([["Chicken Karahi", "", "", ""]])

    adapters = fake_adapters(search=world.search, search_fallback=world.fallback, web=world.fetcher)
    result = CliRunner().invoke(
        app, ["--workspace", str(world.workspace), "run", "--stages", "find"], obj=adapters
    )

    assert result.exit_code == 0
    assert adapters.llm.calls == [] and adapters.mealie.recipes == {} and adapters.mealie.foods == {}  # type: ignore[attr-defined]
