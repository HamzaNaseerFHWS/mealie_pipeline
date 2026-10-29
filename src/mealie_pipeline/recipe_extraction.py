"""Structured Recipe Extraction (pure): page HTML -> `SourceRecipe`s, with the method that found them.

Order: JSON-LD (including `@graph`), microdata / RDFa, recipe-card plugin HTML (selectors from
`config/site_selectors.yaml`), `recipe-scrapers`, then the main text as a last resort. A page with
several Recipe objects returns all of them (ticket 12 splits them); callers take the best match.
"""

import html
import re
from typing import Any

import extruct
import trafilatura
from pydantic import BaseModel, Field
from selectolax.lexbor import LexborHTMLParser as HTMLParser
from selectolax.lexbor import LexborNode as Node


class SourceIngredient(BaseModel):
    text: str
    section: str | None = None


class SourceStep(BaseModel):
    text: str
    section: str | None = None


class SourceRecipe(BaseModel):
    name: str = ""
    ingredients: list[SourceIngredient] = Field(default_factory=list)
    steps: list[SourceStep] = Field(default_factory=list)
    yield_text: str | None = None
    prep_minutes: int | None = None
    cook_minutes: int | None = None
    total_minutes: int | None = None
    image: str | None = None
    # json-ld | microdata | rdfa | card:<plugin> | recipe-scrapers | main-text
    extraction_method: str = ""
    text: str = ""  # main-text fallback only

    @property
    def structured(self) -> bool:
        return bool(self.ingredients) and bool(self.steps)


_DURATION = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?$", re.IGNORECASE)


def parse_duration(value: Any) -> int | None:
    """`PT1H30M` -> 90; anything that is not an ISO-8601 duration -> None."""
    if not isinstance(value, str):
        return None
    match = _DURATION.match(value.strip())
    if not match or not any(match.groups()):
        return None
    days, hours, minutes = (int(g) if g else 0 for g in match.groups())
    return days * 1440 + hours * 60 + minutes


def _clean(text: Any) -> str:
    return " ".join(html.unescape(str(text)).split())  # some sites double-encode: "&#190; cup"


def _key(name: str) -> str:
    """`http://schema.org/recipeIngredient` / `recipeIngredient` -> `recipeingredient`."""
    return re.split(r"[/#]", name)[-1].lower()


def _get(item: dict[str, Any], *names: str) -> Any:
    """The value of the first of `names` the item has (in the order given, not the item's own order)."""
    keyed = {}
    for key, value in item.items():
        keyed.setdefault(_key(key), value)
    for name in names:
        if name.lower() in keyed:
            return keyed[name.lower()]
    return None


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _text_of(value: Any) -> str:
    if isinstance(value, dict):
        inner = _get(value, "text", "name", "@value", "value")
        return _clean(_text_of(inner)) if inner is not None else ""
    if isinstance(value, list):
        return _clean(" ".join(_text_of(v) for v in value))
    return _clean(value) if value is not None else ""


def _image_url(value: Any) -> str | None:
    for item in _as_list(value):
        if isinstance(item, str) and item.strip():
            return item.strip()
        if isinstance(item, dict):
            url = _get(item, "url", "contenturl", "@id", "@value")
            if isinstance(url, str) and url.strip():
                return url.strip()
    return None


def _steps(value: Any, section: str | None = None) -> list[SourceStep]:
    steps: list[SourceStep] = []
    if isinstance(value, str):
        for line in re.split(r"\r?\n+", value):
            if _clean(line):
                steps.append(SourceStep(text=_clean(line), section=section))
        return steps
    for item in _as_list(value):
        if isinstance(item, str):
            steps += _steps(item, section)
        elif isinstance(item, dict):
            children = _get(item, "itemlistelement")
            types = {_key(t) for t in _as_list(_get(item, "@type", "type")) if isinstance(t, str)}
            if children is not None and ("howtosection" in types or _get(item, "text") is None):
                steps += _steps(children, _text_of(_get(item, "name")) or section)
            else:
                text = _text_of(_get(item, "text", "name", "description"))
                if text:
                    steps.append(SourceStep(text=text, section=section))
    return steps


def _is_recipe(item: Any) -> bool:
    return isinstance(item, dict) and any(
        _key(t) == "recipe" for t in _as_list(_get(item, "@type", "type")) if isinstance(t, str)
    )


def _walk(node: Any) -> list[dict[str, Any]]:
    """Every Recipe object anywhere inside JSON-LD (lists, `@graph`, nested objects)."""
    found: list[dict[str, Any]] = []
    if isinstance(node, list):
        for child in node:
            found += _walk(child)
    elif isinstance(node, dict):
        if _is_recipe(node):
            found.append(node)
        else:
            for value in node.values():
                if isinstance(value, list | dict):
                    found += _walk(value)
    return found


def _from_schema(item: dict[str, Any], method: str) -> SourceRecipe:
    if isinstance(item.get("properties"), dict):  # extruct's microdata shape: {type, properties}
        item = item["properties"]
    yields = [_text_of(v) for v in _as_list(_get(item, "recipeyield", "yield")) if _text_of(v)]
    return SourceRecipe(
        name=_text_of(_get(item, "name")),
        ingredients=[
            SourceIngredient(text=t)
            for t in (_text_of(i) for i in _as_list(_get(item, "recipeingredient", "ingredients")))
            if t
        ],
        steps=_steps(_get(item, "recipeinstructions")),
        yield_text=yields[0] if yields else None,
        prep_minutes=parse_duration(_text_of(_get(item, "preptime"))),
        cook_minutes=parse_duration(_text_of(_get(item, "cooktime", "performtime"))),
        total_minutes=parse_duration(_text_of(_get(item, "totaltime"))),
        image=_image_url(_get(item, "image")),
        extraction_method=method,
    )


