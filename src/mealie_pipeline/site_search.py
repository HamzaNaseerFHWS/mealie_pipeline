"""Site search (pure, over the WebFetcher): find a Video's page on its Creator's known Recipe Website.

Used when a Video has no recipe link but its Creator has a Recipe Website. The strategies run in
order and the first confident match wins: the WordPress search page (`/?s=`), the WordPress REST API
(`/wp-json/wp/v2/posts?search=`), then `sitemap.xml` (following a sitemap index). A page counts only
when its title (or slug) matches the Video title at `min_score` or more (`links.title_match`).
"""

import html
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal
from urllib.parse import quote_plus, urljoin, urlparse

from selectolax.lexbor import LexborHTMLParser as HTMLParser

from mealie_pipeline import links
from mealie_pipeline.adapters.web import WebFetcher

Strategy = Literal["wp_search", "wp_rest", "sitemap"]
# Listing pages on a WordPress site, never a single recipe.
_LISTING = re.compile(r"^/(category|tag|author|page|feed|search|wp-[a-z]+)(/|$)", re.IGNORECASE)
_LOC = re.compile(r"<loc>\s*([^<\s]+)\s*</loc>", re.IGNORECASE)


@dataclass(frozen=True)
class SiteMatch:
    url: str
    title: str
    score: float
    strategy: Strategy


def query_for(title: str) -> str:
    """The search words: the first title segment that names something, without filler words."""
    for segment in [*re.split(r"\s+[|–—:]\s+|\s+-\s+|\|", title), title]:
        words = links.title_words(segment)
        if words:
            return " ".join(words)
    return ""


def _best(
    candidates: list[tuple[str, str]], title: str, strategy: Strategy, min_score: float
) -> SiteMatch | None:
    best: SiteMatch | None = None
    for url, text in candidates:
        score = links.title_match(title, text)
        if score >= min_score and (best is None or score > best.score):
            best = SiteMatch(url, text, score, strategy)
    return best


def _same_site(url: str, site: str) -> bool:
    return links.host_of(url) == links.host_of(site)


def _search_page(site: str, query: str, fetcher: WebFetcher) -> list[tuple[str, str]]:
    page = fetcher.fetch(f"{site}/?s={quote_plus(query)}")
    if not page.ok:
        return []
    found: list[tuple[str, str]] = []
    for anchor in HTMLParser(page.html).css("a[href]"):
        url = urljoin(page.final_url, anchor.attributes.get("href") or "")
        parsed = urlparse(url)
        if (
            not _same_site(url, site)
            or parsed.query
            or links.is_home_page(url)
            or _LISTING.match(parsed.path)
        ):
            continue
        found.append((url, " ".join(anchor.text(separator=" ").split())))
    return found


def _rest_api(site: str, query: str, fetcher: WebFetcher) -> list[tuple[str, str]]:
    page = fetcher.fetch(
        f"{site}/wp-json/wp/v2/posts?search={quote_plus(query)}&per_page=20&_fields=link,title"
    )
    if not page.ok:
        return []
    try:
        posts = json.loads(page.html)
    except ValueError:
        return []
    if not isinstance(posts, list):  # an error object such as `rest_no_route`
        return []
    found = []
    for post in posts:
        if not isinstance(post, dict) or not isinstance(post.get("link"), str):
            continue
        rendered = (
            (post.get("title") or {}).get("rendered", "") if isinstance(post.get("title"), dict) else ""
        )
        found.append((post["link"], " ".join(html.unescape(re.sub(r"<[^>]+>", "", rendered)).split())))
    return found


def _sitemap(site: str, fetcher: WebFetcher, max_sitemaps: int) -> list[tuple[str, str]]:
    root = fetcher.fetch(f"{site}/sitemap.xml")
    if not root.ok:
        return []
    if "<sitemapindex" not in root.html.lower():
        bodies = [root.html]
    else:  # post and recipe sitemaps first: that is where the recipes are
        children = [u for u in _LOC.findall(root.html) if _same_site(u, site)]
        children.sort(key=lambda u: 0 if re.search(r"post|recipe|rezept", u, re.IGNORECASE) else 1)
        bodies = [p.html for p in (fetcher.fetch(u) for u in children[:max_sitemaps]) if p.ok]
    found = []
    for body in bodies:
        for url in _LOC.findall(html.unescape(body)):
            if _same_site(url, site) and not links.is_home_page(url):
                found.append((url, urlparse(url).path.strip("/").rsplit("/", 1)[-1]))
    return found


def search_site(
    site: str, title: str, fetcher: WebFetcher, *, min_score: float = 85, max_sitemaps: int = 5
) -> SiteMatch | None:
    """The page on `site` whose title matches the Video `title`, or None when nothing is close enough."""
    site = site.rstrip("/")
    query = query_for(title)
    if not query:
        return None
    strategies: list[tuple[Strategy, Callable[[], list[tuple[str, str]]]]] = [
        ("wp_search", lambda: _search_page(site, query, fetcher)),
        ("wp_rest", lambda: _rest_api(site, query, fetcher)),
        ("sitemap", lambda: _sitemap(site, fetcher, max_sitemaps)),
    ]
    for strategy, candidates in strategies:
        match = _best(candidates(), title, strategy, min_score)
        if match is not None:
            return match
    return None
