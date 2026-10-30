"""Site search on a known Recipe Website: WordPress search page, WP REST API, sitemap (ticket 17).

Runs the real `HttpxWebFetcher` against a local `pytest-httpserver` playing the creator's site."""

from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

from mealie_pipeline.adapters.web import HttpxWebFetcher
from mealie_pipeline.site_search import search_site

SITE_FIXTURES = Path(__file__).parent / "fixtures" / "web" / "site"
TITLE = "Chatpata Bhindi Aloo | Crispy Okra Stir Fry"
QUERY = "chatpata bhindi aloo"


@pytest.fixture
def site(httpserver: HTTPServer) -> str:
    return httpserver.url_for("/").rstrip("/")


@pytest.fixture
def fetcher(tmp_path) -> HttpxWebFetcher:
    return HttpxWebFetcher(tmp_path / "cache", min_delay_seconds=0)


def fixture(name: str, site: str) -> str:
    return (SITE_FIXTURES / name).read_text(encoding="utf-8").replace("https://SITE", site)


def serve_search(httpserver: HTTPServer, site: str, name: str = "wp_search.html") -> None:
    httpserver.expect_request("/", query_string={"s": QUERY}).respond_with_data(
        fixture(name, site), content_type="text/html; charset=utf-8"
    )


def serve_rest(httpserver: HTTPServer, site: str, body: str | None = None) -> None:
    httpserver.expect_request("/wp-json/wp/v2/posts").respond_with_data(
        body if body is not None else fixture("wp_posts.json", site), content_type="application/json"
    )


def serve_sitemaps(httpserver: HTTPServer, site: str) -> None:
    for path, name in (("/sitemap.xml", "sitemap_index.xml"), ("/post-sitemap.xml", "post_sitemap.xml")):
        httpserver.expect_request(path).respond_with_data(fixture(name, site), content_type="application/xml")
    httpserver.expect_request("/page-sitemap.xml").respond_with_data(
        '<?xml version="1.0"?><urlset><url><loc>' + site + "/about/</loc></url></urlset>",
        content_type="application/xml",
    )


def requested(httpserver: HTTPServer) -> list[str]:
    return [request.path for request, _ in httpserver.log if request.path != "/robots.txt"]


def test_the_wordpress_search_page_is_tried_first_and_its_match_wins(httpserver, site, fetcher):
    serve_search(httpserver, site)
    serve_rest(httpserver, site)
    serve_sitemaps(httpserver, site)

    match = search_site(site, TITLE, fetcher)

    assert match is not None
    assert (match.url, match.title, match.strategy) == (
        f"{site}/bhindi-aloo/",
        "Chatpata Bhindi Aloo",
        "wp_search",
    )
    assert match.score >= 85
    assert requested(httpserver) == ["/"]  # REST and sitemap are not needed


def test_the_rest_api_is_next_when_the_search_page_has_no_confident_match(httpserver, site, fetcher):
    serve_search(httpserver, site, "wp_search_no_match.html")
    serve_rest(httpserver, site)
    serve_sitemaps(httpserver, site)

    match = search_site(site, TITLE, fetcher)

    assert match is not None
    assert (match.url, match.strategy) == (f"{site}/bhindi-aloo/", "wp_rest")
    assert match.title == "Chatpata Bhindi Aloo – Crispy Okra"  # HTML entities decoded
    assert requested(httpserver) == ["/", "/wp-json/wp/v2/posts"]
    rest_request = httpserver.log[-1][0]
    assert rest_request.args["search"] == QUERY


def test_the_sitemap_is_last_and_its_index_is_followed_to_the_post_sitemap(httpserver, site, fetcher):
    serve_sitemaps(httpserver, site)  # no search page, no REST API: both answer 500 here

    match = search_site(site, TITLE, fetcher)

    assert match is not None
    assert (match.url, match.strategy) == (f"{site}/chatpata-bhindi-aloo/", "sitemap")
    paths = requested(httpserver)
    assert paths.index("/post-sitemap.xml") < paths.index("/page-sitemap.xml")  # post sitemaps first


def test_no_match_when_nothing_on_the_site_is_close_enough(httpserver, site, fetcher):
    serve_search(httpserver, site)
    serve_rest(httpserver, site)
    serve_sitemaps(httpserver, site)

    assert search_site(site, "Palak Paneer", fetcher) is None
    assert "/wp-json/wp/v2/posts" in requested(httpserver) and "/post-sitemap.xml" in requested(httpserver)


def test_a_one_word_overlap_is_not_a_confident_match(httpserver, site, fetcher):
    serve_rest(httpserver, site, '[{"link": "' + site + '/aloo/", "title": {"rendered": "Aloo"}}]')

    assert search_site(site, TITLE, fetcher) is None


def test_a_rest_error_object_is_skipped(httpserver, site, fetcher):
    serve_rest(httpserver, site, '{"code": "rest_no_route", "message": "No route was found"}')
    serve_sitemaps(httpserver, site)

    match = search_site(site, TITLE, fetcher)

    assert match is not None and match.strategy == "sitemap"


def test_the_threshold_is_configurable(httpserver, site, fetcher):
    serve_rest(
        httpserver, site, '[{"link": "' + site + '/aloo/", "title": {"rendered": "Bhindi Aloo Masala"}}]'
    )

    assert search_site(site, "Bhindi Aloo Fry", fetcher, min_score=101) is None
    match = search_site(site, "Bhindi Aloo Fry", fetcher, min_score=50)
    assert match is not None and match.url == f"{site}/aloo/"
