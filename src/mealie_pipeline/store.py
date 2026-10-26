"""The State Store: `pipeline.db`, the only place the pipeline remembers anything.

Entities: Videos, Recipe Parts and Stage Records. Migrations are versioned and applied on open.
Public queries are what tests assert on.
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

Status = Literal["pending", "running", "done", "failed", "skipped", "review"]
EntityKind = Literal["video", "part"]

MIGRATIONS = [
    """
    CREATE TABLE videos (
        video_key TEXT PRIMARY KEY,
        platform TEXT NOT NULL,
        video_id TEXT NOT NULL,
        url TEXT NOT NULL,
        canonical_url TEXT NOT NULL,
        metadata_json TEXT,
        added_at TEXT NOT NULL
    );
    CREATE TABLE recipe_parts (
        item_key TEXT PRIMARY KEY,
        video_key TEXT NOT NULL REFERENCES videos(video_key),
        part_index INTEGER NOT NULL,
        part_count INTEGER NOT NULL,
        extracted_json TEXT,
        parsed_json TEXT,
        tags_json TEXT,
        slug TEXT,
        mealie_url TEXT,
        warnings_json TEXT NOT NULL DEFAULT '[]'
    );
    CREATE TABLE stage_records (
        entity_kind TEXT NOT NULL,
        entity_key TEXT NOT NULL,
        stage TEXT NOT NULL,
        status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        updated_at TEXT NOT NULL,
        PRIMARY KEY (entity_kind, entity_key, stage)
    );
    """,
]

PART_JSON_FIELDS = {"extracted", "parsed", "tags"}
PART_FIELDS = PART_JSON_FIELDS | {"slug", "mealie_url", "warnings"}


@dataclass(frozen=True)
class Video:
    video_key: str
    platform: str
    video_id: str
    url: str
    canonical_url: str
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class RecipePart:
    item_key: str
    video_key: str
    part_index: int
    part_count: int
    extracted: dict[str, Any] | None
    parsed: list[dict[str, Any]] | None
    tags: list[dict[str, Any]] | None
    slug: str | None
    mealie_url: str | None
    warnings: list[str]


@dataclass(frozen=True)
class StageRecord:
    entity_kind: str
    entity_key: str
    stage: str
    status: Status
    attempts: int
    last_error: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _loads(text: str | None) -> Any:
    return json.loads(text) if text else None


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.row_factory = sqlite3.Row
        self._migrate()

    def close(self) -> None:
        self._db.close()

    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            self._db.executescript(script)
            self._db.execute(f"PRAGMA user_version = {number}")
        self._db.commit()

    # -- videos ---------------------------------------------------------------------------

    def add_video(self, video_key: str, platform: str, video_id: str, url: str, canonical_url: str) -> bool:
        """Registers a Video; False when its Video Key is already known."""
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO videos (video_key, platform, video_id, url, canonical_url, added_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (video_key, platform, video_id, url, canonical_url, _now()),
        )
        self._db.commit()
        return cursor.rowcount == 1

    def set_metadata(self, video_key: str, metadata: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE videos SET metadata_json = ? WHERE video_key = ?", (json.dumps(metadata), video_key)
        )
        self._db.commit()

    def video(self, video_key: str) -> Video:
        row = self._db.execute("SELECT * FROM videos WHERE video_key = ?", (video_key,)).fetchone()
        if row is None:
            raise KeyError(video_key)
        return Video(
            row["video_key"],
            row["platform"],
            row["video_id"],
            row["url"],
            row["canonical_url"],
            _loads(row["metadata_json"]),
        )

    def videos(self) -> list[Video]:
        keys = self._db.execute("SELECT video_key FROM videos ORDER BY added_at, video_key").fetchall()
        return [self.video(r["video_key"]) for r in keys]

    # -- recipe parts ---------------------------------------------------------------------

    def ensure_part(self, video_key: str, part_index: int = 1, part_count: int = 1) -> str:
        item_key = f"{video_key}#{part_index}"
        self._db.execute(
            "INSERT OR IGNORE INTO recipe_parts (item_key, video_key, part_index, part_count)"
            " VALUES (?, ?, ?, ?)",
            (item_key, video_key, part_index, part_count),
        )
        self._db.commit()
        return item_key

    def part(self, item_key: str) -> RecipePart:
        row = self._db.execute("SELECT * FROM recipe_parts WHERE item_key = ?", (item_key,)).fetchone()
        if row is None:
            raise KeyError(item_key)
        return RecipePart(
            row["item_key"],
            row["video_key"],
            row["part_index"],
            row["part_count"],
            _loads(row["extracted_json"]),
            _loads(row["parsed_json"]),
            _loads(row["tags_json"]),
            row["slug"],
            row["mealie_url"],
            json.loads(row["warnings_json"]),
        )

    def parts(self) -> list[RecipePart]:
        keys = self._db.execute("SELECT item_key FROM recipe_parts ORDER BY item_key").fetchall()
        return [self.part(r["item_key"]) for r in keys]

    def update_part(self, item_key: str, **fields: Any) -> None:
        unknown = set(fields) - PART_FIELDS
        if unknown:
            raise ValueError(f"unknown recipe part fields: {sorted(unknown)}")
        columns, values = [], []
        for name, value in fields.items():
            if name in PART_JSON_FIELDS or name == "warnings":
                columns.append(f"{name}_json = ?")
                values.append(json.dumps(value))
            else:
                columns.append(f"{name} = ?")
                values.append(value)
        self._db.execute(
            f"UPDATE recipe_parts SET {', '.join(columns)} WHERE item_key = ?", (*values, item_key)
        )
        self._db.commit()

    # -- stage records --------------------------------------------------------------------

    def record(
        self, kind: EntityKind, key: str, stage: str, status: Status, detail: str | None = None
    ) -> None:
        """Writes the Stage Record; `running` counts as an attempt."""
        self._db.execute(
            "INSERT INTO stage_records (entity_kind, entity_key, stage, status, attempts, last_error,"
            " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (entity_kind, entity_key, stage) DO UPDATE SET status = excluded.status,"
            " attempts = attempts + excluded.attempts, last_error = excluded.last_error,"
            " updated_at = excluded.updated_at",
            (kind, key, stage, status, 1 if status == "running" else 0, detail, _now()),
        )
        self._db.commit()

    def stage_status(self, kind: EntityKind, key: str, stage: str) -> Status | None:
        row = self._db.execute(
            "SELECT status FROM stage_records WHERE entity_kind = ? AND entity_key = ? AND stage = ?",
            (kind, key, stage),
        ).fetchone()
        return row["status"] if row else None

    def stage_records(self) -> list[StageRecord]:
        rows = self._db.execute(
            "SELECT * FROM stage_records ORDER BY entity_kind, entity_key, updated_at"
        ).fetchall()
        return [
            StageRecord(
                r["entity_kind"], r["entity_key"], r["stage"], r["status"], r["attempts"], r["last_error"]
            )
            for r in rows
        ]

    def next_batch(
        self, kind: EntityKind, stage: str, previous: str | None, limit: int | None = None
    ) -> list[str]:
        """Keys whose `previous` stage is done and whose `stage` has not finished or failed yet."""
        table, key_column = ("videos", "video_key") if kind == "video" else ("recipe_parts", "item_key")
        keys = [r[0] for r in self._db.execute(f"SELECT {key_column} FROM {table} ORDER BY {key_column}")]
        ready = [
            key
            for key in keys
            if (previous is None or self.stage_status(kind, key, previous) == "done")
            and self.stage_status(kind, key, stage) in (None, "pending", "running")
        ]
        return ready[:limit] if limit is not None else ready
