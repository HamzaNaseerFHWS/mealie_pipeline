"""The Stage Runner for the tracer-bullet path: metadata -> extract -> parse -> tag -> upload.

Each stage is a function over the State Store with an `Adapters` bundle. A failure in one entity is
recorded on its Stage Record and never stops the stage. Re-running changes nothing that is `done`.
"""

import csv
import json
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from mealie_pipeline import grounding
from mealie_pipeline.adapters import Adapters
from mealie_pipeline.adapters.llm import LLMError, Tier, UsageLimited
from mealie_pipeline.adapters.mealie import Catalog, Food, Tag, Unit
from mealie_pipeline.adapters.video_source import VideoSourceError
from mealie_pipeline.errors import MealieError
from mealie_pipeline.existing_links import build_link_set
from mealie_pipeline.find import single_recipe
from mealie_pipeline.images import attach_image, candidate_urls
from mealie_pipeline.matching import FoodMatcher, UnitNormalizer
from mealie_pipeline.models import ExtractedRecipe, Judge, ParsedIngredient, VideoMeta, extraction_schema
from mealie_pipeline.payload import build_payload
from mealie_pipeline.protein import ProteinRules, RecipeText, detect, tag_key
from mealie_pipeline.recipe_extraction import extract_recipes
from mealie_pipeline.recipe_extraction import format_for_prompt as web_text
from mealie_pipeline.recipe_requests import RecipeRequest, RecipeRequests
from mealie_pipeline.request_import import register_found, sync_outcomes
from mealie_pipeline.review import write_review_file
from mealie_pipeline.scoring import apply_judge, decide
from mealie_pipeline.scrape import WebResult, find_web_recipe
from mealie_pipeline.settings import Settings
from mealie_pipeline.store import EntityKind, StateStore, Status
from mealie_pipeline.url_normalizer import normalize_website
from mealie_pipeline.verify import Evaluation, evaluate

STAGES = ["metadata", "linkcheck", "scrape", "extract", "parse", "tag", "verify", "upload"]
# Stages that run once per Video; the rest run per Recipe Part.
VIDEO_STAGES = {"metadata", "scrape"}
# The stage that must be done first for the same entity. Recipe Parts exist only once their Video's
# metadata is done, so `linkcheck` has no prerequisite. `scrape` (per Video) waits for a Part's
# `linkcheck`, and `extract` waits for its Part's `linkcheck` and its Video's `scrape`.
PREREQUISITE: dict[str, str | None] = {
    "metadata": None,
    "linkcheck": None,
    "scrape": "metadata",
    "extract": "linkcheck",
    "parse": "extract",
    "tag": "parse",
    "verify": "tag",
    "upload": "verify",
}
MAX_TAGS = 6
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


