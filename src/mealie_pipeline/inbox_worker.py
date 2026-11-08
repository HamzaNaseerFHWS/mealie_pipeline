"""`mp inbox-worker` (ticket 33): links shared to the Telegram inbox bot go through the pipeline, and
the bot is told how each one went.

One cycle:
1. `GET <inbox>/pending`. Each new link is remembered in `data/inbox_items.json` first, so a crash or
   a stop never loses it, then registered: a YouTube/Instagram/Facebook link as a Video of the Saved
   List `inbox:telegram`, any other web link as a recipe page (the path of a found Recipe Request).
2. The pipeline runs every stage, up to upload, for those Videos only (`only_videos`).
3. Each link whose outcome is final is reported: `POST <inbox>/items/<id>/result` with `done` and
   the Mealie link(s), `not_recipe` with the label, or `failed` with a short reason. A link that is
   still waiting (Mealie down, Claude's usage limit) is reported on a later cycle. A link that was
   reported is never reported again.

An unreachable bot is waited for: nothing is marked reported until the bot has taken it.
"""

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from mealie_pipeline.adapters.video_source import VideoSourceError
from mealie_pipeline.models import VideoMeta
from mealie_pipeline.pipeline import ALSO_ON, STAGES, Pipeline
from mealie_pipeline.store import StateStore
from mealie_pipeline.url_normalizer import NormalizedUrl, needs_redirect, normalize, normalize_web, resolve

STATE_FILE = Path("data") / "inbox_items.json"
NOTE_CHARS = 300  # of a failure reason sent to Telegram
FINAL_PART_STATES = {"done", "already_in_mealie", "upgraded_existing"}


class InboxUnavailable(Exception):
    """The bot's API did not answer, or refused: try again on the next cycle."""


@dataclass(frozen=True)
class InboxItem:
    id: int
    url: str


class InboxClient(Protocol):
    def pending(self) -> list[InboxItem]: ...

    def post_result(self, item_id: int, result: dict[str, Any]) -> None: ...


class HttpInboxClient:
    def __init__(self, base_url: str, token: str, *, timeout: float = 30.0):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    def pending(self) -> list[InboxItem]:
        data = self._call("GET", "/pending")
        return [InboxItem(int(i["id"]), str(i["url"])) for i in data.get("items") or []]

    def post_result(self, item_id: int, result: dict[str, Any]) -> None:
        self._call("POST", f"/items/{item_id}/result", json=result)

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as err:
            raise InboxUnavailable(f"inbox not reachable: {err}") from err
        if response.status_code == 404 and method == "POST":
            return {}  # the bot no longer knows the item: nothing left to report
        if not response.is_success:
            raise InboxUnavailable(f"inbox answered {response.status_code} to {method} {path}")
        return response.json() if response.content else {}


@dataclass
class Tracked:
    """One inbox link and where it stands."""

    id: int
    url: str
    video_key: str | None = None
    result: dict[str, Any] | None = None  # set once final
    posted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "url": self.url,
            "video_key": self.video_key,
            "result": self.result,
            "posted": self.posted,
        }


@dataclass
class CycleReport:
    received: int = 0
    reported: list[str] = field(default_factory=list)
    waiting: int = 0
    problems: list[str] = field(default_factory=list)
    stopped: str | None = None


