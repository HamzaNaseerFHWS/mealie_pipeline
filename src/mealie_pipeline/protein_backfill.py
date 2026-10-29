"""`mp tags protein [--apply]`: give every recipe in Mealie its Protein Tags (ticket 25).

It reads every recipe (the pipeline's own and older imports), detects its main proteins
(`protein.detect`) and writes `reports/protein_tags.csv`. With `apply` it creates the Protein Tags
that are missing from Mealie (the one approved exception to "only `To Review` is created", limited to
`config/protein_tags.yaml`) and PATCHes each recipe with its current tags plus the new ones. It never
removes a tag. Overrides in the CSV win and are kept across runs.
"""

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from mealie_pipeline.adapters.llm import LLMBackend, LLMError, UsageLimited
from mealie_pipeline.adapters.mealie import MealieGateway, Tag
from mealie_pipeline.errors import MealieError
from mealie_pipeline.protein import ProteinRules, detect, is_unparsed, mealie_recipe_text, tag_key

CSV_PATH = Path("reports") / "protein_tags.csv"
APPLIED_PATH = Path("reports") / "protein_tags_applied.csv"
CSV_COLUMNS = ["slug", "name", "link", "current_tags", "proposed_tags", "triggers", "override", "result"]
LLM_BATCH = 20  # recipes per `--llm-check` call
LLM_MAX_CANDIDATES = 3  # more candidates than this is ambiguous


@dataclass
class _Row:
    slug: str
    name: str = ""
    link: str = ""
    current: list[dict[str, Any]] = field(default_factory=list)
    proposed: dict[str, list[str]] = field(default_factory=dict)  # tag -> triggers
    override: str = ""
    locked: bool = False
    status: str = ""  # blocked | unchanged | locked | todo | added | failed
    error: str = ""
    notes: list[str] = field(default_factory=list)  # e.g. an unknown name in the override
    new: list[str] = field(default_factory=list)  # Protein Tags to add

    @property
    def result(self) -> str:
        text = {
            "locked": "locked (skipped)",
            "todo": f"would add: {', '.join(self.new)}",
            "added": f"added: {', '.join(self.new)}",
            "failed": f"failed: {self.error}",
        }.get(self.status, self.status)
        return "; ".join([*self.notes, text])

    def csv_row(self) -> dict[str, str]:
        return {
            "slug": self.slug,
            "name": self.name,
            "link": self.link,
            "current_tags": ", ".join(t.get("name") or "" for t in self.current),
            "proposed_tags": ", ".join(self.proposed),
            "triggers": "; ".join(f"{tag}: {', '.join(words)}" for tag, words in self.proposed.items()),
            "override": self.override,
            "result": self.result,
        }


@dataclass
class BackfillReport:
    csv_path: Path
    gained: list[str] = field(default_factory=list)  # slugs that gained (or would gain) a tag
    created_tags: list[str] = field(default_factory=list)
    locked: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _read_overrides(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["slug"]: row.get("override") or "" for row in csv.DictReader(handle) if row.get("slug")}


def _override_entries(override: str) -> list[str]:
    return [e.strip() for e in override.replace(";", ",").split(",") if e.strip()]


def _blocked(override: str) -> bool:
    return any(e.casefold() == "block" for e in _override_entries(override))


def _apply_override(row: _Row, rules: ProteinRules) -> list[str]:
    """The final Protein Tags: proposed, plus `+Tag` (or plain `Tag`), minus `-Tag`; `block` = none.
    Entries are separated by commas or semicolons; names outside the list are reported, not used."""
    if _blocked(row.override):
        return []
    final = list(row.proposed)
    for entry in _override_entries(row.override):
        sign, name = (entry[0], entry[1:].strip()) if entry[0] in "+-" else ("+", entry)
        tag = rules.canonical(name)
        if tag is None:
            row.notes.append(f"unknown override {entry!r}")
        elif sign == "-" and tag in final:
            final.remove(tag)
        elif sign == "+" and tag not in final:
            final.append(tag)
    return final


def _llm_schema(rules: ProteinRules) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "recipes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "slug": {"type": "string"},
                        "tags": {"type": "array", "items": {"type": "string", "enum": list(rules.tags)}},
                    },
                    "required": ["slug", "tags"],
                },
            }
        },
        "required": ["recipes"],
    }


