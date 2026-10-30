"""The State Store: `pipeline.db`, the only place the pipeline remembers anything.

Entities: Saved Lists (with their memberships), Videos, Recipe Parts and Stage Records.
Migrations are versioned and applied on open.
Public queries are what tests assert on.
"""

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

Status = Literal[
    "pending",
    "running",
    "done",
    "failed",
    "skipped",
    "review",
    "already_in_mealie",  # the Video's link is already on a Mealie recipe: nothing more is done
    "upgraded_existing",  # an old Mealie recipe was PATCHed in place (--upgrade-existing)
]
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
    "ALTER TABLE recipe_parts ADD COLUMN verify_json TEXT;",
    # Migration 3: Recipe Requests (ticket 26). Appended; if a sibling branch also appended one, keep both.
    """
    CREATE TABLE recipe_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        row_number INTEGER NOT NULL,
        source_file TEXT NOT NULL,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL,
        url TEXT,
        url_key TEXT,
        language TEXT,
        notes TEXT,
        cuisine TEXT,
        status TEXT NOT NULL DEFAULT 'pending',
        chosen_url TEXT,
        candidates_json TEXT,
        slug TEXT,
        mealie_url TEXT,
        score REAL,
        reason TEXT,
        last_error TEXT,
        added_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """,
    # Migration 4: where each request sits in the sheet and which category column it came from.
    """
    ALTER TABLE recipe_requests ADD COLUMN category TEXT;
    ALTER TABLE recipe_requests ADD COLUMN position TEXT;
    ALTER TABLE recipe_requests ADD COLUMN layout TEXT NOT NULL DEFAULT 'list';
    ALTER TABLE recipe_requests ADD COLUMN identity TEXT;
    UPDATE recipe_requests SET position = 'R' || row_number || 'C1', identity = 'name:' || name_key;
    """,
    # Migration 5 (ticket 28): the Item Key of the Recipe Part a found request became.
    "ALTER TABLE recipe_requests ADD COLUMN item_key TEXT;",
    # Migration 6 (ticket 04): Saved Lists, which Videos each holds, every URL form a Video was seen
    # under, and the early metadata a flat playlist listing gives for free.
    """
    CREATE TABLE saved_lists (
        list_key TEXT PRIMARY KEY,
        platform TEXT NOT NULL,
        url TEXT NOT NULL,
        title TEXT,
        added_at TEXT NOT NULL,
        last_synced TEXT,
        sync_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT
    );
    CREATE TABLE list_members (
        list_key TEXT NOT NULL REFERENCES saved_lists(list_key),
        video_key TEXT NOT NULL REFERENCES videos(video_key),
        first_sync INTEGER NOT NULL,
        last_sync INTEGER NOT NULL,
        PRIMARY KEY (list_key, video_key)
    );
    CREATE TABLE video_urls (
        video_key TEXT NOT NULL REFERENCES videos(video_key),
        url TEXT NOT NULL,
        PRIMARY KEY (video_key, url)
    );
    ALTER TABLE videos ADD COLUMN early_json TEXT;
    INSERT OR IGNORE INTO video_urls (video_key, url) SELECT video_key, url FROM videos;
    """,
    # Migration 7 (ticket 05): the Video Label and how it was reached (`classify` stage).
    "ALTER TABLE videos ADD COLUMN classification_json TEXT;",
    # Migration 8 (ticket 17): the Creator -> Recipe Website registry, keyed by normalized handle.
    """
    CREATE TABLE creator_websites (
        handle TEXT PRIMARY KEY,
        website TEXT NOT NULL,
        source TEXT NOT NULL,
        learned_from TEXT,
        added_at TEXT NOT NULL
    );
    """,
]

PART_JSON_FIELDS = {"extracted", "parsed", "tags", "verify"}
PART_FIELDS = PART_JSON_FIELDS | {"slug", "mealie_url", "warnings"}


@dataclass(frozen=True)
class Video:
    video_key: str
    platform: str
    video_id: str
    url: str
    canonical_url: str
    metadata: dict[str, Any] | None
    early: dict[str, Any] | None = None  # title/channel/duration from a list listing, before `metadata`
    classification: dict[str, Any] | None = None  # the Video Label, confidence and reasons (`classify`)