class InboxWorker:
    def __init__(
        self,
        pipeline: Pipeline,
        client: InboxClient,
        *,
        expand: Callable[[str], str] = lambda url: url,
        list_key: str = "inbox:telegram",
        workers: int = 1,
    ):
        self.pipeline = pipeline
        self.store: StateStore = pipeline.store
        self.client = client
        self.expand = expand
        self.list_key = list_key
        self.workers = workers
        self.path = pipeline.workspace / STATE_FILE
        self.items: dict[int, Tracked] = self._load()

    # -- state ----------------------------------------------------------------------------

    def _load(self) -> dict[int, Tracked]:
        if not self.path.is_file():
            return {}
        raw = json.loads(self.path.read_text(encoding="utf-8"))
        return {int(i["id"]): Tracked(**i) for i in raw.get("items", [])}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        body = {"items": [t.as_dict() for t in sorted(self.items.values(), key=lambda t: t.id)]}
        temp.write_text(json.dumps(body, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, self.path)  # never a half-written file

    # -- one cycle ------------------------------------------------------------------------

    def cycle(self, should_stop: Callable[[], bool] = lambda: False) -> CycleReport:
        report = CycleReport()
        try:
            pending = self.client.pending()
        except InboxUnavailable as err:
            report.problems.append(str(err))
            pending = []  # links already taken are still run and reported below
        for item in pending:
            if item.id not in self.items:
                self.items[item.id] = Tracked(item.id, item.url)
                report.received += 1
        self._save()
        for tracked in self.items.values():
            if tracked.video_key is None and tracked.result is None:
                self._register(tracked)
        self._save()

        open_keys = {t.video_key for t in self.items.values() if t.result is None and t.video_key}
        if open_keys and not should_stop():
            run = self.pipeline.run(only_videos=open_keys, should_stop=should_stop, workers=self.workers)
            report.stopped = run.stopped or run.mealie_unreachable
        for tracked in self.items.values():
            if tracked.result is None and tracked.video_key:
                tracked.result = self.outcome(tracked.video_key)
        self._save()

        for tracked in sorted(self.items.values(), key=lambda t: t.id):
            if tracked.result is None:
                report.waiting += 1
                continue
            if tracked.posted:
                continue
            try:
                self.client.post_result(tracked.id, tracked.result)
            except InboxUnavailable as err:
                report.problems.append(str(err))
                break  # the bot is gone: the rest waits for the next cycle
            tracked.posted = True
            self._save()
            report.reported.append(f"{tracked.url}: {tracked.result['status']}")
        return report

    def _register(self, tracked: Tracked) -> None:
        """Turns the link into a Video of the inbox list, or a recipe-page item; a link that is
        neither is reported as failed."""
        video = resolve(tracked.url, self.expand)
        if video is None and needs_redirect(tracked.url):
            video = self._resolve_with_downloader(tracked.url)
        if video is not None:
            self.store.add_video(
                video.video_key, video.platform, video.video_id, tracked.url, video.canonical_url
            )
            self.store.add_video_url(video.video_key, tracked.url)
            tracked.video_key = video.video_key
        elif tracked.url.lower().startswith(("http://", "https://")) and (page := normalize_web(tracked.url)):
            if self.store.add_video(page.video_key, "web", page.video_id, tracked.url, page.canonical_url):
                meta = VideoMeta(title=page.canonical_url, webpage_url=page.canonical_url)
                self.store.set_metadata(page.video_key, meta.model_dump())
                self.store.record("video", page.video_key, "metadata", "done", "from the Telegram inbox")
                self.store.ensure_part(page.video_key, 1, 1)
            tracked.video_key = page.video_key
        else:
            tracked.result = failed("not a link the pipeline can read")
            return
        # Sending a link again is a request to retry it: stages that failed before run again.
        self.store.reset_stages(list(STAGES), keys=[tracked.video_key], failed_only=True)
        self.store.add_list(self.list_key, "telegram", "telegram://inbox")
        self.store.record_sync(
            self.list_key, sorted(self.store.list_video_keys(self.list_key) | {tracked.video_key})
        )

    def _resolve_with_downloader(self, url: str) -> NormalizedUrl | None:
        """A Facebook share link answers a plain request with an error, so the redirect cannot be
        followed; the downloader (yt-dlp) can, and tells which Video it points to."""
        try:
            meta = self.pipeline.a.videos.metadata(url)
        except VideoSourceError:
            return None
        return normalize(meta.webpage_url)

    # -- outcome --------------------------------------------------------------------------

    def outcome(self, video_key: str, _seen: frozenset[str] = frozenset()) -> dict[str, Any] | None:
        """The result to report for a Video, or None while it is still on its way."""
        store = self.store
        if store.stage_status("video", video_key, "metadata") == "failed":
            return failed(f"download failed: {store.stage_detail('video', video_key, 'metadata')}")
        classify = store.stage_status("video", video_key, "classify")
        if classify == "skipped":
            label = (store.video(video_key).classification or {}).get("label", "not a recipe")
            return {"status": "not_recipe", "mealie_urls": [], "note": label}
        if classify == "failed":
            return failed(f"classify: {store.stage_detail('video', video_key, 'classify')}")
        dedupe_detail = store.stage_detail("video", video_key, "dedupe") or ""
        if store.stage_status("video", video_key, "dedupe") == "skipped" and dedupe_detail.startswith(
            ALSO_ON
        ):
            canonical = dedupe_detail.removeprefix(ALSO_ON)  # the same recipe from another Video
            if canonical in _seen:
                return None
            return self.outcome(canonical, _seen | {video_key})
        for stage in ("scrape", "outline"):
            status = store.stage_status("video", video_key, stage)
            if status in ("failed", "review"):
                return failed(f"{stage}: {store.stage_detail('video', video_key, stage)}")
        parts = store.video_parts(video_key)
        if not parts:
            return None
        urls: list[str] = []
        for part in parts:
            records = {r.stage: r for r in store.stage_records() if r.entity_key == part.item_key}
            bad = next((r for r in records.values() if r.status in ("failed", "review")), None)
            if bad is not None:
                held = "held for review" if bad.status == "review" else "failed"
                return failed(f"{bad.stage} {held}: {bad.last_error or ''}")
            linkcheck = records.get("linkcheck")
            upload = records.get("upload")
            final = (upload and upload.status in FINAL_PART_STATES) or (
                linkcheck and linkcheck.status in ("already_in_mealie", "upgraded_existing")
            )
            if not final:
                return None
            if part.mealie_url:
                urls.append(part.mealie_url)
        return {"status": "done", "mealie_urls": urls, "note": ""}

    # -- the loop -------------------------------------------------------------------------

    def loop(
        self,
        poll_seconds: float,
        should_stop: Callable[[], bool],
        *,
        on_cycle: Callable[[CycleReport], None] = lambda _r: None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Cycles until `should_stop` (SIGTERM, Ctrl+C); waits `poll_seconds` between cycles."""
        while not should_stop():
            on_cycle(self.cycle(should_stop))
            waited = 0.0
            while waited < poll_seconds and not should_stop():
                step = min(1.0, poll_seconds - waited)
                sleep(step)
                waited += step


def failed(reason: str) -> dict[str, Any]:
    reason = " ".join(reason.split())
    if len(reason) > NOTE_CHARS:
        reason = reason[: NOTE_CHARS - 1] + "…"
    return {"status": "failed", "mealie_urls": [], "note": reason}
