"""`mp requeue-subtitles` (ticket 34): send the Videos that had no text to extract back through
`scrape`, which now reads their subtitles (and makes a link-only stub when there are none).

Which Videos: every Recipe Part whose extraction failed for lack of text, plus the rows of
`reports/youtube_status.csv` marked `needs_transcription` (renamed `needs_subtitles` there).
"""

import csv
from pathlib import Path

from mealie_pipeline.pipeline import STAGES
from mealie_pipeline.scrape import web_json_path
from mealie_pipeline.store import StateStore
from mealie_pipeline.url_normalizer import normalize

OLD, NEW = "needs_transcription", "needs_subtitles"
NO_TEXT_ERRORS = ("no description or website recipe", "does not contain a recipe")
KEY_COLUMNS = ("video_key", "item_key", "url", "video_url")


def no_text_videos(store: StateStore) -> set[str]:
    """Videos with a Recipe Part whose extraction failed because there was nothing to extract from."""
    keys = set()
    for record in store.stage_records():
        if record.stage != "extract" or record.status not in ("failed", "review"):
            continue
        if any(message in (record.last_error or "") for message in NO_TEXT_ERRORS):
            keys.add(record.entity_key.split("#", 1)[0])
    return keys


def csv_videos(path: Path) -> set[str]:
    """Video Keys of the rows marked `needs_transcription` or `needs_subtitles`; the file is rewritten
    with the new name for the category."""
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    keys: set[str] = set()
    changed = False
    for row in rows:
        marked = [column for column, value in row.items() if value in (OLD, NEW)]
        if not marked:
            continue
        for column in marked:
            if row[column] == OLD:
                row[column] = NEW
                changed = True
        key = _video_key(row)
        if key:
            keys.add(key)
    if changed:
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
    return keys


def _video_key(row: dict[str, str]) -> str | None:
    for column in KEY_COLUMNS:
        value = (row.get(column) or "").strip()
        if not value:
            continue
        if ":" in value and not value.startswith("http"):
            return value.split("#", 1)[0]
        normalized = normalize(value)
        if normalized is not None:
            return normalized.video_key
    return None


def requeue(store: StateStore, workspace: Path, csv_path: Path) -> list[str]:
    """Resets `scrape` and every later stage for those Videos; returns their keys."""
    known = {v.video_key: v for v in store.videos()}
    keys = sorted((no_text_videos(store) | csv_videos(csv_path)) & set(known))
    for key in keys:
        video = known[key]
        marker = web_json_path(workspace, video.platform, video.video_id).with_name("subtitles.txt")
        marker.unlink(missing_ok=True)  # ask for subtitles again
    if keys:
        store.reset_stages(STAGES[STAGES.index("scrape") :], keys=keys)
    return keys
