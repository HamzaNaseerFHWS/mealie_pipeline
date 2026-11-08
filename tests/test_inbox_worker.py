"""Ticket 33: links from the Telegram inbox go through the pipeline and the bot hears how they went."""

import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from inbox_bot.bot import Queue, make_api_handler
from mealie_pipeline.adapters.fake_llm import FakeLLM
from mealie_pipeline.inbox_worker import HttpInboxClient, InboxItem, InboxUnavailable, InboxWorker
from mealie_pipeline.pipeline import Pipeline
from mealie_pipeline.settings import load_settings
from tests.helpers import classify_as, fake_adapters
from tests.test_outline_seam import ENGINE as CHUTNEY_ENGINE
from tests.test_outline_seam import make_world
from tests.test_pipeline_seam import (
    CANONICAL,
    ENGINE,
    URL,
    VIDEO_KEY,
    World,
    clean_environment,  # noqa: F401  (autouse fixture)
)
from tests.test_scrape_seam import PAGE_URL, WEB_ENGINE, WebWorld, web_recipe

TOKEN = "inbox-secret"
ME = 111


class Sent:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, int | None]] = []

    def __call__(self, chat_id: int, text: str, reply_to: int | None) -> None:
        self.messages.append((chat_id, text, reply_to))


@pytest.fixture
def bot() -> Iterator[tuple[Queue, str, Sent]]:
    """The real inbox bot's queue and HTTP API on a local port; Telegram replies are recorded."""
    queue, sent = Queue(":memory:"), Sent()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_api_handler(queue, TOKEN, sent))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield queue, f"http://127.0.0.1:{server.server_address[1]}", sent
    server.shutdown()
    server.server_close()


class FakeInbox:
    """An inbox that can go away; records every result posted."""

    def __init__(self, items: list[InboxItem]):
        self.items = list(items)
        self.posted: list[tuple[int, dict[str, Any]]] = []
        self.down = False

    def pending(self) -> list[InboxItem]:
        if self.down:
            raise InboxUnavailable("inbox not reachable: connection refused")
        posted = {i for i, _r in self.posted}
        return [i for i in self.items if i.id not in posted]

    def post_result(self, item_id: int, result: dict[str, Any]) -> None:
        if self.down:
            raise InboxUnavailable("inbox not reachable: connection refused")
        self.posted.append((item_id, result))


def worker_for(world: World, client, engine=ENGINE) -> InboxWorker:
    adapters = fake_adapters(
        mealie=world.mealie,
        llm=world.llm,
        videos=world.videos,
        images=world.images,
        engine=engine,
        web=getattr(world, "web", None) or fake_adapters().web,
    )
    settings = load_settings(world.workspace)
    pipeline = Pipeline(world.workspace, settings, adapters, world.store())
    return InboxWorker(pipeline, client, expand=adapters.web.expand)


def test_a_youtube_link_ends_as_done_with_the_mealie_link_over_the_bot_api(tmp_path, bot):
    queue, url, sent = bot
    queue.add(URL, ME, 42)
    world = World(tmp_path)

    report = worker_for(world, HttpInboxClient(url, TOKEN)).cycle()

    [recipe] = world.mealie.recipes.values()
    link = world.mealie.recipe_url(recipe["slug"])
    assert report.reported == [f"{URL}: done"]
    assert queue.pending() == []
    assert sent.messages == [(ME, f"✅ Added to Mealie\n{link}", 42)]
    assert VIDEO_KEY in world.store().list_video_keys("inbox:telegram")


def test_a_non_recipe_link_is_reported_as_not_recipe_with_its_label(tmp_path):
    world = World(tmp_path)
    world.llm = FakeLLM()
    world.llm.script("classify", classify_as("restaurant_or_place"))
    inbox = FakeInbox([InboxItem(1, URL)])

    worker_for(world, inbox).cycle()

    assert inbox.posted == [(1, {"status": "not_recipe", "mealie_urls": [], "note": "restaurant_or_place"})]
    assert not world.mealie.recipes


