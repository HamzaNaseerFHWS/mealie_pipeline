"""The Stage Runner: metadata -> classify -> linkcheck -> scrape -> extract -> parse -> tag -> verify
-> upload.

Each stage is a function over the State Store with an `Adapters` bundle. A failure in one entity is
recorded on its Stage Record and never stops the stage. Re-running changes nothing that is `done`.
"""

import contextlib
import csv
import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mealie_pipeline import dedupe, grounding
from mealie_pipeline.adapters import Adapters
from mealie_pipeline.adapters.llm import LLMError, Tier, UsageLimited
from mealie_pipeline.adapters.mealie import Catalog, Food, Unit
from mealie_pipeline.adapters.video_source import VideoSourceError
from mealie_pipeline.classify import (
    Classifier,
    ClassifyInput,
    ClassifyRules,
    Verdict,
    read_overrides,
    signals,
    video_meta,
    write_classification_csv,
)
from mealie_pipeline.creators import CreatorRegistry, creator_handle
from mealie_pipeline.errors import MealieError
from mealie_pipeline.existing_links import build_link_set
from mealie_pipeline.find import single_recipe
from mealie_pipeline.images import attach_image, candidate_urls
from mealie_pipeline.matching import FoodMatcher, UnitNormalizer
from mealie_pipeline.models import (
    ExtractedRecipe,
    Judge,
    Outline,
    ParsedIngredient,
    VideoMeta,
    extraction_schema,
)
from mealie_pipeline.outline import OutlineError, detect_signals, segment, validate_outline
from mealie_pipeline.payload import build_payload
from mealie_pipeline.protein import ProteinRules, RecipeText, detect, tag_key
from mealie_pipeline.recipe_extraction import SourceRecipe, extract_recipes
from mealie_pipeline.recipe_extraction import format_for_prompt as web_text
from mealie_pipeline.recipe_requests import RecipeRequest, RecipeRequests
from mealie_pipeline.reconcile import reconcile
from mealie_pipeline.request_import import register_found, sync_outcomes
from mealie_pipeline.review import write_review_file
from mealie_pipeline.sanity import check_line
from mealie_pipeline.scoring import apply_judge, decide
from mealie_pipeline.scrape import WebResult, find_web_recipe
from mealie_pipeline.settings import Settings, VerifySettings
from mealie_pipeline.store import EntityKind, RecipePart, StateStore, Status
from mealie_pipeline.tagging import RecipeFacts, TagRules, choose, contradictions, match_existing, rule_tags
from mealie_pipeline.url_normalizer import normalize_website
from mealie_pipeline.verify import Evaluation, evaluate

STAGES = [
    "metadata",
    "classify",
    "dedupe",
    "linkcheck",
    "scrape",
    "outline",
    "extract",
    "parse",
    "tag",
    "verify",
    "upload",
]
# Stages that run once per Video; the rest run per Recipe Part.
VIDEO_STAGES = {"metadata", "classify", "dedupe", "scrape", "outline"}
# The stage that must be done first for the same entity. A Video's Recipe Parts exist only once
# `classify` let it through (a Recipe Request's from the start), so `linkcheck` has no prerequisite.
# `scrape` (per Video) waits for a Part's `linkcheck`, and `extract` waits for its Part's `linkcheck`
# and its Video's `scrape`. Every stage after `classify` takes only Videos it let through, and
# every stage after `dedupe` only the canonical Video of a group (the others are `also_on`).
PREREQUISITE: dict[str, str | None] = {
    "metadata": None,
    "classify": "metadata",
    "dedupe": "classify",
    "linkcheck": None,
    "scrape": "metadata",
    "outline": "scrape",
    "extract": "linkcheck",
    "parse": "extract",
    "tag": "parse",
    "verify": "tag",
    "upload": "verify",
}
MAX_TAGS = 6
ALSO_ON = "also_on:"  # a Video `dedupe` folded into the canonical Video named after it
SIBLING_OF = "sibling_of:"  # a group member that had already gone on before `dedupe` grouped it
# Stages that only read the web or call `claude` for one item at a time: they can use several workers.
# parse, tag, verify and upload write to Mealie and its Catalog, so they always run one at a time.
PARALLEL_STAGES = {"scrape", "extract"}
WEB_STRUCTURED_RULE = (
    "The [SRC:web] block is the creator's own written recipe. Keep the website's quantities and wording "
    "and only fill gaps (missing times or servings) and merge in useful tips from the video description; "
    "do not rewrite or reinterpret it."
)
WEB_TEXT_RULE = (
    "The [SRC:web] block is unstructured text from the creator's website. Extract the recipe from it as "
    "you would from a description, preferring it over the video description when they differ."
)
TO_TASTE = "to taste"
SIBLING_TITLE = "Also in this video"  # the title that marks the sibling note


@dataclass
class RunReport:
    done: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    already_in_mealie: list[str] = field(default_factory=list)
    not_recipes: list[str] = field(default_factory=list)  # skipped by `classify`, with their label
    duplicates: list[str] = field(default_factory=list)  # folded into another Video by `dedupe`
    upgraded_existing: list[str] = field(default_factory=list)
    dry_run_files: list[Path] = field(default_factory=list)
    stopped: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def count(self, stage: str) -> None:
        with self._lock:
            self.done[stage] = self.done.get(stage, 0) + 1

    def sort_lines(self) -> None:
        """Workers finish in any order; the report lists items in key order, as a single worker would."""
        lists = (
            self.failed,
            self.review,
            self.already_in_mealie,
            self.upgraded_existing,
            self.warnings,
            self.not_recipes,
            self.duplicates,
        )
        for lines in lists:
            lines.sort()


