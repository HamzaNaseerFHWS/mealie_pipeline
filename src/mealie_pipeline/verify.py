"""The deterministic half of the Gate (pure): hard checks H1-H5, soft checks and the score.

Ungrounded ingredients are dropped here (together with their parsed counterpart, which is
index-aligned with the extracted ingredient). The LLM judge and the retry live in the pipeline.
"""

from dataclasses import dataclass, field
from typing import Any

from mealie_pipeline import checks, grounding
from mealie_pipeline.models import ExtractedRecipe, ParsedIngredient
from mealie_pipeline.scoring import Component, quality_score
from mealie_pipeline.settings import VerifySettings


@dataclass(frozen=True)
class CheckResult:
    check_id: str
    kind: str  # "hard" | "soft"
    passed: bool
    score: float | None  # soft checks only; None = does not apply yet
    details: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.check_id,
            "kind": self.kind,
            "passed": self.passed,
            "score": self.score,
            "details": self.details,
        }


@dataclass
class Evaluation:
    recipe: ExtractedRecipe  # after dropping ungrounded ingredients
    parsed: list[ParsedIngredient]
    dropped: list[str]  # `original_line` of each dropped ingredient
    checks: list[CheckResult] = field(default_factory=list)
    score: float = 0.0

    @property
    def hard_failures(self) -> list[str]:
        return [c.check_id for c in self.checks if c.kind == "hard" and not c.passed]

    @property
    def failed_checks(self) -> list[str]:
        return [c.check_id for c in self.checks if not c.passed]

    def findings(self) -> list[str]:
        return [f"{c.check_id}: {c.details}" for c in self.checks if not c.passed]


def evaluate(
    recipe: ExtractedRecipe,
    parsed: list[ParsedIngredient],
    tags: list[dict[str, Any]],
    sources: dict[str, str],
    known_foods: list[str],
    cfg: VerifySettings,
) -> Evaluation:
    bad_ingredients = grounding.ungrounded_ingredients(recipe.ingredients, sources, cfg.grounding_threshold)
    bad_steps = grounding.ungrounded_steps(recipe.instructions, sources, cfg.grounding_threshold)
    total = len(recipe.ingredients)
    dropped_fraction = len(bad_ingredients) / total if total else 0.0
    step_fraction = len(bad_steps) / len(recipe.instructions) if recipe.instructions else 0.0

    kept = [i for i in range(total) if i not in set(bad_ingredients)]
    kept_recipe = recipe.model_copy(update={"ingredients": [recipe.ingredients[i] for i in kept]})
    kept_parsed = [parsed[i] for i in kept if i < len(parsed)]
    evaluation = Evaluation(
        recipe=kept_recipe,
        parsed=kept_parsed,
        dropped=[recipe.ingredients[i].original_line or recipe.ingredients[i].line for i in bad_ingredients],
    )
    add = evaluation.checks.append
    is_named_recipe = recipe.is_recipe and bool(recipe.name.strip())

    add(
        CheckResult(
            "H1",
            "hard",
            is_named_recipe,
            None,
            "is a recipe with a name"
            if recipe.is_recipe and recipe.name.strip()
            else "not a recipe or no name",
        )
    )
    enough = len(kept_recipe.ingredients) >= 2 and len(recipe.instructions) >= 1
    add(
        CheckResult(
            "H2",
            "hard",
            enough,
            None,
            f"{len(kept_recipe.ingredients)} ingredients and {len(recipe.instructions)} steps"
            + ("" if enough else " (needs at least 2 ingredients and 1 step)"),
        )
    )
    h3_ok = dropped_fraction <= cfg.max_dropped_fraction and step_fraction <= cfg.max_dropped_fraction
    detail = (
        f"{len(bad_ingredients)} of {total} ingredients and {len(bad_steps)} of "
        f"{len(recipe.instructions)} steps not found in the sources"
    )
    if evaluation.dropped:
        detail += "; dropped: " + " | ".join(evaluation.dropped)
    add(CheckResult("H3", "hard", h3_ok, None, detail))
    missing_food = [p.original_text for p in kept_parsed if not p.food_id]
    add(
        CheckResult(
            "H4",
            "hard",
            not missing_food,
            None,
            "every ingredient has a Food" if not missing_food else "no Food for: " + " | ".join(missing_food),
        )
    )
    add(CheckResult("H5", "hard", bool(tags), None, f"{len(tags)} tags"))

    s2, s2_details = checks.ingredients_vs_steps(
        [p.food_name for p in kept_parsed],
        [s.text for s in recipe.instructions],
        known_foods,
        [p.food_original for p in kept_parsed],
    )
    s6, s6_details = checks.plausibility(
        recipe.servings, recipe.prep_minutes, recipe.cook_minutes, recipe.total_minutes
    )
    soft = [
        ("S1", None, "no website Source yet"),
        ("S2", s2, s2_details),
        ("S3", None, "parse agreement needs the second parse engine (ticket 09)"),
        ("S4", None, "no transcript Source yet"),
        ("S5", None, "quantity sanity needs the second parse engine (ticket 09)"),
        ("S6", s6, s6_details),
    ]
    for check_id, score, details in soft:
        add(CheckResult(check_id, "soft", score is None or score >= cfg.soft_fail_below, score, details))

    components = [Component("H3", 1 - dropped_fraction)] + [Component(i, s) for i, s, _ in soft]
    evaluation.score = quality_score(components, cfg.weights)
    return evaluation
