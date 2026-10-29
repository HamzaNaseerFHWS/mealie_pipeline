"""Ticket 14 at the pipeline seam: `mp login`, sessions in `mp doctor`, private YouTube lists."""

import json
from typing import Any

import pytest
from typer.testing import CliRunner

from mealie_pipeline.adapters.collectors import YouTubeCollector
from mealie_pipeline.adapters.fake_browser import FakeBrowser
from mealie_pipeline.adapters.fake_video_source import FakeVideoSource
from mealie_pipeline.adapters.video_source import PlaylistEntry
from mealie_pipeline.cli import app
from mealie_pipeline.sessions import to_netscape
from tests.helpers import fake_adapters
from tests.test_pipeline_seam import ENGINE, World, clean_environment  # noqa: F401  (autouse fixture)

__all__ = ["clean_environment"]

WATCH_LATER = "https://www.youtube.com/playlist?list=WL"
SECRET = "s3cr3t-cookie-value-never-printed"


def cookie(name: str, domain: str, value: str = SECRET, **extra: Any) -> dict[str, Any]:
    return {"name": name, "value": value, "domain": domain, "path": "/", "expires": -1, "httpOnly": True,
            "secure": True, "sameSite": "Lax"} | extra  # fmt: skip


class LoginWorld(World):
    def __init__(self, tmp_path):
        super().__init__(tmp_path)
        self.videos = FakeVideoSource(self.videos.infos)
        self.browser = FakeBrowser()
        self.cookies_file = tmp_path / "secrets" / "cookies.txt"

    def invoke(self, *args: str, input: str | None = None):
        adapters = fake_adapters(
            mealie=self.mealie,
            llm=self.llm,
            videos=self.videos,
            images=self.images,
            engine=ENGINE,
            browser=self.browser,
            collectors={"youtube": YouTubeCollector(self.videos, cookiefile=self.cookies_file)},
        )
        return CliRunner().invoke(app, ["--workspace", str(self.workspace), *args], obj=adapters, input=input)


@pytest.fixture
def world(tmp_path, monkeypatch) -> LoginWorld:
    monkeypatch.setattr("mealie_pipeline.cli.LOGIN_POLL_SECONDS", 0.01)
    return LoginWorld(tmp_path)


def test_login_waits_for_the_session_then_exports_cookies_for_yt_dlp(world: LoginWorld):
    # the user is still typing their password for two polls, then the session cookie appears
    world.browser.cookie_script = [
        [cookie("PREF", ".youtube.com")],
        [cookie("PREF", ".youtube.com")],
        [
            cookie("PREF", ".youtube.com"),
            cookie("SID", ".youtube.com"),
            cookie("sessionid", ".instagram.com"),
        ],
    ]

    result = world.invoke("login", "youtube")

    assert result.exit_code == 0, result.output
    assert world.browser.shown == [
        "https://accounts.google.com/ServiceLogin?service=youtube&continue=https://www.youtube.com/"
    ]
    assert world.browser.closed
    text = world.cookies_file.read_text(encoding="utf-8")
    assert text.startswith("# Netscape HTTP Cookie File")
    assert "\tSID\t" in text and "\tsessionid\t" in text  # the whole profile: one file serves every platform
    logins = json.loads((world.workspace / "secrets" / "logins.json").read_text(encoding="utf-8"))
    assert set(logins) == {"youtube"}
    assert "logged in to youtube" in result.output
    assert SECRET not in result.output


def test_pressing_enter_ends_the_wait_and_says_no_session_was_found(world: LoginWorld):
    world.browser.cookie_script = [[cookie("csrftoken", ".instagram.com")]]

    result = world.invoke("login", "instagram", input="\n")

    assert result.exit_code == 1
    assert "no Instagram session" in result.output
    assert world.browser.closed
    assert not (world.workspace / "secrets" / "logins.json").exists()


def test_login_refuses_an_unknown_platform(world: LoginWorld):
    result = world.invoke("login", "tiktok")

    assert result.exit_code == 2
    assert "youtube, instagram, facebook" in result.output
    assert world.browser.shown == []


def test_doctor_shows_each_platforms_session_and_its_age_without_cookie_values(world: LoginWorld):
    world.browser.cookie_script = [[cookie("SID", ".youtube.com"), cookie("PREF", ".youtube.com")]]
    world.invoke("login", "youtube")

    result = world.invoke("doctor")

    assert "youtube session: logged in today" in result.output
    assert "instagram session" in result.output and "run `mp login instagram`" in result.output
    assert "facebook session" in result.output
    assert SECRET not in result.output
    assert "value" not in result.output.lower()


def test_doctor_without_any_login_only_warns(world: LoginWorld):
    result = world.invoke("doctor")

    assert result.exit_code == 0, result.output
    assert "[WARN] youtube session: not logged in" in result.output


def test_private_lists_collect_with_the_cookie_file(world: LoginWorld):
    world.videos.private.add(WATCH_LATER)
    world.videos.playlists[WATCH_LATER] = [
        PlaylistEntry("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Dal")
    ]
    world.cookies_file.parent.mkdir()
    world.cookies_file.write_text(to_netscape([cookie("SID", ".youtube.com")]), encoding="utf-8")
    world.invoke("lists", "add", WATCH_LATER)

    result = world.invoke("sync")

    assert result.exit_code == 0, result.output
    assert world.videos.cookiefiles == [world.cookies_file]
    assert [v.video_key for v in world.store().videos()] == ["youtube:dQw4w9WgXcQ"]


def test_private_lists_still_ask_for_a_login_without_the_cookie_file(world: LoginWorld):
    world.videos.private.add(WATCH_LATER)
    world.invoke("lists", "add", WATCH_LATER)

    result = world.invoke("sync")

    assert result.exit_code == 1
    assert "mp login youtube" in result.output


def test_a_stop_signal_stops_that_list_with_a_clear_message(world: LoginWorld):
    from mealie_pipeline.errors import NeedsHumanLogin

    class StoppedCollector:
        def enumerate(self, list_url: str):
            raise NeedsHumanLogin("youtube", "checkpoint", "Sign in to confirm you're not a bot")
            yield  # pragma: no cover

    world.invoke("lists", "add", "https://www.youtube.com/playlist?list=PLdinner")
    adapters = fake_adapters(
        videos=world.videos, browser=world.browser, collectors={"youtube": StoppedCollector()}
    )
    result = CliRunner().invoke(app, ["--workspace", str(world.workspace), "sync"], obj=adapters)

    assert result.exit_code == 1
    assert "checkpoint" in result.output
    assert "mp login youtube" in result.output
    assert "Traceback" not in result.output
