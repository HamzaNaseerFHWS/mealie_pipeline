"""Small recipe pages for the `find` tests."""

import json
from typing import Any


def recipe_json(
    name: str,
    ingredients: int = 6,
    steps: int = 4,
    image: bool = True,
    *,
    ingredient_lines: list[str] | None = None,
    step_lines: list[str] | None = None,
) -> dict[str, Any]:
    data: dict[str, Any] = {
        "@type": "Recipe",
        "name": name,
        "recipeIngredient": ingredient_lines
        or [f"{n} unit of ingredient {n}" for n in range(1, ingredients + 1)],
        "recipeInstructions": [
            {"@type": "HowToStep", "text": text}
            for text in (step_lines or [f"Do step {n}." for n in range(1, steps + 1)])
        ],
        "recipeYield": "4 servings",
        "prepTime": "PT10M",
        "cookTime": "PT20M",
    }
    if image:
        data["image"] = "https://img.example/pic.jpg"
    return data


def page(*recipes: dict[str, Any], lang: str | None = "en", title: str = "A page") -> str:
    """An HTML page whose JSON-LD holds the given recipes (two or more make it a "list" page)."""
    attr = f' lang="{lang}"' if lang else ""
    payload = json.dumps(list(recipes) if len(recipes) != 1 else recipes[0])
    return (
        f"<!doctype html><html{attr}><head><title>{title}</title>"
        f'<script type="application/ld+json">{payload}</script></head>'
        "<body><h1>x</h1></body></html>"
    )


def text_only_page(text: str = "Some words about food.") -> str:
    return (
        f"<html lang='en'><head><title>t</title></head><body><article><p>{text}</p></article></body></html>"
    )
