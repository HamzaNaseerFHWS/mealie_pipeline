"""Rule Tags and tag choice (pure): `config/tag_rules.yaml` evaluated on parsed Foods, times, Recipe
Language and drink-ness, contradiction removal, and the ranking of the final tag list."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from mealie_pipeline.protein import contains_any, tag_key


@dataclass(frozen=True)
class RecipeFacts:
    """What the rules read: the recipe name, its parsed Food names, total minutes and Recipe Language."""

    name: str
    foods: list[str]
    total_minutes: int | None
    language: str


@dataclass(frozen=True)
class TagRules:
    food_groups: dict[str, list[str]] = field(default_factory=dict)
    drink_words: list[str] = field(default_factory=list)
    rules: list[dict[str, Any]] = field(default_factory=list)  # {"tag": str, "when": {...}}
    contradictions: list[dict[str, Any]] = field(default_factory=list)  # {"tag": str, "foods_in": [...]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TagRules":
        return cls(
            food_groups={
                str(g): [str(w) for w in words or []] for g, words in (data.get("food_groups") or {}).items()
            },
            drink_words=[str(w) for w in data.get("drink_words") or []],
            rules=list(data.get("rules") or []),
            contradictions=list(data.get("contradictions") or []),
        )

    @classmethod
    def load(cls, path: Path) -> "TagRules":
        return cls.from_dict(yaml.safe_load(path.read_text(encoding="utf-8")) or {})

    def tag_names(self) -> list[str]:
        """Every tag a rule can add, for `mp doctor`."""
        return [str(rule["tag"]) for rule in self.rules]

    def _foods_in(self, foods: list[str], groups: list[str]) -> str | None:
        """The first Food that belongs to any of the named food groups, or None."""
        words = [w for g in groups for w in self.food_groups.get(g, [])]
        return next((f for f in foods if contains_any(f, words)), None)


def _holds(when: dict[str, Any], facts: RecipeFacts, rules: TagRules) -> bool:
    for condition, value in when.items():
        if condition == "no_foods_in":
            ok = rules._foods_in(facts.foods, value) is None
        elif condition == "any_foods_in":
            ok = rules._foods_in(facts.foods, value) is not None
        elif condition == "max_total_minutes":
            ok = facts.total_minutes is not None and facts.total_minutes <= value
        elif condition == "language":
            ok = facts.language in value
        elif condition == "drink":
            ok = contains_any(facts.name, rules.drink_words) == bool(value)
        else:
            raise ValueError(f"unknown tag rule condition: {condition}")
        if not ok:
            return False
    return True


def rule_tags(facts: RecipeFacts, rules: TagRules) -> list[str]:
    """The tags whose rule holds, in the config's order."""
    return [str(r["tag"]) for r in rules.rules if _holds(r.get("when") or {}, facts, rules)]


def contradictions(tags: list[str], facts: RecipeFacts, rules: TagRules) -> dict[str, str]:
    """Tag (as given) -> the Food that contradicts it, for each tag a Food rules out."""
    found: dict[str, str] = {}
    for tag in tags:
        for rule in rules.contradictions:
            if tag_key(tag) != tag_key(str(rule["tag"])):
                continue
            food = rules._foods_in(facts.foods, rule.get("foods_in") or [])
            if food is not None:
                found[tag] = food
    return found


def match_existing(name: str, existing: list[str]) -> str | None:
    """The existing tag `name` means, ignoring case, spaces and punctuation, or None."""
    key = tag_key(name)
    return next((tag for tag in existing if tag_key(tag) == key), None)


def choose(rule_chosen: list[str], llm_chosen: list[str], *, max_tags: int) -> list[str]:
    """Rule tags first, then the LLM's by rank; duplicates dropped; at most `max_tags`."""
    result: list[str] = []
    for tag in [*rule_chosen, *llm_chosen]:
        if tag_key(tag) not in {tag_key(t) for t in result}:
            result.append(tag)
    return result[:max_tags]
