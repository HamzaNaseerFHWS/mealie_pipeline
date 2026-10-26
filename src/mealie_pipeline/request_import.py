"""Recipe Requests as work items for the pipeline (ticket 28).

A `found` request becomes an ordinary Video-shaped item with platform `web`: Video Key
`web:<hash of the page URL>`, Item Key `web:<hash>#1`. Its `metadata` stage is done from the start
(there is no video), and its `scrape` stage reads the chosen page as the only Source. From there it
runs `linkcheck -> scrape -> extract -> parse -> tag -> verify -> upload` like every other item.
After a run the request's status is brought up to date from those stage records.
"""

from mealie_pipeline.models import VideoMeta
from mealie_pipeline.recipe_requests import RecipeRequests
from mealie_pipeline.store import RecipePart, StageRecord, StateStore
from mealie_pipeline.url_normalizer import normalize_web


def register_found(store: StateStore, requests: RecipeRequests) -> list[str]:
    """Creates the work item for every `found` request that has none yet; returns their Item Keys.

    Cells that found the same page share one item, so one Mealie recipe answers all of them."""
    created: list[str] = []
    for request in requests.with_status("found"):
        if request.item_key or not request.chosen_url:
            continue
        page = normalize_web(request.chosen_url)
        if page is None:
            requests.set_outcome(request.id, "failed", last_error=f"unusable URL: {request.chosen_url}")
            continue
        if store.add_video(page.video_key, "web", page.video_id, request.chosen_url, page.canonical_url):
            meta = VideoMeta(title=request.name, webpage_url=page.canonical_url)
            store.set_metadata(page.video_key, meta.model_dump())
            store.record("video", page.video_key, "metadata", "done", "from a recipe request")
            created.append(store.ensure_part(page.video_key, 1, 1))
        requests.set_item_key(request.id, f"{page.video_key}#1")
    return created


def sync_outcomes(store: StateStore, requests: RecipeRequests) -> int:
    """Brings every started request's status up to date from its item's Stage Records; returns how
    many changed."""
    by_item: dict[str, dict[str, StageRecord]] = {}
    for record in store.stage_records():
        by_item.setdefault(record.entity_key, {})[record.stage] = record
    changed = 0
    for request in requests.all():
        if not request.item_key or request.status in ("pending", "needs_choice", "not_found"):
            continue
        status, fields = import_outcome(store.part(request.item_key), by_item.get(request.item_key, {}))
        wanted = {
            "slug": fields.get("slug"),
            "mealie_url": fields.get("mealie_url"),
            "reason": fields.get("reason"),
            "last_error": fields.get("last_error"),
        }
        if (status, wanted["slug"], wanted["mealie_url"], wanted["reason"], wanted["last_error"]) == (
            request.status,
            request.slug,
            request.mealie_url,
            request.reason,
            request.last_error,
        ) and fields.get("score") in (None, request.score):
            continue
        requests.set_outcome(request.id, status, **fields)  # type: ignore[arg-type]
        changed += 1
    return changed


def import_outcome(part: RecipePart, records: dict[str, StageRecord]) -> tuple[str, dict[str, object]]:
    """`(status, fields)` for a request whose item is being or has been imported."""
    verify = part.verify or {}
    score = verify.get("score")
    if "upload" in records and records["upload"].status == "done":
        note = "imported with the To Review tag" if verify.get("outcome") == "upload_review" else "imported"
        return "imported", {"slug": part.slug, "mealie_url": part.mealie_url, "score": score, "reason": note}
    if "linkcheck" in records and records["linkcheck"].status == "already_in_mealie":
        return "already_in_mealie", {"mealie_url": part.mealie_url, "reason": "its link is already in Mealie"}
    for record in records.values():
        if record.status == "review":
            return "review", {"score": score, "reason": record.last_error or "held back by the Gate"}
    for record in records.values():
        if record.status == "failed":
            return "failed", {"last_error": f"{record.stage}: {record.last_error or 'failed'}"}
    return "found", {}  # nothing wrong (any earlier failure was reset by `mp retry`)
