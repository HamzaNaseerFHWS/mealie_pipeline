"""Ticket 38: a silent Mealie must not hang a run, and the steps that do not need Mealie go on."""

import json
import re
import socket
import time
from collections.abc import Iterator

import pytest

from mealie_pipeline.adapters.mealie_http import MealieHttpGateway
from mealie_pipeline.doctor import run_doctor
from mealie_pipeline.errors import MealieUnreachableError
from mealie_pipeline.settings import load_settings
from tests.helpers import fake_adapters
from tests.test_pipeline_seam import ENGINE, ITEM_KEY, TOKEN, URL, VIDEO_KEY, World


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in ("MEALIE_URL", "MEALIE_TOKEN", "MEALIE__TIMEOUT_SECONDS", "MEALIE__DEADLINE_SECONDS"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def silent_mealie() -> Iterator[str]:
    """A port that takes connections and never answers: what a hung Mealie looks like."""
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(64)
    host, port = server.getsockname()
    yield f"http://{host}:{port}"
    server.close()


class DownWorld(World):
    """The ticket-02 world with a Mealie that can be swapped for a silent or an unreachable one."""

    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.gateway = None

    def invoke(self, *args: str, input: str | None = None):
        from typer.testing import CliRunner

        from mealie_pipeline.cli import app

        adapters = fake_adapters(
            mealie=self.gateway or self.mealie,
            llm=self.llm,
            videos=self.videos,
            images=self.images,
            engine=ENGINE,
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters, input=input)

    def seed_tag_cache(self) -> None:
        path = self.workspace / "data" / "mealie_tags.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(["Breakfast", "Dinner", "Vegan"]), encoding="utf-8")


@pytest.fixture
def world(tmp_path) -> DownWorld:
    return DownWorld(tmp_path)


def test_the_60_second_timeout_is_the_default_without_any_env_var(tmp_path):
    settings = load_settings(tmp_path, environ={})
    assert settings.mealie.timeout_seconds == 60
    assert settings.mealie.deadline_seconds > settings.mealie.timeout_seconds


def test_a_silent_mealie_ends_a_call_within_the_deadline_with_a_clear_message(silent_mealie):
    gateway = MealieHttpGateway(silent_mealie, TOKEN, timeout=0.3, deadline=0.8, sleep=time.sleep)
    started = time.monotonic()
    with pytest.raises(MealieUnreachableError) as err:
        gateway.list_recipe_summaries()
    waited = time.monotonic() - started

    assert waited < 2.0
    assert re.search(rf"cannot reach Mealie at {re.escape(silent_mealie)} after \d+ s", str(err.value))


def test_the_deadline_also_caps_the_backoff_between_attempts():
    sleeps: list[float] = []
    now = [0.0]

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    gateway = MealieHttpGateway(
        "http://mealie.invalid:9000", TOKEN, backoff=5, deadline=8, sleep=sleep, clock=lambda: now[0]
    )
    with pytest.raises(MealieUnreachableError, match="after 8 s"):
        gateway.about()
    assert sum(sleeps) <= 8


def test_a_run_against_a_silent_mealie_exits_3_with_the_message_within_the_deadline(world, silent_mealie):
    assert world.invoke("add", URL).exit_code == 0
    world.seed_tag_cache()
    world.gateway = MealieHttpGateway(silent_mealie, TOKEN, timeout=0.2, deadline=0.5, sleep=time.sleep)

    started = time.monotonic()
    result = world.invoke("run")
    waited = time.monotonic() - started

    assert result.exit_code == 3, result.output
    assert f"cannot reach Mealie at {silent_mealie} after" in result.output
    assert waited < 10  # one deadline for the first miss, then nothing else waits on Mealie


def test_classify_and_extract_run_with_mealie_down_and_the_mealie_steps_wait(world):
    assert world.invoke("add", URL).exit_code == 0
    world.seed_tag_cache()
    world.mealie.reachable = False

    result = world.invoke("run")

    assert result.exit_code == 3, result.output
    store = world.store()
    assert store.stage_status("video", VIDEO_KEY, "classify") == "done"
    assert store.stage_status("part", ITEM_KEY, "linkcheck") == "done"
    assert store.stage_status("video", VIDEO_KEY, "scrape") == "done"
    assert store.stage_status("part", ITEM_KEY, "extract") == "done"
    assert store.stage_status("part", ITEM_KEY, "parse") is None  # waits, not failed
    assert "FAILED" not in result.output
    extract_prompt = next(c.prompt for c in world.llm.calls if c.task == "extract")
    assert '"Dinner"' in extract_prompt  # the tag names came from the cache

    world.mealie.reachable = True  # Mealie is back: the next run finishes the item
    result = world.invoke("run")
    assert result.exit_code == 0, result.output
    assert len(world.mealie.recipes) == 1
    assert store.stage_status("part", ITEM_KEY, "upload") == "done"


def test_without_any_cached_tags_extract_waits_for_mealie_too(world):
    assert world.invoke("add", URL).exit_code == 0
    world.mealie.reachable = False

    result = world.invoke("run")

    assert result.exit_code == 3, result.output
    assert world.store().stage_status("part", ITEM_KEY, "extract") == "pending"
    assert "FAILED" not in result.output


def test_a_mealie_that_goes_away_during_upload_leaves_the_item_pending(world):
    assert world.invoke("add", URL).exit_code == 0
    early = "metadata,classify,linkcheck,scrape,outline,extract"
    assert world.invoke("run", "--stages", early).exit_code == 0
    world.mealie.reachable = False

    result = world.invoke("run")

    assert result.exit_code == 3, result.output
    assert world.store().stage_status("part", ITEM_KEY, "parse") is None
    assert not world.mealie.recipes


def test_doctor_reports_how_long_mealie_took_to_answer(world):
    ticks = iter([10.0, 10.25])
    adapters = fake_adapters(mealie=world.mealie)
    settings = load_settings(world.workspace, environ={})
    checks = run_doctor(adapters, settings, None, clock=lambda: next(ticks))

    reach = next(c for c in checks if c.name.startswith("Mealie reachable"))
    assert reach.status == "ok"
    assert "answered in 0.25 s" in reach.detail


def test_doctor_warns_when_mealie_is_slow(world):
    ticks = iter([0.0, 45.0])
    adapters = fake_adapters(mealie=world.mealie)
    settings = load_settings(world.workspace, environ={})
    checks = run_doctor(adapters, settings, None, clock=lambda: next(ticks))

    reach = next(c for c in checks if c.name.startswith("Mealie reachable"))
    assert reach.status == "warn" and "slow" in reach.detail