def _llm_check(
    rows: list[_Row],
    recipes: dict[str, dict[str, Any]],
    llm: LLMBackend,
    rules: ProteinRules,
    report: BackfillReport,
) -> None:
    """Asks the `fast` tier about recipes with no candidate, too many, or only unparsed ingredients.
    Answers can only name Protein Tags from the list; they replace the rule's guess."""
    unclear = [
        r
        for r in rows
        if not r.proposed or len(r.proposed) > LLM_MAX_CANDIDATES or is_unparsed(recipes[r.slug])
    ]
    for start in range(0, len(unclear), LLM_BATCH):
        batch = unclear[start : start + LLM_BATCH]
        items = [
            {"slug": r.slug, "name": r.name, "ingredients": mealie_recipe_text(recipes[r.slug]).ingredients}
            for r in batch
        ]
        prompt = (
            f"Protein Tags: {json.dumps(list(rules.tags), ensure_ascii=False)}\n\n"
            f"Recipes:\n{json.dumps(items, ensure_ascii=False, indent=1)}"
        )
        try:
            answer = llm.complete("protein_tags", prompt, _llm_schema(rules), "fast")
        except UsageLimited as err:
            report.warnings.append(f"--llm-check stopped at a usage limit: {err}")
            return
        except LLMError as err:
            report.warnings.append(f"--llm-check failed for {len(batch)} recipes: {err}")
            continue
        by_slug = {r.slug: r for r in batch}
        for item in answer.get("recipes") or []:
            row = by_slug.get(str(item.get("slug")))
            if row is None:
                continue
            names = [rules.canonical(str(name)) for name in item.get("tags") or []]
            listed = [tag for tag in rules.tags if tag in names]
            row.proposed = {tag: ["llm"] for tag in listed}


def run_backfill(
    mealie: MealieGateway,
    llm: LLMBackend,
    rules: ProteinRules,
    workspace: Path,
    *,
    apply: bool,
    llm_check: bool = False,
    now: Callable[[], datetime],
) -> BackfillReport:
    csv_path = workspace / CSV_PATH
    report = BackfillReport(csv_path)
    overrides = _read_overrides(csv_path)

    rows: list[_Row] = []
    recipes: dict[str, dict[str, Any]] = {}
    for summary in mealie.list_recipe_summaries():
        slug = str(summary.get("slug"))
        row = _Row(
            slug,
            name=summary.get("name") or "",
            link=mealie.recipe_url(slug),
            override=overrides.get(slug, ""),
        )
        rows.append(row)
        try:
            recipe = mealie.get_recipe(slug)
        except MealieError as err:
            row.status, row.error = "failed", str(err)
            report.failed.append(slug)
            continue
        recipes[slug] = recipe
        row.name = recipe.get("name") or row.name
        row.current = list(recipe.get("tags") or [])
        row.proposed = detect(mealie_recipe_text(recipe), rules)
        row.locked = bool((recipe.get("settings") or {}).get("locked"))

    readable = [r for r in rows if r.slug in recipes]
    if llm_check:
        _llm_check(readable, recipes, llm, rules, report)

    for row in readable:
        final = _apply_override(row, rules)
        have = {tag_key(t.get("name") or "") for t in row.current}
        row.new = [tag for tag in final if tag_key(tag) not in have]
        if _blocked(row.override):
            row.status = "blocked"
        elif not row.new:
            row.status = "unchanged"
        elif row.locked:
            row.status = "locked"
            report.locked.append(row.slug)
        else:
            row.status = "todo"

    todo = [r for r in readable if r.status == "todo"]
    if apply:
        _apply(mealie, todo, report)
        _log_applied(workspace, [r for r in todo if r.status == "added"], now)
    else:
        report.gained = [r.slug for r in todo]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(r.csv_row() for r in rows)
    return report


def _apply(mealie: MealieGateway, todo: list[_Row], report: BackfillReport) -> None:
    """Creates each missing Protein Tag once, then PATCHes current tags + new ones per recipe."""
    by_key: dict[str, Tag] = {tag_key(t.name): t for t in mealie.catalog().tags}
    for row in todo:
        try:
            added: list[Tag] = []
            for name in row.new:
                tag = by_key.get(tag_key(name))
                if tag is None:
                    tag = by_key[tag_key(name)] = mealie.create_tag(name)
                    report.created_tags.append(name)
                added.append(tag)
            payload = {"tags": row.current + [{"id": t.id, "name": t.name, "slug": t.slug} for t in added]}
            mealie.patch_recipe(row.slug, payload)
        except MealieError as err:
            row.status, row.error = "failed", str(err)
            report.failed.append(row.slug)
            continue
        row.status = "added"
        row.current = payload["tags"]
        report.gained.append(row.slug)


def _log_applied(workspace: Path, rows: list[_Row], now: Callable[[], datetime]) -> None:
    """Appends to `reports/protein_tags_applied.csv`, which `mp status` counts."""
    if not rows:
        return
    path = workspace / APPLIED_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.is_file()
    with path.open("a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as handle:
        writer = csv.writer(handle)
        if new_file:
            writer.writerow(["slug", "added_tags", "applied_at"])
        for row in rows:
            writer.writerow([row.slug, ", ".join(row.new), now().isoformat(timespec="seconds")])


def recipes_gained(workspace: Path) -> int:
    """How many distinct recipes `mp tags protein --apply` has given a Protein Tag so far."""
    path = workspace / APPLIED_PATH
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return len({row["slug"] for row in csv.DictReader(handle)})
