"""The Review Queue: one Markdown file per held-back Recipe Part, Sources next to the recipe."""

import re
from pathlib import Path
from typing import Any

from mealie_pipeline.models import ExtractedRecipe
from mealie_pipeline.store import Video

SOURCE_LIMIT = 3000


def review_path(workspace: Path, item_key: str) -> Path:
    return workspace / "review" / (re.sub(r"[^A-Za-z0-9_.-]+", "_", item_key) + ".md")


def write_review_file(
    workspace: Path,
    *,
    item_key: str,
    video: Video,
    sources: dict[str, str],
    recipe: ExtractedRecipe,
    verify: dict[str, Any],
) -> Path:
    lines = [
        f"# Review: {recipe.name or item_key}",
        "",
        f"- Item: `{item_key}`",
        f"- Video: {video.canonical_url}",
        "- Label: not classified yet (the classifier arrives with ticket 05)",
        f"- Score: {verify['score']} (outcome: held back, not uploaded)",
        f"- Extraction attempts: {verify['extraction_attempts']}",
        "",
        "## Failed checks",
        "",
    ]
    failed = [c for c in verify["checks"] if not c["passed"]]
    lines += [f"- **{c['id']}** ({c['kind']}): {c['details']}" for c in failed] or [
        "- none (the score alone was too low)"
    ]
    lines += [
        f"- **S7** (judge): {p['severity']} {p['field']}: {p['description']}"
        for p in verify["judge_problems"]
    ]
    lines += ["", "## Sources", ""]
    for kind, text in sources.items():
        shown = text if len(text) <= SOURCE_LIMIT else text[:SOURCE_LIMIT] + "\n[...trimmed]"
        lines += [f"### {kind}", "", "```text", shown, "```", ""]
    lines += ["## Extracted recipe", "", f"**{recipe.name}** ({recipe.language})", "", recipe.description, ""]
    lines += ["### Ingredients", ""]
    lines += [f"- {i.line}  _(source: {i.original_line})_" for i in recipe.ingredients] or ["- none"]
    if verify["dropped_ingredients"]:
        lines += ["", "Dropped as not found in the sources:"]
        lines += [f"- {d}" for d in verify["dropped_ingredients"]]
    lines += ["", "### Steps", ""]
    lines += [f"{n}. {s.text}" for n, s in enumerate(recipe.instructions, start=1)] or ["- none"]
    path = review_path(workspace, item_key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
