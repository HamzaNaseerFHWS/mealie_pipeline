"""Ticket 29: `--workers` for the slow stages (find, scrape, extract)."""

import subprocess
import threading
import time
from pathlib import Path

import pytest

from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.adapters.fake_mealie import FakeMealie
from mealie_pipeline.adapters.fake_search import FakeWebSearch
from mealie_pipeline.adapters.ingredient_engine import EngineParse, FakeIngredientEngine
from mealie_pipeline.adapters.llm import ClaudeCliBackend, LLMError, UsageLimited
from mealie_pipeline.adapters.search import DdgsSearch, SearchHit
from mealie_pipeline.adapters.web import HttpxWebFetcher
from mealie_pipeline.cli import app
from mealie_pipeline.pipeline import Pipeline
from mealie_pipeline.recipe_requests import RecipeRequests
from mealie_pipeline.settings import load_settings
from mealie_pipeline.store import StateStore
from tests.helpers import fake_adapters
from tests.test_request_import_seam import PARSES, World, extraction
from tests.web_pages import page, recipe_json

DISHES = 12


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "OPENAI_API_KEY", "OPENAI_MAX_USD", "RUN__WORKERS"):
        monkeypatch.delenv(name, raising=False)


# -- the State Store claim --------------------------------------------------------------------


def test_every_item_is_claimed_exactly_once_by_competing_threads(tmp_path: Path):
    store = StateStore(tmp_path / "pipeline.db")
    keys = [f"web:{n}#1" for n in range(20)]
    won: list[str] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        barrier.wait()
        for key in keys:  # every thread tries every key
            if store.claim("part", key, "extract"):
                won.append(key)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(won) == sorted(keys)
    assert store.stage_status("part", keys[0], "extract") == "running"


def test_a_claim_is_refused_for_done_failed_and_fresh_running_items(tmp_path: Path):
    store = StateStore(tmp_path / "pipeline.db")
    store.record("part", "done", "extract", "done")
    store.record("part", "failed", "extract", "failed", "boom")
    store.record("part", "busy", "extract", "running")
    store.record("part", "waiting", "extract", "pending")

    assert store.claim("part", "done", "extract") is False
    assert store.claim("part", "failed", "extract") is False
    assert store.claim("part", "busy", "extract") is False
    assert store.claim("part", "waiting", "extract") is True
    assert store.claim("part", "new", "extract") is True


def test_only_a_stale_running_claim_is_taken_over(tmp_path: Path):
    store = StateStore(tmp_path / "pipeline.db")
    store.record("part", "old", "extract", "running")
    store.record("part", "fresh", "extract", "running")
    store.db.execute(
        "UPDATE stage_records SET updated_at = datetime('now', '-40 minutes') WHERE entity_key = 'old'"
    )
    store.db.commit()

    assert store.claim("part", "fresh", "extract", stale_minutes=30) is False
    assert store.claim("part", "old", "extract", stale_minutes=30) is True


# -- shared politeness ------------------------------------------------------------------------


