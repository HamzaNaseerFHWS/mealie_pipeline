"""Soft checks of the Gate (pure). Each returns `(score 0..1, details)`."""

import re

from mealie_pipeline.matching import singularize

MAX_SERVINGS = 50
MAX_TOTAL_MINUTES = 24 * 60
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)


def words(text: str) -> list[str]:
    return [singularize(w) for w in _WORD.findall(text.casefold())]


def ingredients_vs_steps(
    ingredient_foods: list[str],
    steps: list[str],
    known_foods: list[str],
    original_names: list[str] | None = None,
) -> tuple[float, str]:
    """S2. Each ingredient should be used in some step, and each known Food a step mentions should be
    listed as an ingredient. Score = 1 - problems / ingredients (never below 0).

    `original_names[i]` is ingredient i's name in the source's language (or empty): the steps of a
    German recipe are German, so either spelling counts as "used" and as "listed"."""
    if not ingredient_foods:
        return 0.0, "no ingredients"
    originals = list(original_names or []) + [""] * len(ingredient_foods)
    step_text = " ".join(steps)
    step_words = set(words(step_text))
    unused = [
        f
        for f, original in zip(ingredient_foods, originals, strict=False)
        if not (set(words(f)) | set(words(original))) & step_words
    ]
    listed_words = {w for f in [*ingredient_foods, *originals] for w in words(f)}
    padded = f" {' '.join(words(step_text))} "
    unlisted = sorted(
        {
            name
            for name in known_foods
            if len(name) >= 3
            and f" {' '.join(words(name))} " in padded
            and not set(words(name)) <= listed_words
        }
    )
    score = max(0.0, 1 - (len(unused) + len(unlisted)) / len(ingredient_foods))
    details = []
    if unused:
        details.append("never used in a step: " + ", ".join(unused))
    if unlisted:
        details.append("used in a step but not listed: " + ", ".join(unlisted))
    return score, "; ".join(details) or "every ingredient is used and every step food is listed"


def plausibility(
    servings: float | None, prep: int | None, cook: int | None, total: int | None
) -> tuple[float, str]:
    """S6. Missing values are fine; contradictory or absurd ones are not."""
    problems = []
    if servings is not None and not 1 <= servings <= MAX_SERVINGS:
        problems.append(f"servings {servings:g} outside 1-{MAX_SERVINGS}")
    if total is not None:
        if prep is not None and total < prep:
            problems.append(f"total time {total} min is less than prep time {prep} min")
        if cook is not None and total < cook:
            problems.append(f"total time {total} min is less than cook time {cook} min")
        if total > MAX_TOTAL_MINUTES:
            problems.append(f"total time {total} min is over 24 hours")
    for label, minutes in (("prep", prep), ("cook", cook)):
        if minutes is not None and minutes < 0:
            problems.append(f"negative {label} time")
    return max(0.0, 1 - 0.5 * len(problems)), "; ".join(problems) or "times and servings are plausible"


def food_overlap(video_foods: set[str], website_foods: set[str]) -> tuple[float, str]:
    """S1. Jaccard overlap of the Food names from the video and from the website page; a low value
    suggests the wrong website page was matched. Not used until a website Source exists (ticket 06)."""
    union = video_foods | website_foods
    if not union:
        return 0.0, "no foods on either side"
    score = len(video_foods & website_foods) / len(union)
    return score, f"food overlap {score:.2f}"
