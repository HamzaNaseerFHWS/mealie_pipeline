"""Recipe Requests: one row of the user's sheet of recipe names, kept in the State Store.

Finding the page (ticket 27) and importing it (ticket 28) change a request's status; this module
only registers, lists, resets and reports them.
"""

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from mealie_pipeline.request_sheet import SheetRow, normalize_name, normalize_url
from mealie_pipeline.store import StateStore

STATUSES = [
    "pending",
    "found",
    "not_found",
    "needs_choice",
    "imported",
    "already_in_mealie",
    "review",
    "failed",
]
FINISHED = ("imported", "already_in_mealie")

REPORT_COLUMNS = [
    "row_number",
    "name",
    "notes",
    "cuisine",
    "status",
    "chosen_url",
    "mealie_url",
    "score",
    "reason",
]


@dataclass(frozen=True)
class RecipeRequest:
    id: int
    row_number: int
    source_file: str
    name: str
    url: str | None
    language: str | None
    notes: str | None
    cuisine: str | None
    status: str
    chosen_url: str | None
    candidates: list[dict[str, Any]]
    slug: str | None
    mealie_url: str | None
    score: float | None
    reason: str | None
    last_error: str | None


class RecipeRequests:
    """The Recipe Request queries of the State Store."""

    def __init__(self, store: StateStore):
        self.db = store.db

    def add_rows(self, rows: list[SheetRow], source_file: str) -> tuple[int, int]:
        """Registers rows; a row matching a known request by name or URL is left alone.

        Returns `(new, already_known)`.
        """
        known_names = {r["name_key"] for r in self.db.execute("SELECT name_key FROM recipe_requests")}
        known_urls = {
            r["url_key"]
            for r in self.db.execute("SELECT url_key FROM recipe_requests WHERE url_key IS NOT NULL")
        }
        new = known = 0
        for row in rows:
            name_key = normalize_name(row.name)
            url_key = normalize_url(row.url) if row.url else None
            if name_key in known_names or (url_key and url_key in known_urls):
                known += 1
                continue
            self.db.execute(
                "INSERT INTO recipe_requests (row_number, source_file, name, name_key, url, url_key,"
                " language, notes, cuisine, added_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
                (
                    row.row_number,
                    source_file,
                    row.name,
                    name_key,
                    row.url,
                    url_key,
                    row.language,
                    row.notes,
                    row.cuisine,
                ),
            )
            known_names.add(name_key)
            if url_key:
                known_urls.add(url_key)
            new += 1
        self.db.commit()
        return new, known

    def all(self) -> list[RecipeRequest]:
        rows = self.db.execute("SELECT * FROM recipe_requests ORDER BY id").fetchall()
        return [
            RecipeRequest(
                r["id"],
                r["row_number"],
                r["source_file"],
                r["name"],
                r["url"],
                r["language"],
                r["notes"],
                r["cuisine"],
                r["status"],
                r["chosen_url"],
                json.loads(r["candidates_json"] or "[]"),
                r["slug"],
                r["mealie_url"],
                r["score"],
                r["reason"],
                r["last_error"],
            )
            for r in rows
        ]

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) AS n FROM recipe_requests GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def recent_errors(self, limit: int = 10) -> list[RecipeRequest]:
        wanted = [r for r in self.all() if r.last_error]
        return sorted(wanted, key=lambda r: r.id, reverse=True)[:limit]

    def find(self, ref: str) -> list[RecipeRequest]:
        """Requests matching a row number or a name (case/space-insensitive)."""
        if ref.strip().isdigit():
            return [r for r in self.all() if r.row_number == int(ref)]
        key = normalize_name(ref)
        return [r for r in self.all() if normalize_name(r.name) == key]

    def retry(self, ref: str) -> tuple[list[RecipeRequest], list[RecipeRequest]]:
        """Puts the matching requests back to `pending`; finished ones are left alone.

        Returns `(reset, finished_and_untouched)`.
        """
        matches = self.find(ref)
        todo = [r for r in matches if r.status not in FINISHED]
        self._reset([r.id for r in todo])
        return todo, [r for r in matches if r.status in FINISHED]

    def reset_failed(self) -> int:
        ids = [r.id for r in self.all() if r.status == "failed"]
        self._reset(ids)
        return len(ids)

    def _reset(self, ids: list[int]) -> None:
        for request_id in ids:
            self.db.execute(
                "UPDATE recipe_requests SET status = 'pending', last_error = NULL, reason = NULL,"
                " updated_at = datetime('now') WHERE id = ?",
                (request_id,),
            )
        self.db.commit()


def write_requests_report(requests: RecipeRequests, workspace: Path) -> Path:
    """`reports/requests.csv`: one row per request, UTF-8 with BOM so Excel opens it correctly."""
    path = workspace / "reports" / "requests.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_COLUMNS)
        writer.writeheader()
        for r in requests.all():
            writer.writerow(
                {
                    "row_number": r.row_number,
                    "name": r.name,
                    "notes": r.notes or "",
                    "cuisine": r.cuisine or "",
                    "status": r.status,
                    "chosen_url": r.chosen_url or r.url or "",
                    "mealie_url": r.mealie_url or "",
                    "score": "" if r.score is None else r.score,
                    "reason": r.last_error or r.reason or "",
                }
            )
    return path
