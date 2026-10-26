"""The Mealie payload builder (pure): parsed recipe + tags + provenance -> the PATCH body."""

import uuid
from collections.abc import Callable
from typing import Any

from mealie_pipeline.models import ExtractedRecipe, ParsedIngredient

PIPELINE_VERSION = "0.2.0"


def iso_duration(minutes: int | None) -> str | None:
    """`90` -> `PT1H30M`; None and 0 mean "not given"."""
    if not minutes or minutes <= 0:
        return None
    hours, rest = divmod(minutes, 60)
    return "PT" + (f"{hours}H" if hours else "") + (f"{rest}M" if rest else "")


def _ingredients(parsed: list[ParsedIngredient], new_id: Callable[[], str]) -> list[dict[str, Any]]:
    result, previous_section = [], None
    for item in parsed:
        title = item.section if item.section and item.section != previous_section else None
        previous_section = item.section
        result.append(
            {
                "quantity": item.quantity,
                "unit": {"id": item.unit_id, "name": item.unit_name} if item.unit_name else None,
                "food": {"id": item.food_id, "name": item.food_name},
                "note": item.note,
                "originalText": item.original_text,
                "title": title,
                "referenceId": new_id(),
            }
        )
    return result


def _instructions(recipe: ExtractedRecipe) -> list[dict[str, Any]]:
    result, previous_section = [], None
    for step in recipe.instructions:
        title = step.section if step.section and step.section != previous_section else ""
        previous_section = step.section
        result.append({"title": title, "summary": "", "text": step.text, "ingredientReferences": []})
    return result


def build_payload(
    recipe: ExtractedRecipe,
    parsed: list[ParsedIngredient],
    tags: list[dict[str, Any]],
    *,
    org_url: str,
    item_key: str,
    video_key: str,
    platform: str,
    part: int = 1,
    of: int = 1,
    new_id: Callable[[], str] = lambda: str(uuid.uuid4()),
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": recipe.name,
        "description": recipe.description,
        "recipeIngredient": _ingredients(parsed, new_id),
        "recipeInstructions": _instructions(recipe),
        "notes": [{"title": "", "text": note} for note in recipe.notes],
        "tags": tags,
        "orgURL": org_url,
        "extras": {
            "item_key": item_key,
            "video_key": video_key,
            "part": part,
            "of": of,
            "platform": platform,
            "pipeline_version": PIPELINE_VERSION,
        },
    }
    if recipe.servings:
        payload["recipeServings"] = recipe.servings
    if recipe.yield_text:
        payload["recipeYield"] = recipe.yield_text
    for field, minutes in (
        ("prepTime", recipe.prep_minutes),
        ("performTime", recipe.cook_minutes),
        ("totalTime", recipe.total_minutes),
    ):
        duration = iso_duration(minutes)
        if duration:
            payload[field] = duration
    return payload
