"""The `scrape` stage's logic: find the Recipe Website page a Video links to and read its recipe.

Steps: links from the description and the creator's pinned comment -> denylist -> expand short links
-> open link-in-bio pages in the Browser and keep their links that match the Video title -> rank by
the Video title -> fetch politely (a blocked page is rendered in the Browser) -> Structured Recipe
Extraction. When no link gives a recipe and the Creator's Recipe Website is known (or a bio page
named it), the site is searched for the Video title (`site_search`). The result is a plain
`WebResult` the pipeline stores under `data/<platform>/<id>/web.json` and feeds to `extract` as the
top-priority `web` Source.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from mealie_pipeline import links
from mealie_pipeline.adapters.browser import RenderedPage
from mealie_pipeline.adapters.web import WebFetcher, looks_blocked
from mealie_pipeline.recipe_extraction import SourceRecipe, extract_recipes
from mealie_pipeline.site_search import search_site

Reason = Literal["", "no_link", "no_recipe", "needs_browser", "robots", "error"]
LinkSource = Literal["description", "comment", "link_in_bio", "site_search", ""]
_MENTIONS_INGREDIENTS = re.compile(r"ingredient|zutaten", re.IGNORECASE)


class Renderer(Protocol):
    """The part of the Browser that `scrape` uses."""

    def fetch_rendered(self, url: str) -> RenderedPage: ...


def web_json_path(workspace: Path, platform: str, video_id: str) -> Path:
    return workspace / "data" / platform / video_id / "web.json"


class WebResult(BaseModel):
    reason: Reason = ""
    link: str | None = None  # the link as written in the description, comment or bio page
    final_url: str | None = None  # after redirects
    link_source: LinkSource = ""
    bio_page: str | None = None  # the link-in-bio page the link was listed on
    site_strategy: str = ""  # how site search found the page: wp_search | wp_rest | sitemap
    rendered: bool = False  # the page was read through the Browser
    website: str | None = None  # the Recipe Website this Video leads to, for the Creator registry
    website_source: Literal["video", "bio", ""] = ""
    recipes: list[SourceRecipe] = Field(default_factory=list)
    chosen: int = 0  # index in `recipes` of the best match for the Video title
    tried: list[str] = Field(default_factory=list)

    @property
    def recipe(self) -> SourceRecipe | None:
        return self.recipes[self.chosen] if self.recipes else None

    @property
    def usable(self) -> bool:
        return self.recipe is not None


def best_match(recipes: list[SourceRecipe], title: str) -> int:
    """Index of the recipe whose name is closest to the Video title (the first when unclear)."""
    if len(recipes) < 2:
        return 0
    scores = [fuzz.token_set_ratio(title.casefold(), r.name.casefold()) for r in recipes]
    return scores.index(max(scores))


def _usable(recipes: list[SourceRecipe]) -> list[SourceRecipe]:
    """Structured recipes, or main text that at least talks about ingredients (lowest priority)."""
    structured = [r for r in recipes if r.structured]
    if structured:
        return structured
    return [r for r in recipes if r.text and _MENTIONS_INGREDIENTS.search(r.text)]


@dataclass(frozen=True)
class _Link:
    written: str  # as it appears in the description, comment or on the bio page
    source: LinkSource
    anchor: str = ""  # the bio page's button text
    bio_page: str | None = None


@dataclass(frozen=True)
class _Read:
    reason: Reason
    final_url: str
    recipes: list[SourceRecipe]
    rendered: bool = False


def _read(
    url: str,
    fetcher: WebFetcher,
    browser: Renderer | None,
    render_blocked: bool,
    selectors: dict[str, dict[str, str]],
) -> _Read:
    """Fetches one page and extracts its recipes; a blocked page is rendered in the Browser once.
    A page that still shows a challenge stays `needs_browser`: it is never worked around."""
    page = fetcher.fetch(url)
    html, final_url, rendered = page.html, page.final_url, False
    if page.blocked == "needs_browser" and browser is not None and render_blocked:
        shown = browser.fetch_rendered(page.final_url)
        if not shown.ok or looks_blocked(shown.status, shown.html):
            return _Read("needs_browser", page.final_url, [])
        html, final_url, rendered = shown.html, shown.url, True
    elif page.blocked:
        return _Read(page.blocked, page.final_url, [])
    elif not page.ok:
        return _Read("error", page.final_url, [])
    recipes = _usable(extract_recipes(html, final_url, selectors))
    return _Read("" if recipes else "no_recipe", final_url, recipes, rendered)


def _bio_links(
    bio_url: str, title: str, fetcher: WebFetcher, browser: Renderer, min_score: float
) -> tuple[dict[str, _Link], str | None]:
    """The links on a link-in-bio page that match the Video title, and the Creator's website when
    the page links a home page (`My blog`)."""
    page = browser.fetch_rendered(bio_url)
    if not page.ok:
        return {}, None
    found: dict[str, _Link] = {}
    website = None
    for link in links.bio_links(page.html, page.url):
        target = fetcher.expand(link.url) if links.is_short_link(link.url) else link.url
        if links.is_denied(target):
            continue
        if links.is_home_page(target):
            website = website or links.website_of(target)
            continue
        slug = target.rstrip("/").rsplit("/", 1)[-1]
        if max(links.title_match(title, link.text), links.title_match(title, slug)) >= min_score:
            found.setdefault(target, _Link(link.url, "link_in_bio", link.text, bio_url))
    return found, website


def find_web_recipe(
    *,
    title: str,
    description: str,
    pinned_comment: str,
    fetcher: WebFetcher,
    selectors: dict[str, dict[str, str]],
    max_pages: int = 3,
    browser: Renderer | None = None,
    link_in_bio_hosts: Iterable[str] = links.LINK_IN_BIO_HOSTS,
    bio_min_score: float = 70,
    render_blocked: bool = True,
    site_search: bool = True,
    creator_site: str | None = None,
    site_search_min_score: float = 85,
) -> WebResult:
    """`browser` None never renders anything (link-in-bio pages are then dropped like other socials)."""
    bio_hosts = list(link_in_bio_hosts) if browser is not None else []
    match_title = links.video_title(title, description)
    origin: dict[str, LinkSource] = {}
    for label, text in (("description", description), ("comment", pinned_comment)):
        for url in links.candidates(text, keep=bio_hosts):
            origin.setdefault(url, label)  # type: ignore[arg-type]

    # Short links hide the real destination: expand them, open link-in-bio pages, drop the denylist.
    found: dict[str, _Link] = {}  # final url -> where it came from
    bio_site: str | None = None
    for url, label in origin.items():
        final = fetcher.expand(url) if links.is_short_link(url) else url
        if browser is not None and links.is_link_in_bio(final, bio_hosts):
            listed, website = _bio_links(final, match_title, fetcher, browser, bio_min_score)
            for target, link in listed.items():
                found.setdefault(target, link)
            bio_site = bio_site or website
        elif not links.is_denied(final):
            found.setdefault(final, _Link(url, label))

    result = WebResult(reason="no_recipe" if found else "no_link")
    anchors = {url: link.anchor for url, link in found.items() if link.anchor}
    for final in links.rank_links(list(found), match_title, anchors)[:max_pages]:
        link = found[final]
        result.tried.append(final)
        read = _read(final, fetcher, browser, render_blocked, selectors)
        result.reason = read.reason
        if read.recipes:
            return WebResult(
                link=link.written,
                final_url=read.final_url,
                link_source=link.source,
                bio_page=link.bio_page,
                rendered=read.rendered,
                website=links.website_of(read.final_url),
                website_source="video",
                recipes=read.recipes,
                chosen=best_match(read.recipes, match_title),
                tried=result.tried,
            )

    if bio_site:
        result.website, result.website_source = bio_site, "bio"
    site = creator_site or bio_site
    if site_search and site and result.reason in ("no_link", "no_recipe"):
        match = search_site(site, match_title, fetcher, min_score=site_search_min_score)
        if match is not None:
            result.tried.append(match.url)
            read = _read(match.url, fetcher, browser, render_blocked, selectors)
            if read.recipes:
                return result.model_copy(
                    update={
                        "reason": "",
                        "link": match.url,
                        "final_url": read.final_url,
                        "link_source": "site_search",
                        "site_strategy": match.strategy,
                        "rendered": read.rendered,
                        "recipes": read.recipes,
                        "chosen": best_match(read.recipes, match_title),
                    }
                )
    return result
