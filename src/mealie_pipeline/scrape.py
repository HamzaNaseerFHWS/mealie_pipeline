"""The `scrape` stage's logic: find the Recipe Website page a Video links to and read its recipe.

Steps: links from the description and the creator's pinned comment -> denylist -> expand short links
-> rank by the Video title -> fetch politely -> Structured Recipe Extraction. The result is a plain
`WebResult` the pipeline stores under `data/<platform>/<id>/web.json` and feeds to `extract` as the
top-priority `web` Source.
"""

import re
from typing import Literal

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from mealie_pipeline import links
from mealie_pipeline.adapters.web import WebFetcher
from mealie_pipeline.recipe_extraction import SourceRecipe, extract_recipes

Reason = Literal["", "no_link", "no_recipe", "needs_browser", "robots", "error"]
_MENTIONS_INGREDIENTS = re.compile(r"ingredient|zutaten", re.IGNORECASE)


class WebResult(BaseModel):
    reason: Reason = ""
    link: str | None = None  # the link as written in the description or comment
    final_url: str | None = None  # after redirects
    link_source: Literal["description", "comment", ""] = ""
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


def find_web_recipe(
    *,
    title: str,
    description: str,
    pinned_comment: str,
    fetcher: WebFetcher,
    selectors: dict[str, dict[str, str]],
    max_pages: int = 3,
) -> WebResult:
    sources = [("description", description), ("comment", pinned_comment)]
    origin: dict[str, str] = {}
    for label, text in sources:
        for url in links.candidates(text):
            origin.setdefault(url, label)
    if not origin:
        return WebResult(reason="no_link")

    # Short links hide the real destination: expand them, then drop anything on the denylist.
    resolved: dict[str, str] = {}  # final url -> link as written
    for url, _ in origin.items():
        final = fetcher.expand(url) if links.is_short_link(url) else url
        if not links.is_denied(final):
            resolved.setdefault(final, url)
    if not resolved:
        return WebResult(reason="no_link")

    result = WebResult(reason="no_recipe")
    for final in links.rank_links(list(resolved), title)[:max_pages]:
        written = resolved[final]
        result.tried.append(final)
        page = fetcher.fetch(final)
        if page.blocked:
            result.reason = (
                "robots"
                if page.blocked == "robots"
                else ("needs_browser" if page.blocked == "needs_browser" else "error")
            )
            continue
        if not page.ok:
            result.reason = "error"
            continue
        recipes = _usable(extract_recipes(page.html, page.final_url, selectors))
        if recipes:
            return WebResult(
                reason="",
                link=written,
                final_url=page.final_url,
                link_source=origin[written],  # type: ignore[arg-type]
                recipes=recipes,
                chosen=best_match(recipes, title),
                tried=result.tried,
            )
        result.reason = "no_recipe"
    return result