@dataclass(frozen=True)
class SavedList:
    list_key: str
    platform: str
    url: str
    title: str | None
    added_at: str
    last_synced: str | None
    sync_count: int
    item_count: int
    last_error: str | None


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
    verify: dict[str, Any] | None = None


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


BUSY_TIMEOUT_SECONDS = 60


class StateStore:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._local = threading.local()
        self._connections: list[sqlite3.Connection] = []
        self._connections_lock = threading.Lock()
        self._migrate()

    @property
    def _db(self) -> sqlite3.Connection:
        """This thread's connection: workers never share one, so they never trip over each other."""
        connection = getattr(self._local, "connection", None)
        if connection is None:
            # WAL + a long lock wait: workers, `mp run --stages find` and an import run share the file.
            connection = sqlite3.connect(self._path, timeout=BUSY_TIMEOUT_SECONDS, check_same_thread=False)
            connection.execute("PRAGMA journal_mode=WAL")
            connection.row_factory = sqlite3.Row
            self._local.connection = connection
            with self._connections_lock:
                self._connections.append(connection)
        return connection

    @property
    def db(self) -> sqlite3.Connection:
        """The connection of the calling thread, for modules that own their own tables."""
        return self._db

    def close(self) -> None:
        with self._connections_lock:
            connections, self._connections = self._connections, []
        for connection in connections:
            connection.close()
        self._local = threading.local()

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
        self._db.execute("INSERT OR IGNORE INTO video_urls (video_key, url) VALUES (?, ?)", (video_key, url))
        self._db.commit()
        return cursor.rowcount == 1

    def add_video_url(self, video_key: str, url: str) -> None:
        """Remembers another URL form the Video was seen under."""
        self._db.execute("INSERT OR IGNORE INTO video_urls (video_key, url) VALUES (?, ?)", (video_key, url))
        self._db.commit()

    def video_urls(self, video_key: str) -> list[str]:
        rows = self._db.execute(
            "SELECT url FROM video_urls WHERE video_key = ? ORDER BY url", (video_key,)
        ).fetchall()
        return [r["url"] for r in rows]

    def set_early_metadata(self, video_key: str, early: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE videos SET early_json = ? WHERE video_key = ?", (json.dumps(early), video_key)
        )
        self._db.commit()

    def set_metadata(self, video_key: str, metadata: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE videos SET metadata_json = ? WHERE video_key = ?", (json.dumps(metadata), video_key)
        )
        self._db.commit()

    def set_classification(self, video_key: str, classification: dict[str, Any]) -> None:
        self._db.execute(
            "UPDATE videos SET classification_json = ? WHERE video_key = ?",
            (json.dumps(classification), video_key),
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
            _loads(row["early_json"]),
            _loads(row["classification_json"]),
        )

    def videos(self) -> list[Video]:
        keys = self._db.execute("SELECT video_key FROM videos ORDER BY added_at, video_key").fetchall()
        return [self.video(r["video_key"]) for r in keys]

    # -- saved lists ----------------------------------------------------------------------

    def add_list(self, list_key: str, platform: str, url: str) -> bool:
        """Registers a Saved List; False when its List Key is already known."""
        cursor = self._db.execute(
            "INSERT OR IGNORE INTO saved_lists (list_key, platform, url, added_at) VALUES (?, ?, ?, ?)",
            (list_key, platform, url, _now()),
        )
        self._db.commit()
        return cursor.rowcount == 1

    def saved_lists(self) -> list[SavedList]:
        rows = self._db.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM list_members m WHERE m.list_key = s.list_key) AS items"
            " FROM saved_lists s ORDER BY s.added_at, s.list_key"
        ).fetchall()
        return [
            SavedList(
                r["list_key"],
                r["platform"],
                r["url"],
                r["title"],
                r["added_at"],
                r["last_synced"],
                r["sync_count"],
                r["items"],
                r["last_error"],
            )
            for r in rows
        ]

    def record_sync(self, list_key: str, video_keys: list[str]) -> list[str]:
        """Stores one successful sync of a Saved List; returns the Video Keys new to this list.

        Membership is kept per list; a Video that is no longer listed keeps its membership (removal
        is never propagated) but its `last_sync` stays behind."""
        number = (
            self._db.execute("SELECT sync_count FROM saved_lists WHERE list_key = ?", (list_key,)).fetchone()[
                "sync_count"
            ]
            + 1
        )
        new = []
        for key in dict.fromkeys(video_keys):
            cursor = self._db.execute(
                "INSERT INTO list_members (list_key, video_key, first_sync, last_sync) VALUES (?, ?, ?, ?)"
                " ON CONFLICT (list_key, video_key) DO UPDATE SET last_sync = excluded.last_sync"
                " RETURNING first_sync",
                (list_key, key, number, number),
            )
            if cursor.fetchone()["first_sync"] == number:
                new.append(key)
        self._db.execute(
            "UPDATE saved_lists SET sync_count = ?, last_synced = ?, last_error = NULL WHERE list_key = ?",
            (number, _now(), list_key),
        )
        self._db.commit()
        return new

    def record_sync_error(self, list_key: str, error: str) -> None:
        self._db.execute("UPDATE saved_lists SET last_error = ? WHERE list_key = ?", (error, list_key))
        self._db.commit()

    def new_in_last_sync(self, list_key: str) -> list[str]:
        rows = self._db.execute(
            "SELECT m.video_key FROM list_members m JOIN saved_lists s ON s.list_key = m.list_key"
            " WHERE m.list_key = ? AND m.first_sync = s.sync_count ORDER BY m.video_key",
            (list_key,),
        ).fetchall()
        return [r["video_key"] for r in rows]

    def memberships(self, video_key: str) -> list[str]:
        rows = self._db.execute(
            "SELECT list_key FROM list_members WHERE video_key = ? ORDER BY list_key", (video_key,)
        ).fetchall()
        return [r["list_key"] for r in rows]

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
            _loads(row["verify_json"]),
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

    def claim(self, kind: EntityKind, key: str, stage: str, stale_minutes: int = 30) -> bool:
        """Takes the entity for this stage: True for exactly one caller.

        Succeeds when the stage has no record or is `pending`, or when another run's claim (`running`)
        is older than `stale_minutes` (that run died). Used by workers; the claim is a `running` record."""
        stale_before = (datetime.now(UTC) - timedelta(minutes=stale_minutes)).isoformat(timespec="seconds")
        cursor = self._db.execute(
            "INSERT INTO stage_records (entity_kind, entity_key, stage, status, attempts, last_error,"
            " updated_at) VALUES (?, ?, ?, 'running', 1, NULL, ?)"
            " ON CONFLICT (entity_kind, entity_key, stage) DO UPDATE SET status = 'running',"
            " attempts = attempts + 1, last_error = NULL, updated_at = excluded.updated_at"
            " WHERE stage_records.status = 'pending'"
            " OR (stage_records.status = 'running' AND stage_records.updated_at < ?)",
            (kind, key, stage, _now(), stale_before),
        )
        self._db.commit()
        return cursor.rowcount == 1

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

    # -- status, retry and reset ----------------------------------------------------------

    def stage_counts(self) -> dict[tuple[str, str], int]:
        """`(stage, status) -> number of entities`."""
        rows = self._db.execute(
            "SELECT stage, status, COUNT(*) AS n FROM stage_records GROUP BY stage, status"
        ).fetchall()
        return {(r["stage"], r["status"]): r["n"] for r in rows}

    def recent_errors(self, limit: int = 10) -> list[StageRecord]:
        rows = self._db.execute(
            "SELECT * FROM stage_records WHERE last_error IS NOT NULL AND last_error != ''"
            " AND status = 'failed' ORDER BY updated_at DESC, rowid DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            StageRecord(
                r["entity_kind"], r["entity_key"], r["stage"], r["status"], r["attempts"], r["last_error"]
            )
            for r in rows
        ]

    def reset_stages(
        self, stages: list[str], *, keys: list[str] | None = None, failed_only: bool = False
    ) -> int:
        """Forgets the Stage Records of `stages` so they run again; returns how many were removed.

        `keys` limits the reset to those entities (a Video Key also covers its Recipe Parts).
        `failed_only` removes only the records whose status is `failed`.
        """
        removed = 0
        for record in self.stage_records():
            if record.stage not in stages:
                continue
            if failed_only and record.status != "failed":
                continue
            if keys is not None and not any(
                record.entity_key == k or record.entity_key.startswith(f"{k}#") for k in keys
            ):
                continue
            self._db.execute(
                "DELETE FROM stage_records WHERE entity_kind = ? AND entity_key = ? AND stage = ?",
                (record.entity_kind, record.entity_key, record.stage),
            )
            removed += 1
        self._db.commit()
        return removed
