"""`mp status` and `reports/report.csv`: read-only views of the State Store."""

import csv
from pathlib import Path

from mealie_pipeline.pipeline import STAGES
from mealie_pipeline.store import StateStore

STATUSES = ["pending", "running", "done", "failed", "skipped", "review"]

REPORT_COLUMNS = [
    "item_key",
    "video_url",
    "platform",
    *(f"{stage}_status" for stage in STAGES),
    "score",
    "outcome",
    "failed_checks",
    "extraction_attempts",
    "failure_reason",
    "mealie_slug",
    "mealie_url",
    "created_foods",
    "tags",
    "warnings",
]


def created_food_counts(workspace: Path) -> dict[str, int]:
    """How many Foods each Video caused to be created, from `reports/created_foods.csv`."""
    path = workspace / "reports" / "created_foods.csv"
    if not path.is_file():
        return {}
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[row["first_video_key"]] = counts.get(row["first_video_key"], 0) + 1
    return counts


def write_report(store: StateStore, workspace: Path) -> Path:
    """One row per Recipe Part, plus one row per Video that has no Recipe Part yet (e.g. metadata failed).

    Columns: item_key, video_url, platform, `<stage>_status` for every stage (empty = not reached),
    score / outcome / failed_checks / extraction_attempts (the Gate), failure_reason (the last error
    of the first failed or held-back stage), mealie_slug, mealie_url, created_foods
    (Foods first created for this Video), tags (`;`-separated) and warnings (such as image_missing).
    """
    records = {(r.entity_kind, r.entity_key, r.stage): r for r in store.stage_records()}
    foods = created_food_counts(workspace)
    rows = []
    for video in store.videos():
        parts = [p for p in store.parts() if p.video_key == video.video_key]
        entities = [(p.item_key, p) for p in parts] or [("", None)]
        for item_key, part in entities:
            statuses, reason = {}, ""
            verify = (part.verify if part else None) or {}
            for stage in STAGES:
                kind, key = ("video", video.video_key) if stage == "metadata" else ("part", item_key)
                record = records.get((kind, key, stage))
                statuses[f"{stage}_status"] = record.status if record else ""
                if record and record.status in ("failed", "review") and not reason:
                    reason = f"{stage}: {record.last_error or ''}"
            rows.append(
                {
                    "item_key": item_key,
                    "video_url": video.canonical_url,
                    "platform": video.platform,
                    **statuses,
                    "score": verify.get("score", ""),
                    "outcome": verify.get("outcome", ""),
                    "failed_checks": ";".join(verify.get("failed_checks", [])),
                    "extraction_attempts": verify.get("extraction_attempts", ""),
                    "failure_reason": reason,
                    "mealie_slug": part.slug if part and part.slug else "",
                    "mealie_url": part.mealie_url if part and part.mealie_url else "",
                    "created_foods": foods.get(video.video_key, 0),
                    "tags": ";".join(t["name"] for t in (part.tags or [])) if part else "",
                    "warnings": ";".join(part.warnings) if part else "",
                }
            )
    path = workspace / "reports" / "report.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:  # BOM so Excel reads UTF-8
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path
