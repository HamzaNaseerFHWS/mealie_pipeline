"""Unit Normalizer and Food Matcher (pure).

Both resolve a recipe's wording against the Mealie Catalog. Reuse always keeps the catalog's own
spelling; names the pipeline creates keep the pipeline's lower-case spelling. The fuzzy step is
deliberately strict: "cumin seeds" and "cumin powder" are different foods and must not merge.
"""

import re
from dataclasses import dataclass, replace
from typing import Literal

from rapidfuzz import fuzz

from mealie_pipeline.adapters.mealie import Food, Unit

FUZZY_THRESHOLD = 92
MAX_ALIAS_WORDS = 3  # a longer "name" is a sentence, not a food
# Choices ("Schnittlauch oder Petersilie"), plural markers "Tomate(n)", amounts and lists are not one food.
_NOT_ONE_FOOD = re.compile(r"[()/,;:&+\d]|\b(oder|und|wie|bzw|or|and|aus|mit|nach)\b", re.IGNORECASE)
# Words that make two otherwise similar foods different things.
DISTINGUISHING = {"seed", "seeds", "powder", "oil", "paste", "sauce", "flakes", "leaves", "juice", "milk"}

FoodMatchKind = Literal["exact", "plural", "alias", "singular", "fuzzy", "new"]
UnitMatchKind = Literal["exact", "plural", "alias", "none", "new"]


def _clean(text: str) -> str:
    return " ".join(text.lower().replace(".", " ").split())


def _aliasable(name: str) -> bool:
    return 0 < len(name.split()) <= MAX_ALIAS_WORDS and not _NOT_ONE_FOOD.search(name)


def singularize(word: str) -> str:
    """A small English singularizer: enough for food and unit names."""
    if len(word) > 3 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith(("ches", "shes", "oes", "ses", "xes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us")):
        return word[:-1]
    return word


def singular_phrase(text: str) -> str:
    words = _clean(text).split()
    return " ".join([*words[:-1], singularize(words[-1])]) if words else ""


@dataclass(frozen=True)
class UnitMatch:
    kind: UnitMatchKind
    unit: Unit | None  # None for `none`; for `new`, the name to create is `new_name`
    new_name: str = ""


@dataclass(frozen=True)
class FoodMatch:
    kind: FoodMatchKind
    food: Food | None
    new_name: str = ""
    new_alias: str = ""  # a source-language name the matched (or still to be created) Food should learn


class UnitNormalizer:
    def __init__(self, synonyms: dict[str, list[str]]):
        self._canonical: dict[str, str] = {}
        for canonical, spellings in synonyms.items():
            self._canonical[_clean(canonical)] = canonical
            for spelling in spellings:
                self._canonical[_clean(spelling)] = canonical

    def canonical(self, text: str) -> str:
        """The unit name a spelling stands for ("tbsps", "EL" -> "tablespoon"); "" for no unit."""
        raw = _clean(text)
        return self._canonical.get(raw) or self._canonical.get(singularize(raw)) or singularize(raw)

    def spellings(self) -> set[str]:
        """Every unit name and spelling in the table, cleaned."""
        return set(self._canonical)

    def match(self, text: str, units: list[Unit]) -> UnitMatch:
        raw = _clean(text)
        if not raw:
            return UnitMatch("none", None)
        by_name = {_clean(u.name): u for u in units}
        by_plural = {_clean(u.plural_name): u for u in units if u.plural_name}
        by_abbr = {_clean(u.abbreviation): u for u in units if u.abbreviation}
        if raw in by_name:
            return UnitMatch("exact", by_name[raw])
        canonical = self._canonical.get(raw) or self._canonical.get(singularize(raw))
        if canonical:
            key = _clean(canonical)
            for table in (by_name, by_plural, by_abbr):
                if key in table:
                    return UnitMatch("alias", table[key])
            return UnitMatch("new", None, canonical)
        for table in (by_plural, by_abbr):
            if raw in table:
                return UnitMatch("plural" if table is by_plural else "alias", table[raw])
        if singularize(raw) in by_name:
            return UnitMatch("plural", by_name[singularize(raw)])
        return UnitMatch("new", None, singularize(raw))


class FoodMatcher:
    def __init__(self, glossary: dict[str, str] | None = None):
        self._glossary = {_clean(k): v for k, v in (glossary or {}).items()}

    def match(self, name: str, foods: list[Food], original: str = "") -> FoodMatch:
        """`original` is the food's name in the source's own language (empty for English sources).

        A Food that already knows it wins; otherwise the English match gets it as `new_alias`.
        """
        original = _clean(original)
        if original:
            known = self._known_as(original, foods)
            if known is not None:
                return known
        found = self._match_english(name, foods)
        # A guessed (fuzzy) English match may be the wrong Food; teaching it a word would repeat the mistake.
        if original and found.kind != "fuzzy" and _aliasable(original):
            own = _clean(found.food.name) if found.food else found.new_name
            if original != own:
                return replace(found, new_alias=original)
        return found

    @staticmethod
    def _known_as(original: str, foods: list[Food]) -> FoodMatch | None:
        for food in foods:
            if original == _clean(food.name):
                return FoodMatch("exact", food)
        for food in foods:
            if original in {_clean(a) for a in food.aliases} | {_clean(food.plural_name)}:
                return FoodMatch("alias", food)
        return None

    def _match_english(self, name: str, foods: list[Food]) -> FoodMatch:
        raw = _clean(name)
        raw = _clean(self._glossary.get(raw, raw))
        singular = singular_phrase(raw)
        by_name = {_clean(f.name): f for f in foods}
        by_plural = {_clean(f.plural_name): f for f in foods if f.plural_name}
        by_alias = {_clean(a): f for f in foods for a in f.aliases}
        if raw in by_name:
            return FoodMatch("exact", by_name[raw])
        if raw in by_plural:
            return FoodMatch("plural", by_plural[raw])
        if raw in by_alias:
            return FoodMatch("alias", by_alias[raw])
        singular_names = {singular_phrase(key): food for key, food in by_name.items()}
        if singular in singular_names:
            return FoodMatch("singular", singular_names[singular])
        best = self._best_fuzzy(raw, foods)
        if best is not None:
            return FoodMatch("fuzzy", best)
        return FoodMatch("new", None, raw)

    @staticmethod
    def _best_fuzzy(raw: str, foods: list[Food]) -> Food | None:
        best, best_score = None, 0.0
        for food in foods:
            other = _clean(food.name)
            if (set(raw.split()) ^ set(other.split())) & DISTINGUISHING:
                continue
            score = fuzz.token_set_ratio(raw, other)
            if score >= FUZZY_THRESHOLD and score > best_score:
                best, best_score = food, score
        return best
