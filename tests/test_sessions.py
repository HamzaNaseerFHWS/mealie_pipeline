"""Pure parts of the logins: cookie export to Netscape format, session detection, stop signals."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from mealie_pipeline.sessions import (
    has_session,
    load_platforms,
    parse_netscape,
    session_statuses,
    stop_signal,
    to_netscape,
)

FIXTURES = Path(__file__).parent / "fixtures" / "stop_signals"
REPO = Path(__file__).parents[1]
PLATFORMS = load_platforms(REPO)
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=UTC)
NOW_TS = NOW.timestamp()
IG = "https://www.instagram.com/"
FB = "https://www.facebook.com/"


def cookie(name: str, domain: str, **extra) -> dict:
    return {
        "name": name,
        "value": f"value-of-{name}",
        "domain": domain,
        "path": "/",
        "expires": -1,
        "httpOnly": False,
        "secure": False,
        "sameSite": "Lax",
    } | extra


@pytest.mark.parametrize(
    ("given", "line"),
    [
        (cookie("PREF", ".youtube.com"), ".youtube.com\tTRUE\t/\tFALSE\t0\tPREF\tvalue-of-PREF"),
        (
            cookie("SID", ".youtube.com", expires=1830000000.75, secure=True),
            ".youtube.com\tTRUE\t/\tTRUE\t1830000000\tSID\tvalue-of-SID",
        ),
        (
            cookie("sessionid", ".instagram.com", httpOnly=True, secure=True, expires=1800000000),
            "#HttpOnly_.instagram.com\tTRUE\t/\tTRUE\t1800000000\tsessionid\tvalue-of-sessionid",
        ),
        (
            cookie("csrftoken", "www.instagram.com", path="/accounts"),
            "www.instagram.com\tFALSE\t/accounts\tFALSE\t0\tcsrftoken\tvalue-of-csrftoken",
        ),
    ],
)
def test_playwright_cookies_become_netscape_lines(given, line):
    text = to_netscape([given])

    assert text.splitlines()[0] == "# Netscape HTTP Cookie File"
    assert text.splitlines()[-1] == line
    assert text.endswith("\n")


def test_netscape_text_reads_back_including_httponly_cookies():
    text = to_netscape(
        [
            cookie("sessionid", ".instagram.com", httpOnly=True, expires=1800000000),
            cookie("PREF", ".youtube.com"),
        ]
    )

    parsed = parse_netscape(text)

    assert [(c["name"], c["domain"], c["expires"], c["httpOnly"]) for c in parsed] == [
        ("sessionid", ".instagram.com", 1800000000, True),
        ("PREF", ".youtube.com", -1, False),
    ]


@pytest.mark.parametrize(
    ("platform", "cookies", "expected"),
    [
        ("youtube", [cookie("SID", ".youtube.com")], True),
        ("youtube", [cookie("PREF", ".youtube.com"), cookie("SID", ".google.com")], False),
        ("instagram", [cookie("sessionid", ".instagram.com")], True),
        ("instagram", [cookie("csrftoken", ".instagram.com")], False),
        ("instagram", [cookie("sessionid", ".instagram.com", expires=NOW_TS - 60)], False),  # expired
        ("facebook", [cookie("c_user", ".facebook.com"), cookie("xs", ".facebook.com")], True),
        ("facebook", [cookie("c_user", ".facebook.com")], False),  # both are needed
    ],
)
def test_a_session_needs_the_platforms_session_cookies(platform, cookies, expected):
    assert has_session(cookies, PLATFORMS[platform], now=NOW_TS) is expected


def test_session_statuses_give_age_and_expiry_per_platform():
    text = to_netscape(
        [
            cookie("SID", ".youtube.com", expires=NOW_TS + 30 * 86400),
            cookie("sessionid", ".instagram.com", expires=NOW_TS - 86400),
        ]
    )
    logins = {"youtube": "2026-10-26T12:00:00+00:00", "instagram": "2026-01-01T00:00:00+00:00"}

    statuses = {s.platform: s for s in session_statuses(text, logins, PLATFORMS, NOW)}

    assert statuses["youtube"].logged_in is True
    assert statuses["youtube"].age_days == 3
    assert statuses["youtube"].expires_in_days == 30
    assert statuses["instagram"].logged_in is False  # the session cookie expired
    assert statuses["facebook"].logged_in is False
    assert statuses["facebook"].age_days is None


@pytest.mark.parametrize(
    ("platform", "fixture", "url", "expected"),
    [
        ("instagram", "instagram_login.html", f"{IG}accounts/login/?next=/", "login_wall"),
        ("instagram", "instagram_challenge.html", f"{IG}challenge/AbC/", "checkpoint"),
        ("instagram", "instagram_challenge.html", f"{IG}some.chef/saved/", "checkpoint"),
        ("instagram", "instagram_rate_limit.html", f"{IG}some.chef/saved/", "rate_limit"),
        ("instagram", "instagram_saved_ok.html", f"{IG}some.chef/saved/all-posts/", None),
        ("facebook", "facebook_login.html", f"{FB}login/?next=saved", "login_wall"),
        ("facebook", "facebook_checkpoint.html", f"{FB}checkpoint/1501092823525282/", "checkpoint"),
        ("facebook", "facebook_blocked.html", f"{FB}saved/", "rate_limit"),
        ("facebook", "facebook_saved_ok.html", f"{FB}saved/", None),
        ("youtube", "youtube_bot_check.html", "https://www.youtube.com/playlist?list=WL", "checkpoint"),
        ("youtube", "youtube_watch_later_ok.html", "https://accounts.google.com/v3/signin/", "login_wall"),
        ("youtube", "youtube_watch_later_ok.html", "https://www.youtube.com/playlist?list=WL", None),
    ],
)  # fmt: skip
def test_stop_signals_are_recognised_on_saved_pages(platform, fixture, url, expected):
    html = (FIXTURES / fixture).read_text(encoding="utf-8")
    title = html.split("<title>")[1].split("</title>")[0]

    assert stop_signal(PLATFORMS[platform], url, title, html) == expected


def test_the_profile_and_cookie_file_are_git_ignored():
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()

    assert "secrets/" in ignored
    assert "cookies*.txt" in ignored