@dataclass
class RunReport:
    done: dict[str, int] = field(default_factory=dict)
    failed: list[str] = field(default_factory=list)
    uploaded: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    already_in_mealie: list[str] = field(default_factory=list)
    upgraded_existing: list[str] = field(default_factory=list)
    dry_run_files: list[Path] = field(default_factory=list)
    stopped: str | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def count(self, stage: str) -> None:
        with self._lock:
            self.done[stage] = self.done.get(stage, 0) + 1

    def sort_lines(self) -> None:
        """Workers finish in any order; the report lists items in key order, as a single worker would."""
        lists = (self.failed, self.review, self.already_in_mealie, self.upgraded_existing, self.warnings)
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
        self.mode = "skip"
        self.upgrade_existing = False
        self._links: dict[str, str] | None = None
        units = workspace / "config" / "units.yaml"
        synonyms = yaml.safe_load(units.read_text(encoding="utf-8")) if units.is_file() else {}
        self.units = UnitNormalizer(synonyms or {})
        self.foods = FoodMatcher()
        selectors = workspace / "config" / "site_selectors.yaml"
        self.selectors: dict[str, dict[str, str]] = (
            yaml.safe_load(selectors.read_text(encoding="utf-8")) if selectors.is_file() else {}
        ) or {}
        proteins = workspace / "config" / "protein_tags.yaml"
        self.proteins = ProteinRules.load(proteins) if proteins.is_file() else None

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
            if stage == "scrape":  # only Videos that still have a Part to import (not already in Mealie)
                wanted_videos = {
                    p.video_key
                    for p in self.store.parts()
                    if self.store.stage_status("part", p.item_key, "linkcheck") == "done"
                }
                batch = [key for key in batch if key in wanted_videos]
            if stage == "extract":  # wait for the Video's recipe website (`scrape`)
                batch = [
                    key
                    for key in batch
                    if self.store.stage_status("video", self.store.part(key).video_key, "scrape") == "done"
                ]
            todo = batch[:limit] if limit is not None else batch
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
        if workers > 1:
            report.sort_lines()
        return report

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
        self.store.ensure_part(video_key, 1, 1)

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
        result = find_web_recipe(
            title=meta.title,
            description=meta.description,
            pinned_comment=comment,
            fetcher=self.a.web,
            selectors=self.selectors,
            max_pages=web.max_pages,
        )
        path = self._web_path(video_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(result.model_dump_json(indent=1), encoding="utf-8")
        if result.usable and result.recipe:
            self._detail[video_key] = f"{result.recipe.extraction_method} {result.final_url}"
        else:
            self._detail[video_key] = f"no website recipe ({result.reason})"
            if result.reason in ("needs_browser", "robots", "error"):
                report.warnings.append(f"{video_key}: recipe page not read ({result.reason})")

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
        return slug if slug and slug != part.slug else None

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
        web = self._web(part.video_key)
        if not meta.description.strip() and web is None:
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
        if web is not None and web.recipe is not None:
            rule = WEB_STRUCTURED_RULE if web.recipe.structured else WEB_TEXT_RULE
            prompt += f"[SRC:web]\n{web_text(web.recipe)}\n[/SRC]\n\n{rule}\n\n"
        if meta.description.strip():
            prompt += f"[SRC:desc]\n{meta.description}\n[/SRC]\n"
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
        parsed = self._parse_ingredients(recipe, part.video_key, create=True)
        self.store.update_part(item_key, parsed=[p.model_dump() for p in parsed])

    def _tag(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        part = self.store.part(item_key)
        tags = self._choose_tags(ExtractedRecipe.model_validate(part.extracted))
        self.store.update_part(item_key, tags=tags)

    def _sources(self, video_key: str) -> dict[str, str]:
        """The Sources the Evidence may cite: the website recipe (`web`) and the description (`desc`)."""
        meta = VideoMeta.model_validate(self.store.video(video_key).metadata)
        web = self._web(video_key)
        if web is not None and web.recipe is not None:
            return {"web": web_text(web.recipe), "desc": meta.description}
        return {"desc": meta.description}

    def _evaluate(self, item_key: str) -> Evaluation:
        part = self.store.part(item_key)
        return evaluate(
            ExtractedRecipe.model_validate(part.extracted),
            [ParsedIngredient.model_validate(p) for p in part.parsed or []],
            part.tags or [],
            self._sources(part.video_key),
            [f.name for f in self.catalog.foods],
            self.settings.verify,
        )

    def _verify(self, item_key: str, report: RunReport, dry_run: bool) -> None:
        cfg = self.settings.verify
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
            tags.append(self._review_tag())
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
                sources=self._sources(part.video_key),
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
        video_key = self.store.part(item_key).video_key
        sources = "\n".join(f"[SRC:{k}]\n{v}\n[/SRC]" for k, v in self._sources(video_key).items())
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

    def _review_tag(self) -> dict[str, Any]:
        name = self.settings.verify.review_tag
        existing = next((t for t in self.catalog.tags if t.name.casefold() == name.casefold()), None)
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
        web = self._web(part.video_key)
        website_image = web.recipe.image if web and web.recipe else None
        urls = candidate_urls(video.platform, video.video_id, meta.thumbnail, website_image)
        outcome = attach_image(mealie, slug, urls, self.a.images, self.workspace / "work" / "images")
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

    # -- dry run --------------------------------------------------------------------------

    def _preview(self, report: RunReport, limit: int | None) -> None:
        """Parse, tag and build the payload for parts with a finished extraction; no writes anywhere."""
        out = self.workspace / "work" / "payloads"
        for item_key in self.store.next_batch("part", "upload", "extract", limit):
            try:
                part = self.store.part(item_key)
                video = self.store.video(part.video_key)
                recipe = ExtractedRecipe.model_validate(part.extracted)
                parsed = self._parse_ingredients(recipe, part.video_key, create=False)
                tags = self._choose_tags(recipe)
                # The deterministic Gate only: no judge call, no retry, no tag created.
                evaluation = evaluate(
                    recipe,
                    parsed,
                    tags,
                    self._sources(part.video_key),
                    [f.name for f in self.catalog.foods],
                    self.settings.verify,
                )
                # Hard checks other than H4 (Foods are not created in a dry run, so ids are missing).
                hard = [c for c in evaluation.hard_failures if c != "H4"]
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
        payload = build_payload(
            recipe, parsed, tags, org_url=canonical, item_key=item_key, video_key=video_key, platform=platform
        )
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

    def _choose_tags(self, recipe: ExtractedRecipe) -> list[dict[str, Any]]:
        by_name = {tag_key(t.name): t for t in self.catalog.tags}
        chosen: list[Tag] = []
        for choice in recipe.tag_choices:
            tag = by_name.get(tag_key(choice.tag))
            if tag is not None and tag not in chosen:
                chosen.append(tag)
        # Protein Tags are Rule Tags: always kept, but only those that already exist in Mealie
        # (`mp tags protein --apply` is what creates them).
        proteins = [by_name[tag_key(name)] for name in self._protein_tags(recipe) if tag_key(name) in by_name]
        chosen = [t for t in chosen if t not in proteins][: MAX_TAGS - len(proteins)] + proteins
        if not chosen:
            raise StageFailure("no existing Mealie tag was chosen for this recipe")
        return [{"id": t.id, "name": t.name, "slug": t.slug} for t in chosen[:MAX_TAGS]]

    def _protein_tags(self, recipe: ExtractedRecipe) -> list[str]:
        if self.proteins is None:
            return []
        lines = [f"{i.line} | {i.original_line} | {i.food_original}" for i in recipe.ingredients]
        text = RecipeText(recipe.name, lines, [c.tag for c in recipe.tag_choices])
        return list(detect(text, self.proteins))

    def _parse_ingredients(
        self, recipe: ExtractedRecipe, video_key: str, *, create: bool
    ) -> list[ParsedIngredient]:
        result = []
        # Ingredients the Gate will drop as ungrounded must not leave junk Foods behind in Mealie.
        ungrounded = set(
            grounding.ungrounded_ingredients(
                recipe.ingredients, self._sources(video_key), self.settings.verify.grounding_threshold
            )
        )
        for index, ingredient in enumerate(recipe.ingredients):
            engine = self.a.engine.parse(ingredient.line)
            unit_text = engine.unit if ingredient.quantity_stated else ""
            unit_match = self.units.match(unit_text, self.catalog.units)
            food_match = self.foods.match(
                engine.food or ingredient.line, self.catalog.foods, ingredient.food_original
            )

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
                quantity, note = engine.quantity or 0, engine.note
            else:
                quantity, note = 0, engine.note or TO_TASTE
            result.append(
                ParsedIngredient(
                    original_text=ingredient.original_line or ingredient.line,
                    section=ingredient.section,
                    quantity=quantity,
                    quantity_stated=ingredient.quantity_stated,
                    unit_id=unit.id if unit else None,
                    unit_name=unit.name if unit else (unit_match.new_name or None),
                    food_id=food.id if food else None,
                    food_name=food.name if food else food_match.new_name,
                    food_original=ingredient.food_original,
                    note=note,
                    food_match=food_match.kind,
                    unit_match=unit_match.kind,
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
