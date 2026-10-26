"""Finding the right recipe page for a name (pure): queries, filtering, scoring, the decision.

A candidate is a fetched page that yields exactly one real recipe. Scores are 0..1 from the name's
similarity, how the recipe was found on the page, how complete it is, and whether the page language
fits. The best candidate is accepted when it clears the threshold and leads by a margin; otherwise the
user picks from the top three.
"""

import re
from dataclasses import dataclass, field
from typing import Any, Literal

from rapidfuzz import fuzz

from mealie_pipeline import links
from mealie_pipeline.adapters.search import SearchHit
from mealie_pipeline.recipe_extraction import SourceRecipe
from mealie_pipeline.settings import FindSettings
from mealie_pipeline.url_normalizer import normalize_website

Decision = Literal["found", "needs_choice", "not_found"]

GERMAN_WORDS = {
    "suppe", "salat", "brot", "nudel", "nudeln", "kartoffel", "kartoffeln", "käse", "huhn", "hähnchen",
    "fisch", "eier", "gemüse", "zwiebel", "zwiebeln", "brei", "kuchen", "auflauf", "aufstrich",
    "püree", "pfanne", "mit", "und", "auf", "aus", "im", "vom", "grießbrei", "reis", "knödel",
    "schwarzbrot", "brötchen", "frischkäse", "kürbissuppe", "bällchen", "stäbchen", "möhren",
    "karotten", "pilze", "bohnen", "linsen", "erdbeeren", "sahne", "windbeutel", "pfannkuchen",
}  # fmt: skip
# German compounds end in these ("Linsensuppe", "Kartoffelpuffer"). "salat" is left out: also English.
GERMAN_ENDINGS = (
    "suppe",
    "brei",
    "kuchen",
    "brot",
    "nudeln",
    "puffer",
    "knödel",
    "auflauf",
    "bällchen",
    "stäbchen",
)
NOISE_WORDS = {
    "recipe", "recipes", "rezept", "rezepte", "easy", "best", "simple", "quick", "the", "a", "authentic",
    "homemade", "how", "to", "make", "einfach", "einfaches", "bestes", "style", "mit", "und", "and", "with",
}  # fmt: skip
STRUCTURE_QUALITY = {"json-ld": 1.0, "microdata": 0.9, "rdfa": 0.9, "recipe-scrapers": 0.7, "main-text": 0.0}
_LANG_ATTR = re.compile(r"<html[^>]*\blang\s*=\s*[\"']?([a-zA-Z]{2})", re.IGNORECASE)
_IN_LANGUAGE = re.compile(r"\"inLanguage\"\s*:\s*\"([a-zA-Z]{2})", re.IGNORECASE)
_DEVANAGARI = re.compile(r"[ऀ-ॿ]")
_ARABIC = re.compile(r"[؀-ۿ]")


def guess_language(name: str) -> str:
    """`de` for German-looking names, `hi`/`ur` for Devanagari/Arabic script, else `en`.

    The sheet's own `language` column always wins over this guess."""
    if _DEVANAGARI.search(name):
        return "hi"
    if _ARABIC.search(name):
        return "ur"
    lowered = name.lower()  # not casefold(): it turns ß into ss
    words = set(re.findall(r"[^\W\d_]+", lowered))
    strong = words & GERMAN_WORDS - {"mit", "und", "auf", "aus", "im", "vom"}
    compound = any(w.endswith(GERMAN_ENDINGS) and w not in {"salat"} or w in GERMAN_WORDS for w in words)
    if re.search(r"[äöüß]", lowered) or strong or compound:
        return "de"
    return "de" if len(words & GERMAN_WORDS) >= 2 else "en"


def build_query(name: str, language: str, hint: str | None, cfg: FindSettings) -> str:
    template = cfg.query_templates.get(language) or cfg.query_templates.get(
        cfg.default_language, "{name} recipe"
    )
    query = template.format(name=name.strip())
    return f"{query} {hint.strip()}" if hint and hint.strip() else query


@dataclass(frozen=True)
class SitePolicy:
    deny_domains: tuple[str, ...] = ()
    listicle_patterns: tuple[re.Pattern[str], ...] = ()

    @classmethod
    def from_config(cls, data: dict[str, Any] | None) -> "SitePolicy":
        data = data or {}
        return cls(
            tuple(str(d).lower() for d in data.get("deny_domains") or []),
            tuple(re.compile(p, re.IGNORECASE) for p in data.get("listicle_title_patterns") or []),
        )

    def rejects(self, hit: SearchHit) -> bool:
        host = links.host_of(hit.url)
        if links.is_denied(hit.url) or any(host == d or host.endswith("." + d) for d in self.deny_domains):
            return True
        return any(p.search(hit.title) for p in self.listicle_patterns)


