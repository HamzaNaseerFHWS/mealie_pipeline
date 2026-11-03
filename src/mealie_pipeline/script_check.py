"""Script check on an extracted recipe (pure): Urdu/Hindi text is written in Roman letters, and every
Ingredient Line is English. The prompt asks for this; this catches the model slipping into Devanagari
or Arabic script (Nastaliq)."""

import re

from mealie_pipeline.models import ExtractedRecipe

_NON_LATIN = re.compile(r"[ऀ-ॿ؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")


def _script_name(text: str) -> str | None:
    match = _NON_LATIN.search(text)
    if match is None:
        return None
    return "Devanagari" if "ऀ" <= match.group() <= "ॿ" else "Arabic-script"


def script_problems(recipe: ExtractedRecipe) -> list[str]:
    """What is written in the wrong script, one finding per field, phrased for the retry prompt."""
    problems: list[str] = []
    if recipe.language in ("ur", "hi"):
        fields = [("name", recipe.name), ("description", recipe.description)]
        fields += [(f"step {i}", step.text) for i, step in enumerate(recipe.instructions, 1)]
        for label, text in fields:
            if script := _script_name(text):
                problems.append(f"{label} contains {script} characters: write Urdu/Hindi in Roman letters")
    for i, ingredient in enumerate(recipe.ingredients, 1):
        if script := _script_name(ingredient.line):
            problems.append(
                f"ingredient {i} `line` contains {script} characters: write the ingredient in English "
                "(keep the source's own wording only in `original_line`)"
            )
    return problems