def test_a_link_that_cannot_be_downloaded_fails_with_a_reason(tmp_path):
    world = World(tmp_path)
    world.videos.infos.clear()
    inbox = FakeInbox([InboxItem(1, URL)])

    worker_for(world, inbox).cycle()

    [(item_id, result)] = inbox.posted
    assert item_id == 1 and result["status"] == "failed"
    assert result["note"].startswith("download failed")


def test_sending_a_failed_link_again_runs_it_again(tmp_path):
    world = World(tmp_path)
    infos = dict(world.videos.infos)
    world.videos.infos.clear()
    inbox = FakeInbox([InboxItem(1, URL)])
    worker = worker_for(world, inbox)
    worker.cycle()
    assert inbox.posted[0][1]["status"] == "failed"

    world.videos.infos.update(infos)
    inbox.items.append(InboxItem(2, URL))
    worker.cycle()

    assert [(i, r["status"]) for i, r in inbox.posted] == [(1, "failed"), (2, "done")]
    assert len(world.mealie.recipes) == 1


def test_a_facebook_share_link_the_redirect_cannot_resolve_is_resolved_by_the_downloader(tmp_path):
    share = "https://www.facebook.com/share/r/19uAzn9G7X/"
    canonical = "https://www.facebook.com/watch/?v=1669420287910162"
    world = World(tmp_path)
    info = dict(world.videos.infos[CANONICAL])
    # Facebook answers a plain request with 400, so the redirect leaves the share link as it is;
    # the downloader knows the Video behind it.
    world.videos.infos[share] = {**info, "webpage_url": canonical + "&_rdr"}
    world.videos.infos[canonical] = {**info, "webpage_url": canonical}
    inbox = FakeInbox([InboxItem(1, share)])

    worker_for(world, inbox).cycle()

    assert [r["status"] for _i, r in inbox.posted] == ["done"]
    assert "facebook:1669420287910162" in world.store().list_video_keys("inbox:telegram")


def test_a_link_the_pipeline_cannot_read_fails_without_a_run(tmp_path):
    world = World(tmp_path)
    inbox = FakeInbox([InboxItem(1, "mailto:someone@example.com")])

    worker_for(world, inbox).cycle()

    assert inbox.posted == [
        (1, {"status": "failed", "mealie_urls": [], "note": "not a link the pipeline can read"})
    ]


def test_a_recipe_website_link_goes_the_recipe_page_way(tmp_path):
    world = WebWorld(tmp_path)
    world.llm.script("extract", web_recipe())
    inbox = FakeInbox([InboxItem(7, PAGE_URL)])

    worker_for(world, inbox, engine=WEB_ENGINE).cycle()

    [(item_id, result)] = inbox.posted
    assert result["status"] == "done", result
    [recipe] = world.mealie.recipes.values()
    assert recipe["orgURL"] == PAGE_URL
    assert result["mealie_urls"] == [world.mealie.recipe_url(recipe["slug"])]


def test_a_down_bot_loses_nothing_and_a_result_is_never_posted_twice(tmp_path):
    world = World(tmp_path)
    inbox = FakeInbox([InboxItem(1, URL)])
    inbox.down = True
    worker_for(world, inbox).cycle()  # the bot is down from the start: nothing happens, nothing lost

    inbox.down = False
    worker_for(world, inbox).cycle()  # a fresh start (a container restart) takes and reports it
    assert [i for i, _r in inbox.posted] == [1]

    restarted = worker_for(world, inbox)
    assert restarted.items[1].posted  # remembered across a restart
    inbox.items.append(InboxItem(1, URL))  # the bot lists it again (say, its answer got lost)
    restarted.cycle()
    inbox.down = True
    assert restarted.cycle().problems  # waits, re-sends nothing
    inbox.down = False
    restarted.cycle()
    assert [i for i, _r in inbox.posted] == [1]  # still once
    assert len(world.mealie.recipes) == 1


