"""Telegram inbox bot: collects recipe links you share to it and queues them for the laptop.

Runs on the always-on Mealie PC. Standard library only, so the Docker image needs no installs.

- Asks Telegram for new messages (long polling, outbound only: no open port needed for Telegram).
- Every URL in a message from the allowed chat goes into a SQLite queue as `pending`.
- A small HTTP API lets the laptop fetch pending links and report results back.
  The bot then replies to the original Telegram message with the outcome.

Environment:
    TELEGRAM_BOT_TOKEN   token from @BotFather (required)
    TELEGRAM_CHAT_ID     chat id(s) allowed to use the bot, comma-separated (you and your partner);
                         leave empty at first, message the bot and it replies with the sender's chat id
    INBOX_API_TOKEN      shared secret the laptop sends as `Authorization: Bearer ...` (required)
    INBOX_DB             SQLite path (default /data/inbox.db)
    INBOX_PORT           HTTP API port (default 8765)

HTTP API (all routes except /health need the bearer token):
    GET  /health                -> {"ok": true}
    GET  /pending               -> {"items": [{"id", "url", "received_at"}, ...]}
    POST /items/<id>/result     body {"status": "done"|"not_recipe"|"failed",
                                      "mealie_urls": [...], "note": "..."}
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import re
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

log = logging.getLogger("inbox_bot")

URL_RE = re.compile(r"https?://[^\s<>\"']+")
TRAILING_PUNCT = ".,;:!?)]}>'\""
RESULT_STATUSES = ("done", "not_recipe", "failed")

# Sends a Telegram message: (chat_id, text, reply_to_message_id or None).
SendFn = Callable[[int, str, int | None], None]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def extract_urls(message: dict[str, Any]) -> list[str]:
    """All http(s) links in a Telegram message: plain text, captions and hidden text links."""
    text = message.get("text") or message.get("caption") or ""
    urls = [m.group(0).rstrip(TRAILING_PUNCT) for m in URL_RE.finditer(text)]
    for entity in message.get("entities", []) + message.get("caption_entities", []):
        if entity.get("type") == "text_link" and entity.get("url"):
            urls.append(entity["url"])
    return list(dict.fromkeys(urls))


@dataclass
class Item:
    id: int
    url: str
    chat_id: int
    message_id: int | None
    status: str
    received_at: str


class Queue:
    """SQLite-backed link queue. Safe to share between the polling thread and the HTTP threads."""

    def __init__(self, path: str) -> None:
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.executescript(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    url TEXT NOT NULL UNIQUE,
                    chat_id INTEGER NOT NULL,
                    message_id INTEGER,
                    status TEXT NOT NULL DEFAULT 'pending',
                    received_at TEXT NOT NULL,
                    finished_at TEXT,
                    result_json TEXT
                );
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                """
            )

    def add(self, url: str, chat_id: int, message_id: int | None) -> tuple[Item, bool]:
        """Queue a link. Returns the item and whether it was new (a repeat keeps its first entry)."""
        with self._lock, self._db:
            cur = self._db.execute(
                "INSERT OR IGNORE INTO items (url, chat_id, message_id, received_at) VALUES (?, ?, ?, ?)",
                (url, chat_id, message_id, _now()),
            )
            row = self._db.execute("SELECT * FROM items WHERE url = ?", (url,)).fetchone()
        return _item(row), cur.rowcount == 1

    def get(self, item_id: int) -> Item | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _item(row) if row else None

    def pending(self) -> list[Item]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM items WHERE status = 'pending' ORDER BY id").fetchall()
        return [_item(r) for r in rows]

    def finish(self, item_id: int, status: str, result: dict[str, Any]) -> Item | None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE items SET status = ?, finished_at = ?, result_json = ? WHERE id = ?",
                (status, _now(), json.dumps(result), item_id),
            )
            row = self._db.execute("SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
        return _item(row) if row else None

    def get_offset(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT value FROM meta WHERE key = 'update_offset'").fetchone()
        return int(row["value"]) if row else 0

    def set_offset(self, offset: int) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO meta (key, value) VALUES ('update_offset', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(offset),),
            )


def _item(row: sqlite3.Row) -> Item:
    return Item(
        id=row["id"],
        url=row["url"],
        chat_id=row["chat_id"],
        message_id=row["message_id"],
        status=row["status"],
        received_at=row["received_at"],
    )


def handle_update(
    update: dict[str, Any], queue: Queue, allowed_chat_ids: AbstractSet[int], send: SendFn
) -> None:
    """React to one Telegram update: queue its links and acknowledge them."""
    message = update.get("message") or update.get("channel_post")
    if not message:
        return
    chat_id: int = message["chat"]["id"]
    message_id: int | None = message.get("message_id")
    text = (message.get("text") or "").strip()

    if not allowed_chat_ids:
        # Setup mode: only tell the sender their chat id, store nothing.
        send(
            chat_id,
            f"Your chat ID is {chat_id}. Add it to TELEGRAM_CHAT_ID (comma-separated) and restart.",
            None,
        )
        return
    if chat_id not in allowed_chat_ids:
        log.warning("ignoring message from chat %s", chat_id)
        return

    if text.startswith("/start"):
        send(chat_id, "Ready. Share recipe links here and I'll queue them for Mealie.", None)
        return
    if text.startswith("/queue"):
        items = queue.pending()
        lines = [f"{len(items)} link(s) waiting for the laptop."] + [f"• {i.url}" for i in items[:20]]
        send(chat_id, "\n".join(lines), None)
        return

    urls = extract_urls(message)
    if not urls:
        send(chat_id, "No link found in that message.", message_id)
        return
    fresh = 0
    for url in urls:
        _, is_new = queue.add(url, chat_id, message_id)
        fresh += is_new
    repeats = len(urls) - fresh
    if fresh and not repeats:
        reply = "Saved ✅" if fresh == 1 else f"Saved {fresh} links ✅"
    elif fresh:
        reply = f"Saved {fresh} link(s) ✅ ({repeats} already queued earlier)"
    else:
        reply = "Already queued earlier 👍"
    send(chat_id, reply, message_id)


def result_message(status: str, result: dict[str, Any]) -> str:
    note = (result.get("note") or "").strip()
    if status == "done":
        links = result.get("mealie_urls") or []
        head = "✅ Added to Mealie" if len(links) <= 1 else f"✅ Added {len(links)} recipes to Mealie"
        text = "\n".join([head, *links])
    elif status == "not_recipe":
        text = "🚫 Not a recipe, skipped."
    else:
        text = "⚠️ Couldn't process this link."
    return f"{text}\n{note}" if note else text


class TelegramClient:
    def __init__(self, token: str, timeout: int = 50) -> None:
        self._base = f"https://api.telegram.org/bot{token}/"
        self._timeout = timeout

    def _call(self, method: str, payload: dict[str, Any], timeout: float) -> Any:
        req = urllib.request.Request(
            self._base + method,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.load(resp)
        if not body.get("ok"):
            raise RuntimeError(f"Telegram {method} failed: {body.get('description')}")
        return body["result"]

    def get_updates(self, offset: int) -> list[dict[str, Any]]:
        return self._call(
            "getUpdates",
            {"offset": offset, "timeout": self._timeout, "allowed_updates": ["message", "channel_post"]},
            timeout=self._timeout + 10,
        )

    def send(self, chat_id: int, text: str, reply_to: int | None) -> None:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "link_preview_options": {"is_disabled": True},
        }
        if reply_to is not None:
            payload["reply_parameters"] = {"message_id": reply_to, "allow_sending_without_reply": True}
        try:
            self._call("sendMessage", payload, timeout=20)
        except (urllib.error.URLError, RuntimeError, TimeoutError) as exc:
            log.error("could not send Telegram message: %s", exc)


def poll_forever(client: TelegramClient, queue: Queue, allowed_chat_ids: AbstractSet[int]) -> None:
    offset = queue.get_offset()
    backoff = 1
    while True:
        try:
            updates = client.get_updates(offset)
            backoff = 1
        except (urllib.error.URLError, RuntimeError, TimeoutError, OSError) as exc:
            log.warning("getUpdates failed (%s), retrying in %ss", exc, backoff)
            time.sleep(backoff)
            backoff = min(backoff * 2, 60)
            continue
        for update in updates:
            try:
                handle_update(update, queue, allowed_chat_ids, client.send)
            except Exception:
                log.exception("failed to handle update %s", update.get("update_id"))
            offset = update["update_id"] + 1
            queue.set_offset(offset)


def make_api_handler(queue: Queue, api_token: str, send: SendFn) -> type[BaseHTTPRequestHandler]:
    expected = f"Bearer {api_token}".encode()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, code: int, body: dict[str, Any]) -> None:
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _authorized(self) -> bool:
            given = (self.headers.get("Authorization") or "").encode()
            if hmac.compare_digest(given, expected):
                return True
            self._json(401, {"error": "unauthorized"})
            return False

        def do_GET(self) -> None:
            if self.path == "/health":
                self._json(200, {"ok": True})
            elif self.path == "/pending":
                if self._authorized():
                    items = [
                        {"id": i.id, "url": i.url, "received_at": i.received_at} for i in queue.pending()
                    ]
                    self._json(200, {"items": items})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            match = re.fullmatch(r"/items/(\d+)/result", self.path)
            if not match:
                self._json(404, {"error": "not found"})
                return
            if not self._authorized():
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json(400, {"error": "invalid JSON"})
                return
            status = body.get("status")
            if status not in RESULT_STATUSES:
                self._json(400, {"error": f"status must be one of {', '.join(RESULT_STATUSES)}"})
                return
            item = queue.finish(int(match.group(1)), status, body)
            if item is None:
                self._json(404, {"error": "no such item"})
                return
            send(item.chat_id, result_message(status, body), item.message_id)
            self._json(200, {"ok": True})

        def log_message(self, format: str, *args: Any) -> None:
            log.info("api: " + format, *args)

    return Handler


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    api_token = os.environ["INBOX_API_TOKEN"]
    chat_raw = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    allowed_chat_ids = frozenset(int(c) for c in chat_raw.replace(";", ",").split(",") if c.strip())
    queue = Queue(os.environ.get("INBOX_DB", "/data/inbox.db"))
    client = TelegramClient(token)

    port = int(os.environ.get("INBOX_PORT", "8765"))
    server = ThreadingHTTPServer(("0.0.0.0", port), make_api_handler(queue, api_token, client.send))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    log.info("API listening on :%s", port)
    if not allowed_chat_ids:
        log.warning("TELEGRAM_CHAT_ID not set: setup mode, replying with chat IDs only")

    poll_forever(client, queue, allowed_chat_ids)


if __name__ == "__main__":
    main()