def _text(node: Node | None) -> str:
    return _clean(node.text(separator=" ")) if node is not None else ""


def _grouped(
    container: Node, group_sel: str | None, title_sel: str | None, item_sel: str
) -> list[tuple[str | None, str]]:
    groups = container.css(group_sel) if group_sel else []
    if not groups:
        return [(None, _text(n)) for n in container.css(item_sel) if _text(n)]
    result: list[tuple[str | None, str]] = []
    for group in groups:
        title = _text(group.css_first(title_sel)) if title_sel else ""
        result += [(title or None, _text(n)) for n in group.css(item_sel) if _text(n)]
    return result


def _read_card(container: Node, sel: dict[str, str], method: str) -> SourceRecipe:
    image = container.css_first(sel["image"]) if sel.get("image") else None
    src = (image.attributes.get("data-lazy-src") or image.attributes.get("src")) if image else None
    yield_node = container.css_first(sel["yield"]) if sel.get("yield") else None
    return SourceRecipe(
        name=_text(container.css_first(sel["name"])) if sel.get("name") else "",
        ingredients=[
            SourceIngredient(text=t, section=s)
            for s, t in _grouped(
                container, sel.get("ingredient_group"), sel.get("group_title"), sel["ingredient"]
            )
        ],
        steps=[
            SourceStep(text=t, section=s)
            for s, t in _grouped(container, sel.get("step_group"), sel.get("step_group_title"), sel["step"])
        ],
        yield_text=_text(yield_node) or None,
        image=src,
        extraction_method=method,
    )


def _from_cards(html: str, selectors: dict[str, dict[str, str]]) -> list[SourceRecipe]:
    tree = HTMLParser(html)
    for plugin, sel in selectors.items():
        recipes = [_read_card(c, sel, f"card:{plugin}") for c in tree.css(sel["container"])]
        recipes = [r for r in recipes if r.structured]
        if recipes:
            return recipes
    return []


def _from_recipe_scrapers(html: str, url: str) -> list[SourceRecipe]:
    from recipe_scrapers import scrape_html

    try:
        scraper = scrape_html(html, org_url=url, supported_only=False)
        ingredients = [SourceIngredient(text=_clean(i)) for i in scraper.ingredients() if _clean(i)]
        steps = [SourceStep(text=_clean(s)) for s in scraper.instructions_list() if _clean(s)]
        name = _safe(scraper.title)
        yields = _safe(scraper.yields)
        image = _safe(scraper.image)
        total = _safe_int(scraper.total_time)
    except Exception:  # the library raises many things on pages it cannot read
        return []
    if not ingredients or not steps:
        return []
    return [
        SourceRecipe(
            name=name,
            ingredients=ingredients,
            steps=steps,
            yield_text=yields or None,
            total_minutes=total,
            image=image or None,
            extraction_method="recipe-scrapers",
        )
    ]


def _safe(call: Any) -> str:
    try:
        return _clean(call() or "")
    except Exception:
        return ""


def _safe_int(call: Any) -> int | None:
    try:
        value = call()
        return int(value) if value else None
    except Exception:
        return None


def extract_recipes(html: str, url: str, selectors: dict[str, dict[str, str]]) -> list[SourceRecipe]:
    """All recipes on a page, found by the first method that finds any; never raises on odd HTML."""
    try:
        data = extruct.extract(html, base_url=url, syntaxes=["json-ld", "microdata", "rdfa"], errors="ignore")
    except Exception:
        data = {}
    for syntax in ("json-ld", "microdata", "rdfa"):
        found = [_from_schema(r, syntax) for r in _walk(data.get(syntax) or [])]
        found = [r for r in found if r.structured]
        if found:
            return found
    cards = _from_cards(html, selectors)
    if cards:
        return cards
    scraped = _from_recipe_scrapers(html, url)
    if scraped:
        return scraped
    try:
        text = trafilatura.extract(html, url=url, include_comments=False, include_tables=False) or ""
    except Exception:
        text = ""
    return [SourceRecipe(extraction_method="main-text", text=text.strip())] if text.strip() else []


def format_for_prompt(recipe: SourceRecipe) -> str:
    """The recipe as plain text for a `[SRC:web]` block (also what Evidence quotes are checked against)."""
    if not recipe.structured:
        return recipe.text
    lines = [recipe.name]
    if recipe.yield_text:
        lines.append(f"Yield: {recipe.yield_text}")
    for label, minutes in (
        ("Prep time", recipe.prep_minutes),
        ("Cook time", recipe.cook_minutes),
        ("Total time", recipe.total_minutes),
    ):
        if minutes:
            lines.append(f"{label}: {minutes} minutes")
    lines += ["", "Ingredients"]
    section = None
    for ingredient in recipe.ingredients:
        if ingredient.section != section:
            section = ingredient.section
            if section:
                lines.append(f"{section}:")
        lines.append(ingredient.text)
    lines += ["", "Instructions"]
    section = None
    for number, step in enumerate(recipe.steps, start=1):
        if step.section != section:
            section = step.section
            if section:
                lines.append(f"{section}:")
        lines.append(f"{number}. {step.text}")
    return "\n".join(lines)
