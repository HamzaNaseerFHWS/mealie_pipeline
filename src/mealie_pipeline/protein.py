"""Protein Tags (pure): which main proteins a recipe has, by the word lists in `config/protein_tags.yaml`.

Deterministic and LLM-free. The same detection runs in the tag stage (new recipes) and in the
`mp tags protein` backfill over every recipe already in Mealie.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

WORD = re.compile(r"\w+")


def tag_key(name: str) -> str:
    """How tag names are compared with Mealie's: ignoring case, spaces and punctuation."""
    return re.sub(r"[\W_]+", "", name.casefold())


def _words(text: str) -> list[str]:
    return WORD.findall(text.casefold())


@dataclass(frozen=True)
class _Phrase:
    """A match phrase: words in a row; a last word ending in `*` matches by its start."""

    words: tuple[str, ...]
    prefix: bool

    @classmethod
    def parse(cls, text: str) -> "_Phrase":
        prefix = text.strip().endswith("*")
        return cls(tuple(_words(text)), prefix)

    def matches_at(self, tokens: list[str], start: int) -> bool:
        if start + len(self.words) > len(tokens):
            return False
        last = len(self.words) - 1
        for offset, word in enumerate(self.words):
            token = tokens[start + offset]
            if offset == last and self.prefix:
                if not token.startswith(word):
                    return False
            elif not _same_word(token, word):
                return False
        return True


def _same_word(token: str, word: str) -> bool:
    """Whole word, allowing simple plurals both ways ("egg"/"eggs", "chickpeas"/"chickpea")."""
    if token in (word, word + "s", word + "es") or (word.endswith("s") and token == word[:-1]):
        return True
    return word.endswith("y") and token == word[:-1] + "ies"


@dataclass(frozen=True)
class RecipeText:
    """What detection reads: the recipe name, one text per ingredient, and the tags it already has."""

    name: str
    ingredients: list[str]
    tags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProteinRules:
    tags: dict[str, list[str]]  # tag name -> its words, in the config's order
    exclude: list[str] = field(default_factory=list)
    not_main: list[str] = field(default_factory=list)
    sweet_tags: list[str] = field(default_factory=list)
    sweet_words: list[str] = field(default_factory=list)
    sweet_skip: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, path: Path) -> "ProteinRules":
        data: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sweet = data.get("sweet") or {}
        return cls(
            tags={
                str(name): [str(w) for w in words or []] for name, words in (data.get("tags") or {}).items()
            },
            exclude=[str(w) for w in data.get("exclude") or []],
            not_main=[str(w) for w in data.get("not_main") or []],
            sweet_tags=[str(w) for w in sweet.get("tags") or []],
            sweet_words=[str(w) for w in sweet.get("words") or []],
            sweet_skip=[str(w) for w in sweet.get("skip") or []],
        )

    def canonical(self, name: str) -> str | None:
        """The configured Protein Tag name that `name` means (any case or punctuation), or None."""
        key = tag_key(name)
        return next((tag for tag in self.tags if tag_key(tag) == key), None)


def _phrase_table(rules: ProteinRules) -> list[tuple[_Phrase, str | None]]:
    """Every phrase with its tag (None for an exclusion), longest first; exclusions win ties."""
    table: list[tuple[_Phrase, str | None]] = [(_Phrase.parse(w), None) for w in rules.exclude]
    table += [(_Phrase.parse(w), tag) for tag, words in rules.tags.items() for w in words]
    return sorted(table, key=lambda item: (-len(item[0].words), item[1] is not None))


def _find(text: str, table: list[tuple[_Phrase, str | None]]) -> list[tuple[str, str]]:
    """(tag, matched text) for each phrase found; a word belongs to the first (longest) phrase only."""
    tokens = _words(text)
    used = [False] * len(tokens)
    found: list[tuple[int, str, str]] = []
    for phrase, tag in table:
        for start in range(len(tokens)):
            span = range(start, start + len(phrase.words))
            if any(used[i] for i in span if i < len(used)) or not phrase.matches_at(tokens, start):
                continue
            for i in span:
                used[i] = True
            if tag is not None:
                found.append((start, tag, " ".join(tokens[i] for i in span)))
    return [(tag, words) for _start, tag, words in sorted(found)]


def _has_any(text: str, phrases: list[str]) -> bool:
    tokens = _words(text)
    parsed = [_Phrase.parse(p) for p in phrases]
    return any(p.matches_at(tokens, start) for p in parsed for start in range(len(tokens)))


def detect(recipe: RecipeText, rules: ProteinRules) -> dict[str, list[str]]:
    """The recipe's main proteins: Protein Tag -> the words that triggered it, in the config's order.

    A protein in the name always counts. Ingredient lines marked optional, garnish or "to serve"
    don't, and neither do eggs or cheese in desserts, baked goods and drinks."""
    table = _phrase_table(rules)
    sweet_tags = {tag_key(t) for t in rules.sweet_tags}
    sweet = any(tag_key(t) in sweet_tags for t in recipe.tags) or _has_any(recipe.name, rules.sweet_words)
    skipped = {tag_key(t) for t in rules.sweet_skip} if sweet else set()

    triggers: dict[str, list[str]] = {}

    def add(tag: str, words: str) -> None:
        seen = triggers.setdefault(tag, [])
        if words not in seen:
            seen.append(words)

    for tag, words in _find(recipe.name, table):
        add(tag, words)
    for line in recipe.ingredients:
        if _has_any(line, rules.not_main):
            continue
        for tag, words in _find(line, table):
            if tag_key(tag) not in skipped:
                add(tag, words)
    return {tag: triggers[tag] for tag in rules.tags if tag in triggers}


def mealie_recipe_text(recipe: dict[str, Any]) -> RecipeText:
    """A Mealie recipe as detection reads it: linked Food names for parsed ingredients, and the
    `note`, `originalText` and `display` text of older imports whose ingredients are unparsed."""
    lines = []
    for ingredient in recipe.get("recipeIngredient") or []:
        food = (ingredient.get("food") or {}).get("name") or ""
        parts = [food, *(ingredient.get(k) or "" for k in ("note", "originalText", "display"))]
        lines.append(" | ".join(p for p in parts if p))
    tags = [t.get("name") or "" for t in recipe.get("tags") or []]
    return RecipeText(recipe.get("name") or "", lines, tags)


def is_unparsed(recipe: dict[str, Any]) -> bool:
    """No ingredient is linked to a Food (an older import whose lines are plain text)."""
    return not any((i.get("food") or {}).get("id") for i in recipe.get("recipeIngredient") or [])


def contains_any(text: str, phrases: list[str]) -> bool:
    """Whether `text` holds any of the phrases (whole words, simple plurals, `*` prefixes)."""
    return _has_any(text, phrases)