def filter_hits(
    hits: list[SearchHit], policy: SitePolicy, keep: int, skip: set[str] | None = None
) -> list[SearchHit]:
    """Drops denylisted domains, listicle titles, unusable addresses and duplicates (after URL
    normalization); keeps the first `keep` in search order. `skip` holds keys already tried."""
    seen = set(skip or ())
    kept: list[SearchHit] = []
    for hit in hits:
        key = normalize_website(hit.url)
        if key is None or key in seen or policy.rejects(hit):
            continue
        seen.add(key)
        kept.append(hit)
        if len(kept) == keep:
            break
    return kept


def page_language(html: str) -> str | None:
    match = _LANG_ATTR.search(html[:5000]) or _IN_LANGUAGE.search(html)
    return match.group(1).lower() if match else None


def single_recipe(recipes: list[SourceRecipe]) -> SourceRecipe | None:
    """The page's recipe when it holds exactly one real one (>= 2 ingredients, >= 1 step, found through
    structured data or a recipe card). Lists of recipes and text-only pages are not candidates."""
    real = [
        r for r in recipes if r.structured and len(r.ingredients) >= 2 and r.extraction_method != "main-text"
    ]
    return real[0] if len(real) == 1 else None


def _name_words(name: str) -> str:
    return " ".join(w for w in re.findall(r"[^\W\d_]+", name.casefold()) if w not in NOISE_WORDS)


def name_similarity(requested: str, found: str) -> float:
    a, b = _name_words(requested), _name_words(found)
    if not a or not b:
        return 0.0
    return (0.7 * fuzz.token_set_ratio(a, b) + 0.3 * fuzz.token_sort_ratio(a, b)) / 100


def completeness(recipe: SourceRecipe) -> float:
    return round(
        0.3 * min(1.0, len(recipe.ingredients) / 4)
        + 0.3 * min(1.0, len(recipe.steps) / 3)
        + 0.15 * bool(recipe.prep_minutes or recipe.cook_minutes or recipe.total_minutes)
        + 0.1 * bool(recipe.yield_text)
        + 0.15 * bool(recipe.image),
        4,
    )


def language_fit(wanted: str, page: str | None) -> float:
    if page is None:
        return 0.5
    if wanted == "de":
        return 1.0 if page == "de" else 0.3
    if wanted == "en":
        return 1.0 if page == "en" else 0.3
    return 1.0 if page in ("en", wanted) else 0.5  # desi recipes are usually written in English


@dataclass
class Candidate:
    url: str
    title: str
    recipe_name: str
    score: float
    parts: dict[str, float]
    method: str
    ingredient_preview: list[str] = field(default_factory=list)
    search_title: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "title": self.recipe_name,
            "search_title": self.search_title,
            "score": self.score,
            "parts": self.parts,
            "method": self.method,
            "ingredient_preview": self.ingredient_preview,
        }


def score_candidate(
    requested: str,
    wanted_language: str,
    url: str,
    recipe: SourceRecipe,
    html: str,
    cfg: FindSettings,
    search_title: str = "",
) -> Candidate | None:
    """None when the recipe's name is too unlike the request to be a candidate at all."""
    similarity = name_similarity(requested, recipe.name or search_title)
    if similarity < cfg.min_name_similarity:
        return None
    method = recipe.extraction_method
    parts = {
        "name": round(similarity, 4),
        "structure": STRUCTURE_QUALITY.get(method.split(":")[0], 0.85 if method.startswith("card") else 0.5),
        "completeness": completeness(recipe),
        "language": language_fit(wanted_language, page_language(html)),
    }
    total = sum(cfg.weights.get(k, 0.0) * v for k, v in parts.items()) / (sum(cfg.weights.values()) or 1)
    return Candidate(
        url=url,
        title=recipe.name,
        recipe_name=recipe.name,
        score=round(total, 4),
        parts=parts,
        method=method,
        ingredient_preview=[i.text for i in recipe.ingredients[:4]],
        search_title=search_title,
    )


def decide(candidates: list[Candidate], cfg: FindSettings) -> tuple[Decision, list[Candidate]]:
    """`found` (best clears the threshold with a lead), `needs_choice` (top 3) or `not_found`."""
    ranked = sorted(candidates, key=lambda c: c.score, reverse=True)
    if not ranked:
        return "not_found", []
    best = ranked[0]
    lead = best.score - ranked[1].score if len(ranked) > 1 else 1.0
    if best.score >= cfg.accept_score and lead >= cfg.accept_lead:
        return "found", ranked[:3]
    return "needs_choice", ranked[:3]
