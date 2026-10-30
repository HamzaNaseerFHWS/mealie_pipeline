"""Ticket 17 at the pipeline seam: link-in-bio pages, blocked pages and the Creator's website."""

import csv
import json

import pytest

from mealie_pipeline.adapters.browser import RenderedPage
from mealie_pipeline.adapters.fake_browser import FakeBrowser
from mealie_pipeline.creators import CreatorRegistry
from tests.helpers import non_classify_calls, recipe_llm
from tests.test_pipeline_seam import CANONICAL, VIDEO_KEY, clean_environment, load  # noqa: F401
from tests.test_scrape_seam import (
    PAGE_URL,
    URL,
    WebWorld,
    page,
    run,
    web_json,
    web_recipe,
)

__all__ = ["clean_environment"]

BIO_URL = "https://linktr.ee/yourfoodlab"
SITE = "https://foodlab.example"
BIO_HTML = """<a href="https://foodlab.example/">My blog</a>
<a href="https://foodlab.example/bhindi-aloo/">Chatpata Bhindi Aloo</a>
<a href="https://foodlab.example/dal/">Tadka Dal</a>"""
OTHER_VIDEO = "https://youtu.be/AAAAAAAAAAA"


class BioWorld(WebWorld):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.browser = FakeBrowser(pages={BIO_URL: RenderedPage(BIO_URL, 200, "Linktree", BIO_HTML)})
        self.web.pages[f"{SITE}/?s=chatpata+bhindi+aloo"] = (
            '<a href="/bhindi-aloo/">Chatpata Bhindi Aloo</a><a href="/dal/">Dal</a>'
        )

    def invoke(self, *args: str):
        from typer.testing import CliRunner

        from mealie_pipeline.cli import app
        from tests.helpers import fake_adapters
        from tests.test_scrape_seam import WEB_ENGINE

        adapters = fake_adapters(
            mealie=self.mealie, llm=self.llm, videos=self.videos, images=self.images,
            engine=WEB_ENGINE, web=self.web, browser=self.browser,
        )  # fmt: skip
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters)


@pytest.fixture
def world(tmp_path) -> BioWorld:
    return BioWorld(tmp_path)


def report_rows(world: BioWorld) -> list[dict]:
    world.invoke("report")
    with (world.workspace / "reports" / "report.csv").open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_a_link_in_bio_page_is_opened_in_the_browser_and_the_matching_link_is_used(world: BioWorld):
    world.describe(f"Full recipe on my Linktree: {BIO_URL}")

    result = run(world)

    assert result.exit_code == 0, result.output
    assert world.browser.rendered == [BIO_URL]
    stored = web_json(world)
    assert (stored["link_source"], stored["bio_page"]) == ("link_in_bio", BIO_URL)
    assert stored["final_url"] == PAGE_URL
    assert world.web.fetched == [PAGE_URL]  # the other bio link is not fetched
    assert len(world.mealie.recipes) == 1
    assert report_rows(world)[0]["link_source"] == "link_in_bio"


def test_the_browser_is_not_used_when_the_description_links_a_plain_recipe_page(world: BioWorld):
    run(world)

    assert world.browser.rendered == [] and world.browser.opened == []


def test_a_blocked_recipe_page_is_read_through_the_browser(world: BioWorld):
    world.web.blocked[PAGE_URL] = "needs_browser"
    world.browser.pages[PAGE_URL] = RenderedPage(PAGE_URL, 200, "Bhindi", page("wprm_graph.html"))

    result = run(world)

    assert result.exit_code == 0, result.output
    assert web_json(world)["rendered"] is True
    assert "[SRC:web]" in non_classify_calls(world.llm)[0].prompt


def test_a_challenge_page_is_never_worked_around(world: BioWorld):
    world.web.blocked[PAGE_URL] = "needs_browser"
    challenge = "<html><title>Just a moment...</title><body>checking your browser</body></html>"
    world.browser.pages[PAGE_URL] = RenderedPage(PAGE_URL, 200, "Just a moment...", challenge)
    world.describe(f"Recipe: {PAGE_URL}\n" + load("youtube_info_okra.json")["description"])
    world.llm = recipe_llm()
    world.llm.script("extract", load("llm_extract_okra.json"))

    run(world)

    assert web_json(world)["reason"] == "needs_browser"
    assert world.browser.rendered == [PAGE_URL]  # tried once, no retry


def test_a_reel_that_says_recipe_in_bio_gets_the_creators_website_recipe_by_site_search(world: BioWorld):
    # A first Video taught the registry which website this Creator has ...
    world.invoke("add", URL)
    world.invoke("run")
    store = world.store()
    assert CreatorRegistry(store).all() == {"yourfoodlab": SITE}
    # ... so a second Video with no link at all finds its recipe there.
    other_info = dict(world.info)
    other_info.update(
        id="AAAAAAAAAAA", webpage_url="https://www.youtube.com/watch?v=AAAAAAAAAAA",
        description="Recipe in bio! #okra", title="Chatpata Bhindi Aloo",
    )  # fmt: skip
    world.videos.infos["https://www.youtube.com/watch?v=AAAAAAAAAAA"] = other_info
    world.llm.script("extract", web_recipe())
    world.invoke("add", OTHER_VIDEO)

    result = world.invoke("run")

    assert result.exit_code == 0, result.output
    stored = json.loads(
        (world.workspace / "data" / "youtube" / "AAAAAAAAAAA" / "web.json").read_text(encoding="utf-8")
    )
    assert (stored["link_source"], stored["site_strategy"]) == ("site_search", "wp_search")
    assert stored["final_url"] == PAGE_URL
    rows = {r["video_url"]: r for r in report_rows(world)}
    assert rows["https://www.youtube.com/watch?v=AAAAAAAAAAA"]["link_source"] == "site_search"
    assert rows[CANONICAL]["link_source"] == "description"


def test_a_site_search_recipe_must_clear_the_stricter_upload_bar(world: BioWorld, monkeypatch):
    monkeypatch.setenv("VERIFY__SITE_SEARCH_UPLOAD_AT", "101")  # nothing can clear it
    world.invoke("add", URL)
    world.invoke("run")  # the first Video links the page directly: normal bar, uploaded
    other = dict(world.info)
    other.update(description="Recipe in bio!", title="Chatpata Bhindi Aloo")
    world.videos.infos["https://www.youtube.com/watch?v=AAAAAAAAAAA"] = other
    world.llm.script("extract", web_recipe())
    world.invoke("add", OTHER_VIDEO)

    world.invoke("run")

    store = world.store()
    assert (store.part(VIDEO_KEY + "#1").verify or {}).get("outcome") == "upload"
    assert (store.part("youtube:AAAAAAAAAAA#1").verify or {}).get(
        "outcome"
    ) == "upload_review"  # uploaded, but tagged for review