def test_workers_share_the_per_domain_gap_of_the_fetcher(tmp_path: Path):
    sleeps: list[float] = []
    fetcher = HttpxWebFetcher(
        tmp_path / "cache", min_delay_seconds=2.0, clock=lambda: 100.0, sleep=sleeps.append
    )

    threads = [threading.Thread(target=fetcher._wait_turn, args=("site.example",)) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(sleeps) == [2.0, 4.0, 6.0]  # the first goes at once, the rest queue 2 s apart


def test_workers_share_the_search_gap_of_ddgs():
    now = [100.0]
    calls: list[float] = []
    lock = threading.Lock()

    class Client:
        def text(self, query, region, max_results):
            calls.append(now[0])
            return [{"href": "https://x.example/r", "title": query, "body": ""}]

    def sleep(seconds: float) -> None:
        with lock:
            now[0] += seconds

    search = DdgsSearch(client=Client(), min_delay_seconds=3.0, clock=lambda: now[0], sleep=sleep)

    threads = [threading.Thread(target=search.search, args=(f"q{n}",)) for n in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    gaps = [b - a for a, b in zip(calls, calls[1:], strict=False)]
    assert len(calls) == 4 and all(gap >= 3.0 for gap in gaps)


def test_claude_calls_never_exceed_the_slot_limit(monkeypatch, tmp_path: Path):
    running = peak = 0
    lock = threading.Lock()

    def fake_run(args, **kwargs):
        nonlocal running, peak
        with lock:
            running += 1
            peak = max(peak, running)
        time.sleep(0.05)
        with lock:
            running -= 1
        return subprocess.CompletedProcess(
            args, 0, b'{"is_error": false, "structured_output": {"ok": true}}', b""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    backend = ClaudeCliBackend(tmp_path, executable="claude-fake", slots=threading.BoundedSemaphore(2))

    threads = [
        threading.Thread(target=backend.complete, args=("extract", "p", {}, "strong")) for _ in range(6)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert peak == 2


# -- the pipeline seam ------------------------------------------------------------------------


class TrackingLLM(FakeLLM):
    """Remembers which threads called it and how many calls overlapped."""

    def __init__(self, scripted: FakeLLM):
        super().__init__()
        self._scripts = scripted._scripts
        self.threads: set[int] = set()
        self.running = self.peak = 0
        self._lock = threading.Lock()

    def complete(self, task, prompt, schema, tier, images=()):
        with self._lock:
            self.threads.add(threading.get_ident())
            self.running += 1
            self.peak = max(self.peak, self.running)
        try:
            time.sleep(0.03)  # long enough for the workers to overlap
            return super().complete(task, prompt, schema, tier, images)
        finally:
            with self._lock:
                self.running -= 1


class SerialMealie(FakeMealie):
    """Fails the test's assertion when two Mealie writes overlap."""

    def __init__(self, **kwargs):
        self._busy = threading.Lock()  # before super().__init__: it creates the first foods
        self.overlaps = 0
        super().__init__(**kwargs)

    def _exclusive(self):
        if not self._busy.acquire(blocking=False):
            self.overlaps += 1
            self._busy.acquire()
        time.sleep(0.005)

    def create_recipe(self, name):
        self._exclusive()
        try:
            return super().create_recipe(name)
        finally:
            self._busy.release()

    def patch_recipe(self, slug, payload):
        self._exclusive()
        try:
            return super().patch_recipe(slug, payload)
        finally:
            self._busy.release()

    def create_food(self, name, plural_name=None):
        self._exclusive()
        try:
            return super().create_food(name, plural_name)
        finally:
            self._busy.release()


class BigWorld(World):
    """A sheet of DISHES names, each with its own page, search hit and scripted extraction."""

    def __init__(self, tmp_path: Path):
        tmp_path.mkdir(parents=True, exist_ok=True)
        super().__init__(tmp_path)
        self.parses = dict(PARSES)
        self.names = []
        for n in range(DISHES):
            item = "item" + chr(ord("a") + n)  # unique stems: a needle must not match another dish
            name, url = f"Dish {n:02d}", f"https://dish{n}.example/recipe"
            ingredients = [f"{n + 1} g {item}", "2 tbsp ghee", "3 tomatoes", "1 tsp salt"]
            steps = [
                f"Heat the ghee and fry the {item}.",
                "Add the tomatoes and simmer.",
                "Season with salt and serve.",
            ]
            self.parses[ingredients[0]] = EngineParse(n + 1, n + 1, "g", item, "", 0.99)
            self.fetcher.pages[url] = page(
                recipe_json(name, ingredient_lines=ingredients, step_lines=steps), lang="en"
            )
            self.search.hits[name] = [SearchHit(url, name)]
            self.llm.script("extract", extraction(name, ingredients, steps), when_prompt_has=ingredients[0])
            self.names.append(name)
        self.fallback = FakeWebSearch()
        self.llm = TrackingLLM(self.llm)
        self.mealie = SerialMealie(
            token="test-token-1234567890",
            tags=["Dinner", "Vegan", "Lunch"],
            foods=["Salt"],
            units=["gram", "tablespoon", "teaspoon", "cup"],
        )

    def invoke(self, *args: str):
        from typer.testing import CliRunner

        adapters = fake_adapters(
            mealie=self.mealie,
            llm=self.llm,
            search=self.search,
            search_fallback=self.fallback,
            web=self.fetcher,
            images=self.images,
            engine=FakeIngredientEngine(self.parses),
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)

    def load_sheet(self) -> None:
        self.sheet([[name, ""] for name in self.names])

    def outcome(self) -> dict:
        requests = {r.name: (r.status, r.chosen_url) for r in self.requests().values()}
        recipes = {
            r["name"]: (r["orgURL"], [t["name"] for t in r["tags"]], len(r["recipeIngredient"]))
            for r in self.mealie.recipes.values()
        }
        return {"requests": requests, "recipes": recipes}


def test_four_workers_give_the_same_result_as_one(tmp_path: Path):
    serial = BigWorld(tmp_path / "s")
    parallel = BigWorld(tmp_path / "p")
    for world, workers in ((serial, "1"), (parallel, "4")):
        world.load_sheet()
        result = world.invoke("run", "--workers", workers)
        assert result.exit_code == 0, result.output

    assert parallel.outcome() == serial.outcome()
    assert {status for status, _ in parallel.outcome()["requests"].values()} == {"imported"}
    assert len(parallel.outcome()["recipes"]) == DISHES
    assert len(parallel.llm.threads) > 1 and parallel.llm.peak > 1  # really in parallel
    assert len(serial.llm.threads) == 1
    assert parallel.mealie.overlaps == 0  # parse and upload never wrote to Mealie at the same time


def test_the_find_output_lists_requests_in_sheet_order_whatever_order_workers_finish(tmp_path: Path):
    world = BigWorld(tmp_path)
    world.load_sheet()

    result = world.invoke("run", "--stages", "find", "--workers", "4")

    assert result.exit_code == 0, result.output
    lines = [line for line in result.output.splitlines() if line.startswith("found ")]
    assert [line.split()[2] + " " + line.split()[3] for line in lines] == [
        f"Dish {n:02d}" for n in range(DISHES)
    ]


def test_one_failing_item_does_not_stop_the_others(tmp_path: Path):
    world = BigWorld(tmp_path)
    world.llm._scripts.insert(0, ("extract", "4 g itemd", LLMError("boom")))
    world.load_sheet()

    result = world.invoke("run", "--workers", "4")

    statuses = {r.name: r.status for r in world.requests().values()}
    assert statuses["Dish 03"] == "failed"
    assert [s for n, s in statuses.items() if n != "Dish 03"] == ["imported"] * (DISHES - 1)
    assert "boom" in result.output


def test_a_usage_limit_stops_new_calls_and_leaves_the_items_pending(tmp_path: Path):
    world = BigWorld(tmp_path)
    world.llm._scripts.insert(0, ("extract", "", UsageLimited("limit reached")))
    world.load_sheet()

    result = world.invoke("run", "--workers", "4")

    assert "usage limit" in result.output.lower()
    assert len(world.llm.calls) <= 4 < DISHES  # nothing new started after the first limit
    stages = StateStore(world.workspace / "pipeline.db").stage_counts()
    assert stages.get(("extract", "failed"), 0) == 0
    assert stages.get(("extract", "done"), 0) == 0
    assert stages.get(("extract", "running"), 0) == 0


def test_an_interrupted_worker_leaves_nothing_running_and_starts_nothing_else(tmp_path: Path):
    world = BigWorld(tmp_path)
    world.load_sheet()
    world.invoke("run", "--stages", "find", "--workers", "4")

    class Interrupting(TrackingLLM):
        def complete(self, task, prompt, schema, tier, images=()):
            super().complete(task, prompt, schema, tier, images)
            raise KeyboardInterrupt

    interrupting = Interrupting(world.llm)
    store = StateStore(world.workspace / "pipeline.db")
    settings = load_settings(world.workspace)
    adapters = fake_adapters(
        mealie=world.mealie, llm=interrupting, web=world.fetcher, images=world.images,
        engine=FakeIngredientEngine(world.parses),
    )  # fmt: skip
    with pytest.raises(KeyboardInterrupt):
        Pipeline(world.workspace, settings, adapters, store).run(workers=4)

    stages = store.stage_counts()
    assert stages.get(("extract", "running"), 0) == 0
    assert len(interrupting.calls) < DISHES


def test_find_with_workers_keeps_requests_pending_when_every_search_fails(tmp_path: Path):
    world = BigWorld(tmp_path)
    world.search = FakeWebSearch(fail="no network")
    world.fallback = FakeWebSearch(fail="no network")
    world.load_sheet()

    result = world.invoke("run", "--stages", "find", "--workers", "4")

    assert "Every search source failed" in result.output
    pending = RecipeRequests(StateStore(world.workspace / "pipeline.db")).with_status("pending")
    assert len(pending) == DISHES


def test_workers_share_one_download_of_the_mealie_catalog(tmp_path: Path):
    class SlowCatalogMealie(FakeMealie):
        downloads = 0

        def catalog(self):
            SlowCatalogMealie.downloads += 1
            time.sleep(0.1)  # long enough for every thread to arrive while the first is downloading
            return super().catalog()

    world = BigWorld(tmp_path)
    adapters = fake_adapters(mealie=SlowCatalogMealie(token="t", tags=["Dinner"], foods=["Salt"]))
    pipeline = Pipeline(world.workspace, load_settings(world.workspace), adapters, world.store())

    threads = [threading.Thread(target=lambda: pipeline.catalog) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert SlowCatalogMealie.downloads == 1


# -- settings and the command line ------------------------------------------------------------


def test_workers_default_to_one_and_come_from_settings_or_the_environment(tmp_path: Path):
    assert load_settings(tmp_path, {}).run.workers == 1
    assert load_settings(tmp_path, {}).run.stale_minutes == 30
    assert load_settings(tmp_path, {}).llm.max_parallel == 2
    assert load_settings(tmp_path, {"RUN__WORKERS": "3"}).run.workers == 3


def test_zero_workers_is_rejected(tmp_path: Path):
    world = BigWorld(tmp_path)

    assert world.invoke("run", "--workers", "0").exit_code == 2
