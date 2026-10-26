"""HttpxWebFetcher against httpx's mock transport: headers, robots.txt, pacing, cache, blocking."""

import httpx
import pytest

from mealie_pipeline.adapters.web import HttpxWebFetcher, looks_blocked

UA = "Mozilla/5.0 (Test Browser)"
HTML = "<html><body><h1>A recipe</h1></body></html>"


class Clock:
    def __init__(self):
        self.now = 1000.0
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make(tmp_path, handler, clock=None, **kwargs):
    clock = clock or Clock()
    requests: list[httpx.Request] = []

    def recording(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    client = httpx.Client(transport=httpx.MockTransport(recording), follow_redirects=True)
    fetcher = HttpxWebFetcher(
        tmp_path / "cache", user_agent=UA, client=client, clock=clock, sleep=clock.sleep, **kwargs
    )
    return fetcher, requests, clock


def ok(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(404)
    return httpx.Response(200, html=HTML)


def test_a_real_browser_user_agent_is_sent(tmp_path):
    fetcher, requests, _ = make(tmp_path, ok)

    page = fetcher.fetch("https://blog.example/soup")

    assert page.ok and page.html == HTML and page.final_url == "https://blog.example/soup"
    assert {r.headers["user-agent"] for r in requests} == {UA}


ROBOTS = "User-agent: *\nDisallow: /private/\n"


def robots_site(request: httpx.Request) -> httpx.Response:
    if request.url.path == "/robots.txt":
        return httpx.Response(200, text=ROBOTS)
    return httpx.Response(200, html=HTML)


def test_robots_txt_disallow_is_honoured_without_requesting_the_page(tmp_path):
    fetcher, requests, _ = make(tmp_path, robots_site)

    blocked = fetcher.fetch("https://blog.example/private/soup")
    allowed = fetcher.fetch("https://blog.example/public/soup")

    assert (blocked.blocked, blocked.ok) == ("robots", False)
    assert allowed.ok
    assert [r.url.path for r in requests] == ["/robots.txt", "/public/soup"]  # robots fetched once


def test_an_allowlisted_domain_skips_robots_txt(tmp_path):
    fetcher, requests, _ = make(tmp_path, robots_site, robots_allowlist=("blog.example",))

    page = fetcher.fetch("https://blog.example/private/soup")

    assert page.ok
    assert [r.url.path for r in requests] == ["/private/soup"]


def test_at_least_two_seconds_pass_between_requests_to_one_domain(tmp_path):
    fetcher, _, clock = make(tmp_path, ok)

    fetcher.fetch("https://blog.example/a")  # also fetches robots.txt first
    fetcher.fetch("https://blog.example/b")
    fetcher.fetch("https://other.example/c")

    # blog.example: robots.txt (no wait), /a (2 s), /b (2 s); other.example: robots.txt is its own
    # domain's first request (no wait), then /c waits 2 s for that domain.
    assert clock.slept == [2.0, 2.0, 2.0]


def test_no_wait_when_the_gap_is_already_long_enough(tmp_path):
    fetcher, _, clock = make(tmp_path, ok, robots_allowlist=("blog.example",))

    fetcher.fetch("https://blog.example/a")
    clock.now += 5
    fetcher.fetch("https://blog.example/b")

    assert clock.slept == []


def test_pages_are_cached_on_disk_by_url(tmp_path):
    fetcher, requests, _ = make(tmp_path, ok)
    fetcher.fetch("https://blog.example/soup")
    count = len(requests)

    again = fetcher.fetch("https://blog.example/soup")
    fresh_fetcher, fresh_requests, _ = make(tmp_path, ok)  # a new process, same cache directory
    from_disk = fresh_fetcher.fetch("https://blog.example/soup")

    assert len(requests) == count and fresh_requests == []
    assert again.html == from_disk.html == HTML


@pytest.mark.parametrize("status", [403, 429])
def test_blocked_statuses_are_marked_needs_browser_not_errors(tmp_path, status):
    def handler(request):
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(status, text="no")

    fetcher, _, _ = make(tmp_path, handler)

    page = fetcher.fetch("https://blog.example/soup")

    assert (page.blocked, page.status, page.ok) == ("needs_browser", status, False)


def test_a_cloudflare_challenge_served_with_200_is_marked_needs_browser(tmp_path):
    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(200, html="<html><head><title>Just a moment...</title></head></html>")

    fetcher, _, _ = make(tmp_path, handler)

    assert fetcher.fetch("https://blog.example/soup").blocked == "needs_browser"


def test_a_connection_error_is_reported_and_not_cached(tmp_path):
    calls = {"n": 0}

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, html=HTML)

    fetcher, _, _ = make(tmp_path, handler)

    first = fetcher.fetch("https://blog.example/soup")
    second = fetcher.fetch("https://blog.example/soup")

    assert first.blocked == "error" and not first.ok
    assert second.ok  # the failure was not cached


def test_expand_follows_redirects_with_head_and_returns_the_final_url(tmp_path):
    methods = []

    def handler(request):
        methods.append(request.method)
        if request.url.host == "bit.ly":
            return httpx.Response(301, headers={"location": "https://blog.example/soup?utm_source=x"})
        return httpx.Response(200, html=HTML)

    fetcher, _, _ = make(tmp_path, handler)

    assert fetcher.expand("https://bit.ly/3xyz") == "https://blog.example/soup?utm_source=x"
    assert set(methods) == {"HEAD"}


def test_expand_falls_back_to_get_when_head_is_refused(tmp_path):
    def handler(request):
        if request.method == "HEAD":
            return httpx.Response(405)
        if request.url.host == "geni.us":
            return httpx.Response(302, headers={"location": "https://blog.example/final"})
        return httpx.Response(200, html=HTML)

    fetcher, _, _ = make(tmp_path, handler)

    assert fetcher.expand("https://geni.us/abc") == "https://blog.example/final"


def test_expand_returns_the_input_when_the_link_is_unreachable(tmp_path):
    def handler(request):
        raise httpx.ConnectError("down")

    fetcher, _, _ = make(tmp_path, handler)

    assert fetcher.expand("https://bit.ly/3xyz") == "https://bit.ly/3xyz"


@pytest.mark.parametrize(
    ("status", "html", "blocked"),
    [
        (200, "<html>ok</html>", False),
        (403, "", True),
        (429, "", True),
        (200, "<title>Attention Required! | Cloudflare</title>", True),
        (200, "<div id='cf-chl-widget'></div>", True),
        (404, "not found", False),
    ],
)
def test_looks_blocked(status, html, blocked):
    assert looks_blocked(status, html) is blocked