def test_a_result_the_bot_could_not_take_is_posted_on_the_next_cycle(tmp_path):
    world = World(tmp_path)

    class FlakyPost(FakeInbox):
        fail_next_post = True

        def post_result(self, item_id, result):
            if self.fail_next_post:
                self.fail_next_post = False
                raise InboxUnavailable("inbox answered 502")
            super().post_result(item_id, result)

    inbox = FlakyPost([InboxItem(1, URL)])
    worker = worker_for(world, inbox)
    worker.cycle()
    assert inbox.posted == []
    worker.cycle()
    assert [i for i, _r in inbox.posted] == [1]
    assert len(world.mealie.recipes) == 1  # the run was not repeated


def test_mealie_down_keeps_the_link_waiting_then_reports_it(tmp_path):
    world = World(tmp_path)
    world.mealie.reachable = False
    inbox = FakeInbox([InboxItem(1, URL)])
    worker = worker_for(world, inbox)

    report = worker.cycle()
    assert inbox.posted == [] and report.waiting == 1

    world.mealie.reachable = True
    worker.cycle()
    assert inbox.posted[0][1]["status"] == "done"


def test_a_multi_recipe_video_returns_all_its_mealie_links(tmp_path):
    world = make_world(tmp_path, mint_for_tamarind=False)
    inbox = FakeInbox([InboxItem(3, "https://youtu.be/de1ppj9L4Hk")])

    worker_for(world, inbox, engine=CHUTNEY_ENGINE).cycle()

    [(_id, result)] = inbox.posted
    assert result["status"] == "done"
    assert len(result["mealie_urls"]) == 3 == len(world.mealie.recipes)


def test_a_link_only_stub_is_done_with_its_mealie_link(tmp_path):
    world = World(tmp_path)
    world.videos.infos[CANONICAL]["description"] = "#okra #reels 😍"
    inbox = FakeInbox([InboxItem(1, URL)])

    worker_for(world, inbox).cycle()

    [(_id, result)] = inbox.posted
    assert result["status"] == "done" and len(result["mealie_urls"]) == 1


def test_the_loop_stops_cleanly_when_asked_and_resumes_at_the_next_start(tmp_path):
    world = World(tmp_path)
    inbox = FakeInbox([InboxItem(1, URL)])
    worker = worker_for(world, inbox)
    stop = threading.Event()
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        stop.set()  # SIGTERM arrives while the worker waits

    worker.loop(60, stop.is_set, sleep=sleep)

    assert [i for i, _r in inbox.posted] == [1]
    assert len(sleeps) == 1  # stopped at once instead of sleeping the full minute
    inbox.items.append(InboxItem(2, "https://youtu.be/BBBBBBBBBBB"))
    world.videos.infos["https://www.youtube.com/watch?v=BBBBBBBBBBB"] = world.videos.infos[CANONICAL]
    worker_for(world, inbox).cycle()  # a new start picks up where it left
    assert [i for i, _r in inbox.posted] == [1, 2]


def test_the_cli_refuses_to_start_without_the_inbox_settings(tmp_path):
    from typer.testing import CliRunner

    from mealie_pipeline.cli import app

    world = World(tmp_path)
    result = CliRunner().invoke(
        app, ["--workspace", str(tmp_path), "inbox-worker", "--once"], obj=fake_adapters(mealie=world.mealie)
    )
    assert result.exit_code == 2 and "INBOX_URL" in result.output


def test_the_cli_runs_one_cycle_against_the_bot(tmp_path, bot, monkeypatch):
    from typer.testing import CliRunner

    from mealie_pipeline.cli import app

    queue, url, sent = bot
    queue.add(URL, ME, 9)
    world = World(tmp_path)
    monkeypatch.setenv("INBOX_URL", url)
    monkeypatch.setenv("INBOX_API_TOKEN", TOKEN)
    adapters = fake_adapters(
        mealie=world.mealie, llm=world.llm, videos=world.videos, images=world.images, engine=ENGINE
    )

    result = CliRunner().invoke(app, ["--workspace", str(tmp_path), "inbox-worker", "--once"], obj=adapters)

    assert result.exit_code == 0, result.output
    assert f"reported {URL}: done" in result.output
    assert sent.messages and sent.messages[0][0] == ME
