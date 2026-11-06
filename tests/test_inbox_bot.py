"""Telegram inbox bot: link extraction, queueing, replies and the laptop-facing HTTP API."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from typing import Any

import pytest

from inbox_bot.bot import Queue, extract_urls, handle_update, make_api_handler

ME = 111
STRANGER = 999


class Sent:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, int | None]] = []

    def __call__(self, chat_id: int, text: str, reply_to: int | None) -> None:
        self.messages.append((chat_id, text, reply_to))


def update(text: str, chat_id: int = ME, message_id: int = 5, **extra: Any) -> dict[str, Any]:
    return {
        "update_id": 1,
        "message": {"message_id": message_id, "chat": {"id": chat_id}, "text": text, **extra},
    }


@pytest.fixture
def queue() -> Queue:
    return Queue(":memory:")


def test_extract_urls_from_shared_text_and_hidden_links() -> None:
    message = {
        "text": "Look at this (https://www.instagram.com/reel/abc/?igsh=x). Also https://youtu.be/xyz!",
        "entities": [{"type": "text_link", "url": "https://example.com/recipe"}],
    }
    assert extract_urls(message) == [
        "https://www.instagram.com/reel/abc/?igsh=x",
        "https://youtu.be/xyz",
        "https://example.com/recipe",
    ]


def test_extract_urls_reads_captions_and_drops_duplicates() -> None:
    message = {"caption": "https://youtu.be/a https://youtu.be/a"}
    assert extract_urls(message) == ["https://youtu.be/a"]


def test_link_from_my_chat_is_queued_and_acknowledged(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("https://youtu.be/a"), queue, {ME}, sent)

    [item] = queue.pending()
    assert (item.url, item.chat_id, item.message_id) == ("https://youtu.be/a", ME, 5)
    assert sent.messages == [(ME, "Saved ✅", 5)]


def test_same_link_twice_is_queued_once(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("https://youtu.be/a"), queue, {ME}, sent)
    handle_update(update("https://youtu.be/a", message_id=6), queue, {ME}, sent)

    assert len(queue.pending()) == 1
    assert sent.messages[-1] == (ME, "Already queued earlier 👍", 6)


def test_a_link_that_failed_can_be_sent_again(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("https://youtu.be/a"), queue, {ME}, sent)
    [first] = queue.pending()
    queue.finish(first.id, "failed", {"status": "failed", "note": "download failed"})

    handle_update(update("https://youtu.be/a", message_id=9), queue, {ME}, sent)

    [again] = queue.pending()
    assert (again.url, again.message_id) == ("https://youtu.be/a", 9)
    assert again.id != first.id
    assert sent.messages[-1] == (ME, "Saved ✅", 9)


def test_a_link_that_succeeded_is_not_queued_again(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("https://youtu.be/a"), queue, {ME}, sent)
    [first] = queue.pending()
    queue.finish(first.id, "done", {"status": "done"})

    handle_update(update("https://youtu.be/a", message_id=9), queue, {ME}, sent)

    assert queue.pending() == []
    assert sent.messages[-1] == (ME, "Already queued earlier 👍", 9)


def test_messages_from_other_chats_are_ignored(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("https://youtu.be/a", chat_id=STRANGER), queue, {ME}, sent)

    assert queue.pending() == []
    assert sent.messages == []


def test_a_second_allowed_chat_can_queue_links_and_gets_its_own_replies(queue: Queue) -> None:
    sent = Sent()
    partner = 777
    handle_update(update("https://youtu.be/a"), queue, {ME, partner}, sent)
    handle_update(update("https://youtu.be/b", chat_id=partner), queue, {ME, partner}, sent)
    handle_update(update("https://youtu.be/c", chat_id=STRANGER), queue, {ME, partner}, sent)

    assert sorted((i.url, i.chat_id) for i in queue.pending()) == [
        ("https://youtu.be/a", ME),
        ("https://youtu.be/b", partner),
    ]
    assert [m[0] for m in sent.messages] == [ME, partner]


def test_setup_mode_only_reports_the_chat_id(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("https://youtu.be/a", chat_id=STRANGER), queue, frozenset(), sent)

    assert queue.pending() == []
    assert "999" in sent.messages[0][1]


def test_message_without_link_gets_a_hint(queue: Queue) -> None:
    sent = Sent()
    handle_update(update("hello"), queue, {ME}, sent)

    assert queue.pending() == []
    assert sent.messages == [(ME, "No link found in that message.", 5)]


def test_update_offset_survives_reopening(tmp_path: Any) -> None:
    path = str(tmp_path / "inbox.db")
    Queue(path).set_offset(42)
    assert Queue(path).get_offset() == 42


# --- HTTP API --------------------------------------------------------------------------------------------

TOKEN = "s3cret"


@pytest.fixture
def api(queue: Queue) -> Iterator[tuple[str, Sent]]:
    sent = Sent()
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_api_handler(queue, TOKEN, sent))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", sent
    server.shutdown()
    server.server_close()


def call(url: str, body: dict[str, Any] | None = None, token: str | None = TOKEN) -> tuple[int, Any]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as err:
        return err.code, json.load(err)


def test_pending_requires_the_api_token(api: tuple[str, Sent]) -> None:
    base, _ = api
    assert call(f"{base}/pending", token=None)[0] == 401
    assert call(f"{base}/pending", token="wrong")[0] == 401
    assert call(f"{base}/health", token=None) == (200, {"ok": True})


def test_laptop_fetches_pending_and_reports_result(queue: Queue, api: tuple[str, Sent]) -> None:
    base, sent = api
    item, _ = queue.add("https://youtu.be/a", ME, 5)

    status, body = call(f"{base}/pending")
    assert status == 200
    assert [i["url"] for i in body["items"]] == ["https://youtu.be/a"]

    result = {"status": "done", "mealie_urls": ["http://mealie/g/home/r/dal", "http://mealie/g/home/r/rice"]}
    assert call(f"{base}/items/{item.id}/result", result) == (200, {"ok": True})

    assert queue.pending() == []
    chat_id, text, reply_to = sent.messages[-1]
    assert (chat_id, reply_to) == (ME, 5)
    assert text.splitlines() == [
        "✅ Added 2 recipes to Mealie",
        "http://mealie/g/home/r/dal",
        "http://mealie/g/home/r/rice",
    ]


def test_not_recipe_result_is_reported(queue: Queue, api: tuple[str, Sent]) -> None:
    base, sent = api
    item, _ = queue.add("https://youtu.be/a", ME, 5)

    call(f"{base}/items/{item.id}/result", {"status": "not_recipe"})

    assert sent.messages[-1] == (ME, "🚫 Not a recipe, skipped.", 5)


def test_bad_result_requests_are_rejected(queue: Queue, api: tuple[str, Sent]) -> None:
    base, sent = api
    item, _ = queue.add("https://youtu.be/a", ME, 5)

    assert call(f"{base}/items/{item.id}/result", {"status": "maybe"})[0] == 400
    assert call(f"{base}/items/9999/result", {"status": "done"})[0] == 404
    assert len(queue.pending()) == 1
    assert sent.messages == []
