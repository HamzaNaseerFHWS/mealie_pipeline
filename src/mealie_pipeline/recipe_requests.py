"""Recipe Requests: one row of the user's sheet of recipe names, kept in the State Store.

Finding the page (ticket 27) and importing it (ticket 28) change a request's status; this module
only registers, lists, resets and reports them.
"""

import csv
import json
import re
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
    "position",
    "name",
    "category",
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
    category: str | None = None
    position: str | None = None
    item_key: str | None = None


class RecipeRequests:
    """The Recipe Request queries of the State Store."""

    def __init__(self, store: StateStore):
        self.db = store.db

    def add_rows(self, rows: list[SheetRow], source_file: str) -> tuple[int, int]:
        """Registers rows and returns `(new, already_known)`.

        A list-layout row is known when a request has the same normalized name or URL. A grid-layout
        row is one cell: it is known when a request has the same sheet position and name, so the same
        recipe in several columns stays several requests, each with its own category.
        """
        known_names = {r["name_key"] for r in self.db.execute("SELECT name_key FROM recipe_requests")}
        known_urls = {
            r["url_key"]
            for r in self.db.execute("SELECT url_key FROM recipe_requests WHERE url_key IS NOT NULL")
        }
        known_cells = {
            r["identity"]
            for r in self.db.execute("SELECT identity FROM recipe_requests WHERE identity LIKE 'cell:%'")
        }
        new = known = 0
        for row in rows:
            name_key = normalize_name(row.name)
            url_key = normalize_url(row.url) if row.url else None
            if row.layout == "grid":
                identity = f"cell:{row.position}|{name_key}"
                is_known = identity in known_cells
            else:
                identity = f"name:{name_key}"
                is_known = name_key in known_names or bool(url_key and url_key in known_urls)
            if is_known:
                known += 1
                continue
            self.db.execute(
                "INSERT INTO recipe_requests (row_number, source_file, name, name_key, url, url_key,"
                " language, notes, cuisine, category, position, layout, identity, added_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))",
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
                    row.category,
                    row.position,
                    row.layout,
                    identity,
                ),
            )
            known_names.add(name_key)
            known_cells.add(identity)
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
                r["category"],
                r["position"],
                r["item_key"],
            )
            for r in rows
        ]

    def get(self, request_id: int) -> RecipeRequest:
        return next(r for r in self.all() if r.id == request_id)

    def for_item(self, item_key: str) -> RecipeRequest | None:
        """The first request that became this Recipe Part (the same page can answer several cells)."""
        return next((r for r in self.all() if r.item_key == item_key), None)

    def set_item_key(self, request_id: int, item_key: str) -> None:
        self.db.execute(
            "UPDATE recipe_requests SET item_key = ?, updated_at = datetime('now') WHERE id = ?",
            (item_key, request_id),
        )
        self.db.commit()

    def set_outcome(
        self,
        request_id: int,
        status: str,
        *,
        slug: str | None = None,
        mealie_url: str | None = None,
        score: float | None = None,
        reason: str | None = None,
        last_error: str | None = None,
    ) -> None:
        """The import outcome of a found request; the search candidates stay as they were."""
        self.db.execute(
            "UPDATE recipe_requests SET status = ?, slug = ?, mealie_url = ?, score = COALESCE(?, score),"
            " reason = ?, last_error = ?, updated_at = datetime('now') WHERE id = ?",
            (status, slug, mealie_url, score, reason, last_error, request_id),
        )
        self.db.commit()

    def with_status(self, status: str) -> list[RecipeRequest]:
        return [r for r in self.all() if r.status == status]

    def set_result(
        self,
        request_id: int,
        status: str,
        *,
        chosen_url: str | None = None,
        candidates: list[dict[str, Any]] | None = None,
        score: float | None = None,
        reason: str | None = None,
        last_error: str | None = None,
    ) -> None:
        """Records what a stage found out about a request."""
        self.db.execute(
            "UPDATE recipe_requests SET status = ?, chosen_url = ?, candidates_json = ?, score = ?,"
            " reason = ?, last_error = ?, updated_at = datetime('now') WHERE id = ?",
            (
                status,
                chosen_url,
                json.dumps(candidates or [], ensure_ascii=False),
                score,
                reason,
                last_error,
                request_id,
            ),
        )
        self.db.commit()

    def counts(self) -> dict[str, int]:
        rows = self.db.execute("SELECT status, COUNT(*) AS n FROM recipe_requests GROUP BY status")
        return {r["status"]: r["n"] for r in rows}

    def recent_errors(self, limit: int = 10) -> list[RecipeRequest]:
        wanted = [r for r in self.all() if r.last_error]
        return sorted(wanted, key=lambda r: r.id, reverse=True)[:limit]

    def find(self, ref: str) -> list[RecipeRequest]:
        """Requests matching a cell position (`R2C1`), a row number or a name (case/space-insensitive)."""
        if re.fullmatch(r"(.+!)?R\d+C\d+", ref.strip(), re.IGNORECASE):
            wanted = ref.strip().casefold()
            return [
                r
                for r in self.all()
                if (r.position or "").casefold() == wanted
                or (r.position or "").casefold().endswith("!" + wanted)
            ]
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
                    "position": r.position or "",
                    "name": r.name,
                    "category": r.category or "",
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