class Pipeline:
    def __init__(
        self,
        workspace: Path,
        settings: Settings,
        adapters: Adapters,
        store: StateStore,
        *,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
    ):
        self.workspace = workspace
        self.settings = settings
        self.a = adapters
        self.store = store
        self.now = now
        self._catalog: Catalog | None = None
        self._catalog_lock = threading.Lock()  # workers must not each download the whole Catalog
        self._detail: dict[str, str] = {}
        self._uploaded_videos: set[str] = set()
        self.mode = "skip"
        self.upgrade_existing = False
        self._links: dict[str, str] | None = None
        units = workspace / "config" / "units.yaml"
        synonyms = yaml.safe_load(units.read_text(encoding="utf-8")) if units.is_file() else {}
        self.units = UnitNormalizer(synonyms or {})
        self.foods = FoodMatcher()
        self.rules = ClassifyRules.load(workspace / "config" / "classify_rules.yaml")
        selectors = workspace / "config" / "site_selectors.yaml"
        self.selectors: dict[str, dict[str, str]] = (
            yaml.safe_load(selectors.read_text(encoding="utf-8")) if selectors.is_file() else {}
        ) or {}
        proteins = workspace / "config" / "protein_tags.yaml"
        self.proteins = ProteinRules.load(proteins) if proteins.is_file() else None
        tag_rules = workspace / "config" / "tag_rules.yaml"
        self.tag_rules = TagRules.load(tag_rules) if tag_rules.is_file() else None

    # -- public ---------------------------------------------------------------------------

    def add(self, canonical_url: str, url: str, platform: str, video_id: str) -> bool:
        return self.store.add_video(f"{platform}:{video_id}", platform, video_id, url, canonical_url)

    def run(
        self,
        *,
        stages: list[str] | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        mode: str = "skip",
        upgrade_existing: bool = False,
        should_stop: Callable[[], bool] = lambda: False,
        workers: int = 1,
    ) -> RunReport:
        """Runs the stages over every Video and every found Recipe Request that is ready (see `_run`).

        Found requests become work items first; their status is brought up to date at the end, even
        when the run is interrupted."""
        requests = RecipeRequests(self.store)
        register_found(self.store, requests)
        try:
            return self._run(
                stages=stages,
                limit=limit,
                dry_run=dry_run,
                mode=mode,
                upgrade_existing=upgrade_existing,
                should_stop=should_stop,
                workers=workers,
            )
        finally:
            sync_outcomes(self.store, requests)

    def _run(
        self,
        *,
        stages: list[str] | None = None,
        limit: int | None = None,
        dry_run: bool = False,
        mode: str = "skip",
        upgrade_existing: bool = False,
        should_stop: Callable[[], bool] = lambda: False,
        workers: int = 1,
    ) -> RunReport:
        """Runs the stages in order over every entity that is ready.

        `should_stop` is polled between entities (Ctrl+C sets it): the entity in progress finishes,
        then the run returns. Whatever was not reached stays pending for the next run.
        """
        report = RunReport()
        self.mode = mode
        self.upgrade_existing = upgrade_existing
        wanted = stages or STAGES
        handlers: dict[str, Callable[[str, RunReport, bool], None]] = {
            "metadata": self._metadata,
            "linkcheck": self._linkcheck,
            "scrape": self._scrape,
            "outline": self._outline,
            "extract": self._extract,
            "parse": self._parse,
            "tag": self._tag,
            "verify": self._verify,
            "upload": self._upload,
        }
        for stage in STAGES:
            if stage not in wanted:
                continue
            kind = "video" if stage in VIDEO_STAGES else "part"
            previous = PREREQUISITE[stage]
            # In a dry run nothing past `extract` is recorded, so the later stages preview instead.
            if dry_run and stage in ("parse", "tag", "verify", "upload"):
                if stage == "upload":
                    self._preview(report, limit)
                continue
            if stage in ("linkcheck", "upload"):
                self._links = None  # one fresh listing of Mealie per batch
            batch = self.store.next_batch(kind, stage, previous)
            if stage not in ("metadata", "classify"):  # only Videos `classify` let through
                batch = [
                    key
                    for key in batch
                    if self._let_through(key if kind == "video" else self.store.part(key).video_key)
                ]
            if stage == "scrape":  # only Videos that still have a Part to import (not already in Mealie)
                wanted_videos = {
                    p.video_key
                    for p in self.store.parts()
                    if self.store.stage_status("part", p.item_key, "linkcheck") == "done"
                }
                batch = [key for key in batch if key in wanted_videos]
            if stage == "extract":  # wait for the Video's recipe website (`scrape`) and its `outline`
                batch = [
                    key for key in batch if self._ready_to_extract(self.store.part(key).video_key, wanted)
                ]
            todo = batch[:limit] if limit is not None else batch
            if stage == "classify":  # batched: many Videos per LLM call
                if not self._classify(todo, report, should_stop):
                    return report
                continue
            if stage == "dedupe":  # groups need every Video at once, so it also revisits earlier ones
                self._dedupe(todo, report)
                continue
            if workers > 1 and stage in PARALLEL_STAGES and len(todo) > 1:
                stop = self._run_parallel(
                    kind, stage, todo, handlers[stage], report, dry_run, workers, should_stop
                )
                if stop:
                    report.sort_lines()
                    return report
                continue
            for key in todo:
                if should_stop():
                    report.stopped = (
                        "Interrupted: finished the current item and stopped. Run again to continue."
                    )
                    return report
                self.store.record(kind, key, stage, "running")
                if not self._process(kind, key, stage, handlers[stage], report, dry_run):
                    return report
            if stage == "upload" and not dry_run:
                self._link_siblings(report)
        if workers > 1:
            report.sort_lines()
        return report

    def _ready_to_extract(self, video_key: str, wanted: list[str]) -> bool:
        if self.store.stage_status("video", video_key, "scrape") != "done":
            return False
        outline = self.store.stage_status("video", video_key, "outline")
        return outline == "done" or (outline is None and "outline" not in wanted)

    def _process(
        self,
        kind: EntityKind,
        key: str,
        stage: str,
        handler: Callable[[str, RunReport, bool], None],
        report: RunReport,
        dry_run: bool,
    ) -> bool:
        """Runs one entity through one stage and records the outcome; False when the run must stop
        (Claude usage limit). A failure here never stops the other entities."""
        try:
            handler(key, report, dry_run)
        except UsageLimited as err:
            self.store.record(kind, key, stage, "pending", str(err))
            report.stopped = f"Claude usage limit reached: {err}. Run again after it resets."
            return False
        except AlreadyInMealie as err:
            link = self.a.mealie.recipe_url(err.slug)
            self.store.update_part(key, mealie_url=link)
            self.store.record(kind, key, stage, err.status, link)
            if isinstance(err, UpgradedExisting):
                self.store.update_part(key, slug=err.slug)
                report.upgraded_existing.append(f"{key}: {link}")
            else:
                report.already_in_mealie.append(f"{key}: {link}")
        except NeedsReview as err:
            self.store.record(kind, key, stage, "review", str(err))
            report.review.append(f"{key}: {err}")
        except Exception as err:  # one entity's failure never stops the others
            self.store.record(kind, key, stage, "failed", describe_error(err))
            report.failed.append(f"{key} [{stage}]: {describe_error(err)}")
        except BaseException:  # Ctrl+C or a crash: give the claim back instead of leaving it running
            self.store.record(kind, key, stage, "pending")
            raise
        else:
            self.store.record(kind, key, stage, "done", self._detail.pop(key, None))
            report.count(stage)
        return True

    def _run_parallel(
        self,
        kind: EntityKind,
        stage: str,
        keys: list[str],
        handler: Callable[[str, RunReport, bool], None],
        report: RunReport,
        dry_run: bool,
        workers: int,
        should_stop: Callable[[], bool],
    ) -> bool:
        """One stage over several entities at once; True when the run must stop afterwards.

        Each item is claimed atomically, so none is taken twice (also by another `mp run`). A usage
        limit or Ctrl+C stops new items from starting; the ones already running finish."""
        halt = threading.Event()
        interrupted = threading.Event()
        stale = self.settings.run.stale_minutes

        def work(key: str) -> None:
            if halt.is_set():
                return
            if should_stop():
                interrupted.set()
                return
            if not self.store.claim(kind, key, stage, stale):
                return  # another run has it
            if not self._process(kind, key, stage, handler, report, dry_run):
                halt.set()

        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix=f"mp-{stage}")
        try:
            for future in [pool.submit(work, key) for key in keys]:
                future.result()
        except BaseException:  # Ctrl+C or a crash: start nothing else, let the running items finish
            halt.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        pool.shutdown()
        if interrupted.is_set() and report.stopped is None:
            report.stopped = "Interrupted: finished the current item and stopped. Run again to continue."
        return report.stopped is not None

    # -- catalog --------------------------------------------------------------------------

    @property
    def catalog(self) -> Catalog:
        with self._catalog_lock:
            if self._catalog is None:
                self._catalog = self.a.mealie.catalog()
            return self._catalog

    # -- stages ---------------------------------------------------------------------------

    def _metadata(self, video_key: str, report: RunReport, dry_run: bool) -> None:
        video = self.store.video(video_key)
        if video.platform == "web":  # a Recipe Request: there is no video, its metadata was set up front
            self.store.ensure_part(video_key, 1, 1)
            return
        meta = self.a.videos.metadata(video.canonical_url)
        self.store.set_metadata(video_key, meta.model_dump())

    def _let_through(self, video_key: str) -> bool:
        """A Recipe Request always; a Video once `classify` labelled it a recipe and `dedupe` did not
        fold it into another Video."""
        if self.store.video(video_key).platform == "web":
            return True
        return (
            self.store.stage_status("video", video_key, "classify") == "done"
            and self.store.stage_status("video", video_key, "dedupe") != "skipped"
        )

    def _classify(self, keys: list[str], report: RunReport, should_stop: Callable[[], bool]) -> bool:
        """Labels the Videos in batches; False when the run must stop. Recipe Requests are no Videos
        to classify. Overrides from `reports/classification.csv` win, also over earlier verdicts."""
        csv_path = self.workspace / "reports" / "classification.csv"
        overrides, warnings = read_overrides(csv_path)
        report.warnings += warnings
        try:
            for video in self.store.videos():  # an Override set or changed since the last run
                label = overrides.get(video.video_key)
                status = self.store.stage_status("video", video.video_key, "classify")
                if (
                    label
                    and status in ("done", "skipped")
                    and (video.classification or {}).get("label") != label
                ):
                    self._decide(video.video_key, by_hand(label), report)
            self._links = None  # one fresh listing of Mealie per batch
            ask: list[str] = []
            for key in keys:
                if self.store.video(key).platform == "web":
                    continue
                if key in overrides:
                    self._decide(key, by_hand(overrides[key]), report)
                elif self._already_in_mealie(key):  # no LLM call; `linkcheck` then records it
                    reason = "its link is already a recipe in Mealie"
                    self._decide(key, Verdict("recipe", 1.0, [reason], source="existing"), report)
                else:
                    ask.append(key)
            return self._classify_with_llm(ask, report, should_stop)
        finally:
            write_classification_csv(self.store, csv_path, self.rules)

    def _classify_with_llm(self, keys: list[str], report: RunReport, should_stop: Callable[[], bool]) -> bool:
        classifier = Classifier(self.a.llm, self.settings.classify, self.a.videos.subtitles)
        size = self.settings.classify.batch_size
        for start in range(0, len(keys), size):
            if should_stop():
                report.stopped = "Interrupted: finished the current item and stopped. Run again to continue."
                return False
            chunk = keys[start : start + size]
            inputs = []
            for key in chunk:
                self.store.record("video", key, "classify", "running")
                video = self.store.video(key)
                meta = video_meta(video)
                inputs.append(ClassifyInput(key, video.canonical_url, meta, signals(meta, self.rules)))
            try:
                verdicts = classifier.classify(inputs)
            except UsageLimited as err:
                for key in chunk:
                    self.store.record("video", key, "classify", "pending", str(err))
                report.stopped = f"Claude usage limit reached: {err}. Run again after it resets."
                return False
            except LLMError as err:  # the batch fails; `mp retry` or the next run asks again
                for key in chunk:
                    self.store.record("video", key, "classify", "failed", describe_error(err))
                    report.failed.append(f"{key} [classify]: {describe_error(err)}")
                continue
            for key in chunk:
                self._decide(key, verdicts[key], report)
        return True

    def _already_in_mealie(self, video_key: str) -> bool:
        try:
            return self._link_key(video_key) in self._link_set()
        except MealieError:
            return False  # Mealie is not reachable: classify as usual

    def _decide(self, video_key: str, verdict: Verdict, report: RunReport) -> None:
        """Stores the Video Label; a recipe gets its Recipe Part and goes on, anything else is skipped."""
        self.store.set_classification(video_key, verdict.as_dict())
        detail = f"{verdict.label} ({verdict.confidence:.2f})"
        if verdict.reasons:
            detail += f": {verdict.reasons[0]}"
        if verdict.passes:
            self.store.ensure_part(video_key, 1, 1)
            self.store.record("video", video_key, "classify", "done", detail)
            report.count("classify")
        else:
            self.store.record("video", video_key, "classify", "skipped", detail)
            report.not_recipes.append(f"{video_key}: {detail}")

    # -- dedupe ---------------------------------------------------------------------------

    def _dedupe(self, keys: list[str], report: RunReport) -> None:
        """Groups near-duplicate Videos and lets only the canonical Video of each group go on.

        Every Video `classify` let through is grouped, not just the new ones, so a Video that arrives
        later joins the group of one that went on earlier. A group member whose link is already in
        Mealie is the canonical one, so the group resolves to that recipe. Overrides from
        `reports/dedupe.csv` win. A Video not yet extracted follows a changed group; one that already
        went on does not."""
        csv_path = self.workspace / "reports" / "dedupe.csv"
        overrides, warnings = dedupe.read_overrides(csv_path)
        report.warnings += warnings
        videos = [
            v
            for v in self.store.videos()
            if v.platform != "web" and self.store.stage_status("video", v.video_key, "classify") == "done"
        ]
        cands = {v.video_key: self._dedupe_candidate(v) for v in videos}
        settled = frozenset(
            k for k in cands if self.store.stage_status("video", k, "dedupe") == "done" or self._started(k)
        )
        groups = dedupe.plan_groups(list(cands.values()), overrides, settled=settled)
        links: dict[str, str] = {}
        if groups:  # Mealie is asked only when there is a group to resolve against it
            self._links = None  # one fresh listing of Mealie per batch
            with contextlib.suppress(MealieError):  # Mealie is not reachable: group without it
                links = self._link_set()
            groups = dedupe.plan_groups(
                list(cands.values()),
                overrides,
                existing=frozenset(k for k in cands if k in links),
                settled=settled,
            )
        folded = {member: g for g in groups for member in g.also_on}
        grouped = {g.canonical for g in groups} | set(folded)
        pending = set(keys)
        for key in cands:
            status = self.store.stage_status("video", key, "dedupe")
            group = folded.get(key)
            if group is not None and not self._started(key):
                detail = f"{ALSO_ON}{group.canonical}"
                if status != "skipped" or self.store.stage_detail("video", key, "dedupe") != detail:
                    self.store.record("video", key, "dedupe", "skipped", detail)
                    report.duplicates.append(f"{key}: also on {group.canonical} ({group.reason})")
            elif group is not None:  # went on before it was grouped: confirmed after parsing
                if key in pending or status is None:
                    self.store.record("video", key, "dedupe", "done", f"{SIBLING_OF}{group.canonical}")
                    report.count("dedupe")
            elif key in pending or status == "skipped":
                self.store.record("video", key, "dedupe", "done", "in a group" if key in grouped else "")
                report.count("dedupe")
        self._write_dedupe_csv(csv_path, groups, cands, overrides, links)

    def _started(self, video_key: str) -> bool:
        """Has the Video's Recipe Part gone past `dedupe` (extracted, or already in Mealie)?"""
        parts = [p for p in self.store.parts() if p.video_key == video_key]
        return any(p.extracted is not None or p.slug for p in parts)

    def _dedupe_candidate(self, video: Any) -> dedupe.Candidate:
        meta = video_meta(video)
        return dedupe.candidate(
            video.video_key,
            video.platform,
            video.canonical_url,
            handle=creator_handle(meta),
            title=meta.title,
            description=meta.description,
            upload_date=meta.upload_date,
        )

    def _write_dedupe_csv(
        self,
        path: Path,
        groups: list[dedupe.Group],
        cands: dict[str, dedupe.Candidate],
        overrides: dict[str, str],
        links: dict[str, str],
    ) -> None:
        rows = []
        shown: set[str] = set()
        for group in groups:
            for key in (group.canonical, *group.also_on):
                role = "canonical" if key == group.canonical else "also_on"
                reason = group.reason if role == "canonical" else ""
                if key in links:
                    reason = ("in Mealie; " + reason).strip("; ")
                rows.append(self._dedupe_row(cands[key], group.canonical, role, reason, overrides))
                shown.add(key)
        for key, value in overrides.items():  # an Override stays in the file also when its group is gone
            if key in cands and key not in shown:
                rows.append(
                    self._dedupe_row(cands[key], "", "split" if value == "split" else "alone", "", overrides)
                )
        dedupe.write_csv(path, rows)

    def _dedupe_row(
        self, cand: dedupe.Candidate, canonical: str, role: str, reason: str, overrides: dict[str, str]
    ) -> dict[str, str]:
        creator = video_meta(self.store.video(cand.video_key)).uploader
        return {
            "group_id": canonical or cand.video_key,
            "video_key": cand.video_key,
            "url": cand.url,
            "platform": cand.platform,
            "title": cand.title,
            "creator": creator,
            "role": role,
            "canonical_key": canonical,
            "reason": reason,
            "override": overrides.get(cand.video_key, ""),
        }

    def _confirm_group(self, item_key: str) -> list[str]:
        """After parsing: a group member that went on anyway is checked against its group's canonical
        recipe by food-level Jaccard. A pair under 0.7 is split again (the sibling stands alone)."""
        found = []
        for sibling, canonical in self._group_pairs(self.store.part(item_key).video_key):
            mine, theirs = (self._foods(k) for k in (sibling, canonical))
            if mine is None or theirs is None:
                continue  # the other recipe is not parsed yet: checked when it is
            if dedupe.confirmed(mine, theirs):
                self.store.record("video", sibling, "dedupe", "done", f"{ALSO_ON}{canonical}")
            else:
                score = dedupe.jaccard(mine, theirs)
                self.store.record(
                    "video", sibling, "dedupe", "done", f"split after parsing: overlap {score:.2f}"
                )
                found.append(f"{sibling}: not the same dish as {canonical} (food overlap {score:.2f}), split")
        return found

    def _foods(self, video_key: str) -> set[str] | None:
        parts = [p for p in self.store.parts() if p.video_key == video_key and p.parsed]
        return dedupe.foods_of([p["food_name"] for p in parts[0].parsed or []]) if parts else None

    def _group_pairs(self, video_key: str) -> list[tuple[str, str]]:
        """`(sibling, canonical)` pairs this Video belongs to, where the sibling went on anyway."""
        pairs = []
        for record in self.store.stage_records():
            if record.stage != "dedupe" or record.status != "done" or not record.last_error:
                continue
            if not record.last_error.startswith(SIBLING_OF):
                continue
            canonical = record.last_error.removeprefix(SIBLING_OF)
            if video_key in (record.entity_key, canonical):
                pairs.append((record.entity_key, canonical))
        return pairs

    def _web_path(self, video_key: str) -> Path:
        video = self.store.video(video_key)
        return self.workspace / "data" / video.platform / video.video_id / "web.json"

    def _web(self, video_key: str) -> WebResult | None:
        """The Recipe Website result stored by `scrape`, if it found a usable recipe."""
        path = self._web_path(video_key)
        if not path.is_file():
            return None
        result = WebResult.model_validate_json(path.read_text(encoding="utf-8"))
        return result if result.usable else None

    def _scrape_request_page(self, video_key: str) -> None:
        """A Recipe Request's chosen page is the only Source: read it into `web.json`."""
        video = self.store.video(video_key)
        page = self.a.web.fetch(video.canonical_url)
        if not page.ok:
            raise StageFailure(f"could not read the page ({page.blocked or 'HTTP ' + str(page.status)})")
        recipe = single_recipe(extract_recipes(page.html, page.final_url, self.selectors))
        if recipe is None:
            raise StageFailure("the page no longer holds exactly one recipe")
        result = WebResult(link=video.canonical_url, final_url=page.final_url, recipes=[recipe], chosen=0)
        path = self._web_path(video_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=1), encoding="utf-8")
        self._detail[video_key] = f"{recipe.extraction_method} {page.final_url}"

    def _scrape(self, video_key: str, report: RunReport, dry_run: bool) -> None:
        video = self.store.video(video_key)
        if video.platform == "web":
            return self._scrape_request_page(video_key)
        meta = VideoMeta.model_validate(video.metadata)
        web = self.settings.web
        comment = self.a.videos.pinned_comments(video.canonical_url) if web.fetch_pinned_comment else ""
        registry = CreatorRegistry(self.store)
        handle = creator_handle(meta)
        result = find_web_recipe(
            title=meta.title,
            description=meta.description,
            pinned_comment=comment,
            fetcher=self.a.web,
            selectors=self.selectors,
            max_pages=web.max_pages,
            browser=self.a.browser,
            link_in_bio_hosts=web.link_in_bio_hosts,
            bio_min_score=web.bio_min_score,
            render_blocked=web.render_blocked,
            site_search=web.site_search,
            creator_site=registry.website(handle),
            site_search_min_score=web.site_search_min_score,
        )
        if result.website and result.website_source:  # the first Video that links a website teaches it
            registry.learn(handle, result.website, result.website_source, video_key)
        path = self._web_path(video_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=1), encoding="utf-8")
        if result.usable and result.recipe:
            how = f" via {result.link_source}" if result.link_source in ("link_in_bio", "site_search") else ""
            self._detail[video_key] = f"{result.recipe.extraction_method} {result.final_url}{how}"
        else:
            self._detail[video_key] = f"no website recipe ({result.reason})"
            if result.reason in ("needs_browser", "robots", "error"):
                report.warnings.append(f"{video_key}: recipe page not read ({result.reason})")

    def _outline(self, video_key: str, report: RunReport, dry_run: bool) -> None:
        """One `strong` call per Video that shows signs of several recipes; each recipe becomes its own
        Recipe Part with its own slice of the Sources. Other Videos stay one part, with no call."""
        video = self.store.video(video_key)
        if video.platform == "web":
            return
        meta = VideoMeta.model_validate(video.metadata)
        web = self._web(video_key)
        names = [r.name for r in web.recipes] if web else []
        signals = detect_signals(meta, names)
        if not signals:
            return
        prompt = (
            f"Title: {meta.title}\nDuration: {meta.duration_s or 'unknown'} s\n"
            f"Signals: {', '.join(signals)}\n"
            + "".join(
                f"Chapter {c.start_s:g}-{c.end_s if c.end_s is not None else '?'} s: {c.title}\n"
                for c in meta.chapters
            )
            + (f"Recipes on the website page: {json.dumps(names, ensure_ascii=False)}\n" if names else "")
            + f"\n[SRC:desc]\n{meta.description}\n[/SRC]\n"
        )
        raw = self.a.llm.complete("outline", prompt, Outline.model_json_schema(), "strong")
        try:
            parts = validate_outline(
                Outline.model_validate(raw), meta.duration_s, self.settings.outline.overlap
            )
        except OutlineError as err:
            raise NeedsReview(f"outline: {err}") from err
        if len(parts) < 2:
            return
        slices: list[dict[str, Any] | None] = [asdict(s) for s in segment(parts, meta.description, names)]
        existing = self.store.video_parts(video_key)
        if [(p.outline or {}).get("title") for p in existing] == [s["title"] for s in slices if s]:
            return  # the same outline again: nothing to replace
        keys = self.store.replace_parts(video_key, slices)
        if keys is None:
            raise NeedsReview(f"outline now has {len(slices)} recipes but some earlier parts are uploaded")
        for key in keys:  # the Video's link was checked before the outline; its parts share it
            self.store.record("part", key, "linkcheck", "done")
        self._detail[video_key] = f"{len(slices)} recipes: " + ", ".join(s["title"] for s in slices if s)

    def _link_set(self) -> dict[str, str]:
        """The Existing Link Set: `key -> slug` for every recipe in Mealie that has an `orgURL`."""
        if self._links is None:
            self._links = build_link_set(self.a.mealie.list_recipe_summaries())
        return self._links

    def _link_key(self, video_key: str) -> str:
        """The key of this item in the Existing Link Set: the Video Key, or the normalized page URL
        for a Recipe Request (its `orgURL` is the page)."""
        video = self.store.video(video_key)
        if video.platform == "web":
            return normalize_website(video.canonical_url) or video_key
        return video_key

    def _request_for(self, item_key: str) -> RecipeRequest | None:
        return RecipeRequests(self.store).for_item(item_key)

    def _foreign_recipe(self, item_key: str) -> str | None:
        """Slug of a recipe in Mealie with this Video's link that the pipeline did not make, if any."""
        part = self.store.part(item_key)
        slug = self._link_set().get(self._link_key(part.video_key))
        mine = {
            p.slug for p in self.store.video_parts(part.video_key) if p.slug
        }  # sibling parts share the link
        return slug if slug and slug != part.slug and slug not in mine else None

    def _linkcheck(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        """Before any paid work: a Video whose link is already in Mealie is skipped (link = identity)."""
        slug = self._foreign_recipe(item_key)
        if slug is None:
            return
        if not self.upgrade_existing:
            raise AlreadyInMealie(slug)
        self._detail[item_key] = f"will upgrade {slug}"

    def _upgrade_existing(self, item_key: str, slug: str, payload: dict[str, Any]) -> None:
        """PATCH an older import in place: ingredients, steps, tags (added to its own) and extras
        (merged). Name, image, rating, comments and dates are not sent, so they stay."""
        mealie = self.a.mealie
        current = mealie.get_recipe(slug)
        have = {t["id"] for t in current.get("tags") or []}
        tags = list(current.get("tags") or []) + [t for t in payload["tags"] if t["id"] not in have]
        sent = {
            "recipeIngredient": payload["recipeIngredient"],
            "recipeInstructions": payload["recipeInstructions"],
            "tags": tags,
            "extras": {**(current.get("extras") or {}), **payload["extras"]},
        }
        mealie.patch_recipe(slug, sent)
        problems = read_back_problems(sent, mealie.get_recipe(slug))
        if problems:
            raise StageFailure("read-back differs from what was sent: " + "; ".join(problems))
        self.store.update_part(item_key, slug=slug)
        raise UpgradedExisting(slug)

    def _extract(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        self._run_extraction(item_key, "strong", [])

    def _run_extraction(self, item_key: str, tier: Tier, findings: list[str]) -> None:
        """One extraction call; on a retry the Gate's findings go into the prompt."""
        part = self.store.part(item_key)
        video = self.store.video(part.video_key)
        meta = VideoMeta.model_validate(video.metadata)
        web = self._part_web(part)
        sources = self._sources(item_key)
        if not sources["desc"].strip() and web is None:
            raise StageFailure("the video has no description or website recipe to extract from")
        tags = sorted(t.name for t in self.catalog.tags)
        prompt = (
            f"Title: {meta.title}\nUploader: {meta.uploader}\nURL: {video.canonical_url}\n\n"
            f"Allowed tag names: {json.dumps(tags, ensure_ascii=False)}\n\n"
        )
        request = self._request_for(item_key) if video.platform == "web" else None
        if request is not None:
            hint = f" Notes from the sheet: {request.notes}" if request.notes else ""
            prompt += (
                f"Requested recipe name: {request.name}.{hint} "
                "(Context only. Never quote it as Evidence.)\n\n"
            )
        if part.outline is not None:
            where = (
                f" (from {part.outline['start_s']:g} s)" if part.outline.get("start_s") is not None else ""
            )
            prompt += (
                f"This video holds {part.part_count} recipes. Extract ONLY recipe {part.part_index} of "
                f'{part.part_count}: "{part.outline["title"]}"{where}. Ignore the other recipes; text '
                "marked as shared applies to all of them.\n\n"
            )
        if web is not None:
            rule = WEB_STRUCTURED_RULE if web.structured else WEB_TEXT_RULE
            prompt += f"[SRC:web]\n{web_text(web)}\n[/SRC]\n\n{rule}\n\n"
        if sources["desc"].strip():
            prompt += f"[SRC:desc]\n{sources['desc']}\n[/SRC]\n"
        if findings:
            prompt += (
                "\nYour previous extraction of this video failed verification. Fix these problems, "
                "using only what the sources say:\n" + "\n".join(f"- {f}" for f in findings) + "\n"
            )
        raw = self.a.llm.complete("extract", prompt, extraction_schema(tags), tier)
        recipe = ExtractedRecipe.model_validate(raw)
        if not recipe.is_recipe:
            raise StageFailure(
                f"the {'description and website page' if web else 'description'} does not contain a recipe"
            )
        if not recipe.ingredients or not recipe.instructions:
            raise StageFailure("the extraction has no ingredients or no steps")
        self.store.update_part(item_key, extracted=recipe.model_dump())

    def _parse(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        part = self.store.part(item_key)
        recipe = ExtractedRecipe.model_validate(part.extracted)
        parsed = self._parse_ingredients(recipe, item_key, create=True)
        self.store.update_part(item_key, parsed=[p.model_dump() for p in parsed])
        report.warnings += self._confirm_group(item_key)

    def _tag(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        part = self.store.part(item_key)
        tags = self._choose_tags(part, report)
        if not tags:  # one retry at the strongest tier, then the `To Review` fallback
            self._run_extraction(
                item_key,
                "strongest",
                ["none of your tag choices is an existing tag: choose from the allowed tag names"],
            )
            self._parse(item_key, report, False)
            tags = self._choose_tags(self.store.part(item_key), report)
        self.store.update_part(item_key, tags=tags or [self._review_tag()])

    def _part_web(self, part: RecipePart) -> SourceRecipe | None:
        """The website recipe this part is written from: the chosen one, or the one its outline matched."""
        web = self._web(part.video_key)
        if web is None:
            return None
        if part.outline is None:
            return web.recipe
        index = part.outline.get("web_index")
        return web.recipes[index] if index is not None and index < len(web.recipes) else None

    def _sources(self, item_key: str) -> dict[str, str]:
        """The Sources the Evidence may cite: the website recipe (`web`) and the description (`desc`).
        For a part of a multi-recipe Video that is only its own slice, plus the shared text."""
        part = self.store.part(item_key)
        meta = VideoMeta.model_validate(self.store.video(part.video_key).metadata)
        desc = meta.description
        if part.outline is not None:
            own, shared = part.outline["own"], part.outline["shared"]
            desc = (
                f"[Shared by every recipe in this video]\n{shared}\n\n[This recipe]\n{own}" if own else shared
            )
        web = self._part_web(part)
        return {"web": web_text(web), "desc": desc} if web is not None else {"desc": desc}

    def _evaluate(self, item_key: str) -> Evaluation:
        part = self.store.part(item_key)
        return evaluate(
            ExtractedRecipe.model_validate(part.extracted),
            [ParsedIngredient.model_validate(p) for p in part.parsed or []],
            part.tags or [],
            self._sources(item_key),
            [f.name for f in self.catalog.foods],
            self.settings.verify,
        )

    def _gate_config(self, video_key: str) -> VerifySettings:
        """The Gate's thresholds; a page found by site search must clear a higher upload bar."""
        cfg = self.settings.verify
        web = self._web(video_key)
        if web is not None and web.link_source == "site_search":
            return cfg.model_copy(update={"upload_at": max(cfg.upload_at, cfg.site_search_upload_at)})
        return cfg

    def _verify(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        cfg = self._gate_config(self.store.part(item_key).video_key)
        attempts = 1
        evaluation = self._evaluate(item_key)
        judge = self._judge(item_key, evaluation)
        if decide(judge.score, evaluation.hard_failures, cfg) == "fail":
            # One retry per run: the strongest tier, with the findings in the prompt.
            findings = evaluation.findings() + [f"judge: {p}" for p in judge.descriptions]
            self._run_extraction(item_key, "strongest", findings)
            self._parse(item_key, report, False)
            self._tag(item_key, report, False)
            attempts = 2
            evaluation = self._evaluate(item_key)
            judge = self._judge(item_key, evaluation)
        outcome = decide(judge.score, evaluation.hard_failures, cfg)

        part = self.store.part(item_key)
        tags = list(part.tags or [])
        if outcome == "upload_review":
            review = self._review_tag()
            if review["id"] not in {t["id"] for t in tags}:
                tags.append(review)
        if outcome != "fail":  # keep the recipe without its ungrounded ingredients
            self.store.update_part(
                item_key,
                extracted=evaluation.recipe.model_dump(),
                parsed=[p.model_dump() for p in evaluation.parsed],
                tags=tags,
            )
        verify = {
            "score": judge.score,
            "outcome": "review" if outcome == "fail" else outcome,
            "failed_checks": evaluation.failed_checks + (["S7"] if judge.descriptions else []),
            "checks": [c.as_dict() for c in evaluation.checks],
            "dropped_ingredients": evaluation.dropped,
            "judge_problems": judge.problems,
            "extraction_attempts": attempts,
        }
        self.store.update_part(item_key, verify=verify)
        if outcome == "fail":
            path = write_review_file(
                self.workspace,
                item_key=item_key,
                video=self.store.video(part.video_key),
                sources=self._sources(item_key),
                recipe=evaluation.recipe,
                verify=verify,
            )
            raise NeedsReview(f"score {judge.score}, failed {', '.join(verify['failed_checks'])}; see {path}")

    def _judge(self, item_key: str, evaluation: Evaluation) -> "JudgeResult":
        """S7: an independent LLM review, only when the deterministic score is below the skip level."""
        cfg = self.settings.verify
        score = evaluation.score
        if evaluation.hard_failures or score >= cfg.judge_skip_at:
            return JudgeResult(score, [], [])
        sources = "\n".join(f"[SRC:{k}]\n{v}\n[/SRC]" for k, v in self._sources(item_key).items())
        recipe = json.dumps(evaluation.recipe.model_dump(), ensure_ascii=False, indent=1)
        prompt = f"Final recipe:\n{recipe}\n\nSources:\n{sources}\n"
        try:
            raw = self.a.llm.complete("judge", prompt, Judge.model_json_schema(), "strong")
            problems = Judge.model_validate(raw).problems
        except UsageLimited:
            raise
        except (LLMError, ValidationError):
            return JudgeResult(score, [], [])  # an unavailable judge never blocks or fails an item
        severities = [p.severity for p in problems]
        return JudgeResult(
            apply_judge(score, severities, cfg.judge_penalties),
            [p.model_dump() for p in problems],
            [f"{p.severity} {p.field}: {p.description}" for p in problems],
        )

    def _review_tag(self, *, create: bool = True) -> dict[str, Any]:
        name = self.settings.verify.review_tag
        existing = next((t for t in self.catalog.tags if t.name.casefold() == name.casefold()), None)
        if existing is None and not create:  # a dry run creates nothing
            return {"id": "", "name": name, "slug": ""}
        if existing is None:
            existing = self.a.mealie.create_tag(name)  # created once, then found in the catalog
            self.catalog.tags.append(existing)
        return {"id": existing.id, "name": existing.name, "slug": existing.slug}

    def _upload(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        part = self.store.part(item_key)
        video = self.store.video(part.video_key)
        recipe = ExtractedRecipe.model_validate(part.extracted)
        parsed = [ParsedIngredient.model_validate(p) for p in part.parsed or []]
        payload = self._payload(recipe, parsed, part.tags or [], item_key, part.video_key, video.platform)
        mealie = self.a.mealie

        # Re-check against a fresh listing: it may have been imported since extraction.
        foreign = self._foreign_recipe(item_key)
        if foreign is not None:
            if not self.upgrade_existing:
                raise AlreadyInMealie(foreign)
            self._upgrade_existing(item_key, foreign, payload)

        existing = mealie.find_recipe(item_key=item_key, org_url=payload.get("orgURL"))
        if existing is not None and existing.get("recipeIngredient") and self.mode != "update":
            slug = str(existing["slug"])  # already uploaded earlier: record it, write nothing
            self.store.update_part(item_key, slug=slug, mealie_url=mealie.recipe_url(slug))
            report.uploaded.append(f"{item_key}: {mealie.recipe_url(slug)} (already in Mealie)")
            return
        slug = (existing or {}).get("slug") or part.slug or mealie.create_recipe(recipe.name)
        self.store.update_part(item_key, slug=slug)  # remembered before the PATCH so a crash can resume
        mealie.patch_recipe(slug, payload)

        meta = VideoMeta.model_validate(video.metadata)
        web = self._part_web(part)
        website_image = web.image if web else None
        urls = candidate_urls(video.platform, video.video_id, meta.thumbnail, website_image)
        scratch = self.workspace / "work" / "images"
        outcome = None
        start = (part.outline or {}).get("start_s")
        if website_image is None and start is not None:  # no website image: a frame from the part's start
            frame = self.a.videos.frame(video.canonical_url, start, scratch / f"{slug}-frame.jpg")
            if frame is not None:
                try:
                    mealie.upload_image(slug, frame)
                    outcome = "file"
                except MealieError:
                    pass
        if outcome is None:
            outcome = attach_image(mealie, slug, urls, self.a.images, scratch)
        warnings = ["image_missing"] if outcome == "missing" else []

        stored = mealie.get_recipe(slug)
        problems = read_back_problems(payload, stored)
        if problems:
            raise StageFailure("read-back differs from what was sent: " + "; ".join(problems))
        link = mealie.recipe_url(slug)
        self.store.update_part(item_key, mealie_url=link, warnings=warnings)
        self._detail[item_key] = "image_missing" if warnings else ""
        self._link_set()[self._link_key(part.video_key)] = (
            slug  # known at once, so a later item cannot repeat it
        )
        report.uploaded.append(f"{item_key}: {link}")
        report.warnings += [f"{item_key}: {w}" for w in warnings]
        self._uploaded_videos.add(part.video_key)

    # -- dry run --------------------------------------------------------------------------

    def _preview(self, report: RunReport, limit: int | None) -> None:
        """Parse, tag and build the payload for parts with a finished extraction; no writes anywhere."""
        out = self.workspace / "work" / "payloads"
        for item_key in self.store.next_batch("part", "upload", "extract", limit):
            try:
                part = self.store.part(item_key)
                video = self.store.video(part.video_key)
                recipe = ExtractedRecipe.model_validate(part.extracted)
                parsed = self._parse_ingredients(recipe, item_key, create=False)
                tags = self._choose_tags(part, None, parsed=parsed) or [self._review_tag(create=False)]
                # The deterministic Gate only: no judge call, no retry, no tag created.
                evaluation = evaluate(
                    recipe,
                    parsed,
                    tags,
                    self._sources(item_key),
                    [f.name for f in self.catalog.foods],
                    self.settings.verify,
                )
                # Hard checks other than H4 (Foods are not created in a dry run, so ids are missing),
                # unless a line is `unparsed`: that one has no Food whatever is created.
                unparsed = any(p.parse_status == "unparsed" for p in evaluation.parsed)
                hard = [c for c in evaluation.hard_failures if c != "H4" or unparsed]
                if hard or evaluation.score < self.settings.verify.review_at:
                    problems = ", ".join(evaluation.failed_checks)
                    report.review.append(
                        f"{item_key}: would go to the Review Queue (score {evaluation.score}, {problems})"
                    )
                    continue
                recipe, parsed = evaluation.recipe, evaluation.parsed
                payload = self._payload(recipe, parsed, tags, item_key, part.video_key, video.platform)
            except (StageFailure, ValidationError, MealieError) as err:
                report.failed.append(f"{item_key} [dry-run]: {err}")
                continue
            out.mkdir(parents=True, exist_ok=True)
            path = out / (re.sub(r"[^A-Za-z0-9_.-]+", "_", item_key) + ".json")
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            report.dry_run_files.append(path)

    # -- helpers --------------------------------------------------------------------------

    def _payload(
        self,
        recipe: ExtractedRecipe,
        parsed: list[ParsedIngredient],
        tags: list[dict[str, Any]],
        item_key: str,
        video_key: str,
        platform: str,
    ) -> dict[str, Any]:
        canonical = self.store.video(video_key).canonical_url
        part = self.store.part(item_key)
        org_url = canonical
        notes: list[str] = []
        if part.outline is not None:
            start = part.outline.get("start_s")
            if platform == "youtube" and start is not None:
                org_url = f"{canonical}&t={int(start)}s"  # unique per part, and opens at the right place
            others = [self._part_name(p) for p in self.store.video_parts(video_key) if p.item_key != item_key]
            notes = [f"Also in this video: {', '.join(others)}"]
        payload = build_payload(
            recipe,
            parsed,
            tags,
            org_url=org_url,
            item_key=item_key,
            video_key=video_key,
            platform=platform,
            part=part.part_index,
            of=part.part_count,
        )
        payload["notes"] = [*payload["notes"], *({"title": SIBLING_TITLE, "text": n} for n in notes)]
        urls = also_on(self.store, video_key)
        if urls:
            payload["extras"]["also_on"] = urls
            payload["notes"] = [
                *payload["notes"],
                {"title": "Also posted on", "text": "\n".join(urls)},
            ]
        request = self._request_for(item_key) if platform == "web" else None
        if request is not None:
            payload["extras"] = {
                "item_key": item_key,
                "requested_name": request.name,
                "request_row": request.position or request.row_number,
                "source": "web-search" if not request.url else "sheet-url",
                "score": (self.store.part(item_key).verify or {}).get("score", request.score),
                "pipeline_version": payload["extras"]["pipeline_version"],
            }
            if recipe.name.strip().casefold() != request.name.strip().casefold():
                payload["notes"] = [
                    *payload["notes"],
                    {"title": "Requested as", "text": f'Requested as "{request.name}" in the recipe list.'},
                ]
        return payload

    def _part_name(self, part: RecipePart) -> str:
        """A part's recipe name once extracted, else the title the outline gave it."""
        if part.extracted and part.extracted.get("name"):
            return str(part.extracted["name"])
        return str((part.outline or {}).get("title") or part.item_key)

    def _link_siblings(self, report: RunReport) -> None:
        """Once every part of a multi-recipe Video is in Mealie, its sibling note gets links to the
        others (slugs were not known when each part was uploaded): one PATCH of the notes per part."""
        mealie = self.a.mealie
        for video_key in sorted(self._uploaded_videos):
            parts = self.store.video_parts(video_key)
            if len(parts) < 2 or not all(p.slug for p in parts):
                continue
            for part in parts:
                assert part.slug is not None
                links = [
                    f"[{self._part_name(p)}]({mealie.recipe_url(p.slug)})"
                    for p in parts
                    if p.item_key != part.item_key and p.slug
                ]
                current = mealie.get_recipe(part.slug)
                kept = [n for n in current.get("notes") or [] if n.get("title") != SIBLING_TITLE]
                note = {"title": SIBLING_TITLE, "text": "Also in this video: " + ", ".join(links)}
                if note not in (current.get("notes") or []):
                    mealie.patch_recipe(part.slug, {"notes": [*kept, note]})
        self._uploaded_videos.clear()

    def _choose_tags(
        self,
        part: RecipePart,
        report: RunReport | None,
        *,
        parsed: list[ParsedIngredient] | None = None,
    ) -> list[dict[str, Any]]:
        """The recipe's 1-6 existing tags: Rule Tags first, then the LLM's by rank, minus any a Food
        contradicts. Empty when none survive. `report=None` (a dry run) writes nothing."""
        recipe = ExtractedRecipe.model_validate(part.extracted)
        if parsed is None:
            parsed = [ParsedIngredient.model_validate(p) for p in part.parsed or []]
        by_key = {tag_key(t.name): t for t in self.catalog.tags}
        names = [t.name for t in self.catalog.tags]
        llm: list[str] = []
        for choice in recipe.tag_choices:
            existing = match_existing(choice.tag, names)
            if existing is None:
                if report is not None:
                    self._suggest_tag(choice.tag, part.video_key)
            else:
                llm.append(existing)
        facts = RecipeFacts(
            recipe.name,
            [p.food_name for p in parsed],
            recipe.total_minutes or ((recipe.prep_minutes or 0) + (recipe.cook_minutes or 0)) or None,
            recipe.language,
        )
        # Rule Tags (config rules, then Protein Tags) only name tags that exist in Mealie; `mp doctor`
        # reports the rest, and `mp tags protein --apply` is what creates Protein Tags.
        wanted = (rule_tags(facts, self.tag_rules) if self.tag_rules else []) + self._protein_tags(recipe)
        rules = [e for name in wanted if (e := match_existing(name, names)) is not None]
        chosen = choose(
            rules, llm, max_tags=len(rules) + len(llm)
        )  # capped below, once contradictions free slots
        if self.tag_rules:
            for tag, food in contradictions(chosen, facts, self.tag_rules).items():
                chosen.remove(tag)
                if report is not None:
                    report.warnings.append(f"{part.item_key}: removed tag {tag!r}: the recipe has {food}")
        return [
            {"id": by_key[tag_key(t)].id, "name": by_key[tag_key(t)].name, "slug": by_key[tag_key(t)].slug}
            for t in chosen[:MAX_TAGS]
        ]

    def _suggest_tag(self, name: str, video_key: str) -> None:
        """A tag the LLM chose that Mealie does not have goes to `reports/suggested_tags.csv`, once."""
        path = self.workspace / "reports" / "suggested_tags.csv"
        if path.exists():
            with path.open(encoding="utf-8-sig", newline="") as handle:
                if any(tag_key(row["name"]) == tag_key(name) for row in csv.DictReader(handle)):
                    return
        self._log_created("suggested_tags.csv", name, video_key)

    def _protein_tags(self, recipe: ExtractedRecipe) -> list[str]:
        if self.proteins is None:
            return []
        lines = [f"{i.line} | {i.original_line} | {i.food_original}" for i in recipe.ingredients]
        text = RecipeText(recipe.name, lines, [c.tag for c in recipe.tag_choices])
        return list(detect(text, self.proteins))

    def _parse_ingredients(
        self, recipe: ExtractedRecipe, item_key: str, *, create: bool
    ) -> list[ParsedIngredient]:
        video_key = self.store.part(item_key).video_key
        result = []
        # Ingredients the Gate will drop as ungrounded must not leave junk Foods behind in Mealie.
        ungrounded = set(
            grounding.ungrounded_ingredients(
                recipe.ingredients, self._sources(item_key), self.settings.verify.grounding_threshold
            )
        )
        cfg = self.settings.parse
        unit_words = self.units.spellings() | {u.name.lower() for u in self.catalog.units}
        for index, ingredient in enumerate(recipe.ingredients):
            line = reconcile(
                ingredient.line,
                self.a.engine.parse(ingredient.line),
                ingredient.llm_parse,
                self.units.canonical,
                nlp_confidence=cfg.nlp_preferred_confidence,
                food_agreement=cfg.food_agreement,
            )
            original = ingredient.original_line or ingredient.line
            if line.status == "unparsed":  # kept as a note; the Gate sends the recipe to review (H4)
                result.append(
                    ParsedIngredient(
                        original_text=original,
                        section=ingredient.section,
                        quantity_stated=ingredient.quantity_stated,
                        food_name="",
                        note=line.note,
                        parse_status="unparsed",
                    )
                )
                continue
            unit_text = line.unit if ingredient.quantity_stated else ""
            unit_match = self.units.match(unit_text, self.catalog.units)
            food_match = self.foods.match(line.food, self.catalog.foods, ingredient.food_original)

            unit: Unit | None = unit_match.unit
            create_here = create and index not in ungrounded
            if unit_match.kind == "new" and create_here:
                unit = self._create_unit(unit_match.new_name, video_key)
            food: Food | None = food_match.food
            if food_match.kind == "new" and create_here:
                food = self._create_food(food_match.new_name, video_key)
            if food is not None and food_match.new_alias and create_here:
                self._add_food_alias(food, food_match.new_alias, video_key)

            if ingredient.quantity_stated:
                quantity, note = line.quantity or 0, line.note
            else:
                quantity, note = 0, line.note or TO_TASTE
            unit_name = unit.name if unit else (unit_match.new_name or None)
            food_name = food.name if food else food_match.new_name
            result.append(
                ParsedIngredient(
                    original_text=original,
                    section=ingredient.section,
                    quantity=quantity,
                    quantity_stated=ingredient.quantity_stated,
                    unit_id=unit.id if unit else None,
                    unit_name=unit_name,
                    food_id=food.id if food else None,
                    food_name=food_name,
                    food_original=ingredient.food_original,
                    note=note,
                    food_match=food_match.kind,
                    unit_match=unit_match.kind,
                    parse_status=line.status,
                    suspicious=check_line(
                        quantity, self.units.canonical(unit_name or ""), food_name, cfg, unit_words
                    ),
                    food_aliases=[a for a in (food.plural_name, *food.aliases) if a] if food else [],
                )
            )
        return result

    def _create_food(self, name: str, video_key: str) -> Food:
        food = self.a.mealie.create_food(name)
        self.catalog.foods.append(food)
        self._log_created("created_foods.csv", name, video_key)
        return food

    def _add_food_alias(self, food: Food, alias: str, video_key: str) -> None:
        """The source's own word for a Food (German "Zwiebel" for onion): later recipes link through it."""
        updated = self.a.mealie.add_food_alias(food.id, alias)
        food.aliases[:] = updated.aliases  # the Catalog's Food stays in step with Mealie
        self._log_created("created_aliases.csv", f"{alias} -> {food.name}", video_key)

    def _create_unit(self, name: str, video_key: str) -> Unit:
        unit = self.a.mealie.create_unit(name)
        self.catalog.units.append(unit)
        self._log_created("created_units.csv", name, video_key)
        return unit

    def _log_created(self, filename: str, name: str, video_key: str) -> None:
        """Appends to `reports/<filename>` with the Video the name first came from."""
        path = self.workspace / "reports" / filename
        path.parent.mkdir(parents=True, exist_ok=True)
        new_file = not path.exists()
        with path.open("a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as handle:
            writer = csv.writer(handle)
            if new_file:
                writer.writerow(["name", "first_video_key", "created_at"])
            writer.writerow([name, video_key, self.now().isoformat(timespec="seconds")])


def also_on(store: StateStore, video_key: str) -> list[str]:
    """URLs of the Videos `dedupe` folded into this one, in Video Key order."""
    marker = f"{ALSO_ON}{video_key}"
    folded = [
        r.entity_key
        for r in store.stage_records()
        if r.stage == "dedupe" and r.status in ("skipped", "done") and r.last_error == marker
    ]
    return [store.video(k).canonical_url for k in sorted(folded)]


def by_hand(label: str) -> Verdict:
    return Verdict(label, 1.0, ["set by hand in classification.csv"], source="override")


def describe_error(err: Exception) -> str:
    """Expected failures show their message; unexpected ones also name their type."""
    expected = (LLMError, MealieError, VideoSourceError, StageFailure, ValidationError)
    return str(err) if isinstance(err, expected) else f"unexpected {type(err).__name__}: {err}"


@dataclass
class JudgeResult:
    score: float
    problems: list[dict[str, Any]]
    descriptions: list[str]


class AlreadyInMealie(Exception):
    """The Video's link is already on a recipe in Mealie: skip it, write nothing."""

    status: Status = "already_in_mealie"

    def __init__(self, slug: str):
        super().__init__(f"already in Mealie as {slug}")
        self.slug = slug


class UpgradedExisting(AlreadyInMealie):
    """An existing recipe was upgraded in place (`--upgrade-existing`)."""

    status: Status = "upgraded_existing"


class NeedsReview(Exception):
    """The Gate held the item back: it goes to the Review Queue and is not uploaded."""


class StageFailure(Exception):
    """An expected, explainable failure of one entity at one stage."""


def read_back_problems(sent: dict[str, Any], stored: dict[str, Any]) -> list[str]:
    """What differs between the PATCH body and the recipe read back from Mealie (empty = identical)."""
    problems = []
    sent_ingredients, got_ingredients = sent["recipeIngredient"], stored.get("recipeIngredient") or []
    if len(sent_ingredients) != len(got_ingredients):
        problems.append(f"ingredient count {len(got_ingredients)}, expected {len(sent_ingredients)}")
    else:
        for index, (want, got) in enumerate(zip(sent_ingredients, got_ingredients, strict=True), start=1):
            want_id = (want.get("food") or {}).get("id")
            got_id = (got.get("food") or {}).get("id")
            if want_id != got_id:
                problems.append(f"ingredient {index} food id {got_id}, expected {want_id}")
    want_tags = {t["id"] for t in sent["tags"]}
    got_tags = {t["id"] for t in stored.get("tags") or []}
    if want_tags != got_tags:
        problems.append(f"tags {sorted(got_tags)}, expected {sorted(want_tags)}")
    if len(sent["recipeInstructions"]) != len(stored.get("recipeInstructions") or []):
        problems.append("step count differs")
    return problems
