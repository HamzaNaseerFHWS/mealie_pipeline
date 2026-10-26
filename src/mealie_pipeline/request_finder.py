"""The `find` stage for Recipe Requests (ticket 27): name -> search -> fetch -> pick the right page.

A request ends as `found` (its chosen URL is stored for ticket 28), `not_found`, or `needs_choice`
(the top three go to `reports/request_choices.csv` and `review/request-<cell>.md`). The user's choice
always wins over the scorer and is applied at the start of the next run.
"""

import csv
import re
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from mealie_pipeline import find
from mealie_pipeline.adapters.search import SearchError, SearchHit, WebSearch
from mealie_pipeline.adapters.web import WebFetcher
from mealie_pipeline.find import Candidate, SitePolicy
from mealie_pipeline.recipe_extraction import extract_recipes
from mealie_pipeline.recipe_requests import RecipeRequest, RecipeRequests
from mealie_pipeline.settings import FindSettings
from mealie_pipeline.url_normalizer import normalize_website

CHOICE_COLUMNS = ["request_id", "position", "name", "category"] + [
    f"{n}_{field}" for n in (1, 2, 3) for field in ("title", "url", "score", "ingredients")
]
CHOICE_COLUMNS.append("choice")


class SearchOutage(Exception):
    """Every search source failed: the requests stay pending instead of being marked not_found."""


def _outage_message(err: Exception) -> str:
    return (
        f"Every search source failed ({err}). The remaining requests stay pending: "
        "check your connection and run again later."
    )


@dataclass
class FindReport:
    found: list[str] = field(default_factory=list)
    not_found: list[str] = field(default_factory=list)
    needs_choice: list[str] = field(default_factory=list)
    choices_applied: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    searched: int = 0
    fallback_used: int = 0
    stopped: str | None = None

    def absorb(self, other: "FindReport") -> None:
        self.found += other.found
        self.not_found += other.not_found
        self.needs_choice += other.needs_choice
        self.warnings += other.warnings
        self.searched += other.searched
        self.fallback_used += other.fallback_used


class RequestFinder:
    def __init__(
        self,
        workspace: Path,
        cfg: FindSettings,
        requests: RecipeRequests,
        search: WebSearch,
        fallback: WebSearch | None,
        fetcher: WebFetcher,
        selectors: dict[str, dict[str, str]],
        policy: SitePolicy,
    ):
        self.workspace = workspace
        self.cfg = cfg
        self.requests = requests
        self.search = search
        self.fallback = fallback if cfg.use_claude_fallback else None
        self.fetcher = fetcher
        self.selectors = selectors
        self.policy = policy

    # -- run ------------------------------------------------------------------------------

    def run(
        self,
        *,
        limit: int | None = None,
        should_stop: Callable[[], bool] = lambda: False,
        workers: int = 1,
    ) -> FindReport:
        report = FindReport()
        self._apply_choices(report)
        todo = self.requests.with_status("pending")
        todo = todo[:limit] if limit is not None else todo
        if workers > 1 and len(todo) > 1:
            self._run_parallel(todo, report, should_stop, workers)
        else:
            for request in todo:
                if should_stop():
                    report.stopped = "Interrupted after the current request. Run again to continue."
                    break
                try:
                    self._find_one(request, report)
                except SearchOutage as err:
                    report.stopped = _outage_message(err)
                    break
        self._write_choices()
        return report

    def _run_parallel(
        self,
        todo: list[RecipeRequest],
        report: FindReport,
        should_stop: Callable[[], bool],
        workers: int,
    ) -> None:
        """Several requests at once. The search sources and each domain still keep their delays (they
        are shared), and the results are merged in request order, whatever order the workers finish."""
        halt = threading.Event()
        interrupted = threading.Event()
        results: dict[int, FindReport] = {}
        outages: list[SearchOutage] = []
        lock = threading.Lock()

        def work(request: RecipeRequest) -> None:
            if halt.is_set():
                return
            if should_stop():
                interrupted.set()
                return
            sub = FindReport()
            try:
                self._find_one(request, sub)
            except SearchOutage as err:
                with lock:
                    outages.append(err)
                halt.set()
                return
            with lock:
                results[request.id] = sub

        pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mp-find")
        try:
            for future in [pool.submit(work, request) for request in todo]:
                future.result()
        except BaseException:  # Ctrl+C or a crash: start nothing else, let the running requests finish
            halt.set()
            pool.shutdown(wait=True, cancel_futures=True)
            raise
        pool.shutdown()
        for request in todo:
            if request.id in results:
                report.absorb(results[request.id])
        if outages:
            report.stopped = _outage_message(outages[0])
        elif interrupted.is_set():
            report.stopped = "Interrupted after the current request. Run again to continue."

    # -- one request ----------------------------------------------------------------------

    def _find_one(self, request: RecipeRequest, report: FindReport) -> None:
        label = f"{request.position or request.row_number} {request.name}"
        if request.url:  # given in the sheet: no search, only check that it is a real recipe page
            report_line = self._check_given_url(request)
            (report.found if report_line is None else report.not_found).append(report_line or label)
            return
        language = request.language or find.guess_language(request.name)
        hint = " ".join(x for x in (request.cuisine, request.notes) if x)
        query = find.build_query(request.name, language, hint, self.cfg)
        tried: set[str] = set()
        notes: list[str] = []
        primary_error: SearchError | None = None
        try:
            report.searched += 1
            hits = self.search.search(query, language, self.cfg.search_results)
        except SearchError as err:
            primary_error, hits = err, []
        candidates = self._evaluate(request, language, hits, tried, notes)
        if not candidates and self.fallback is not None:
            report.fallback_used += 1
            try:
                more = self.fallback.search(query, language, self.cfg.search_results)
            except SearchError as err:
                if primary_error is not None:
                    raise SearchOutage(f"{primary_error}; {err}") from err
                notes.append(f"fallback search unavailable: {err}")
                more = []
            candidates = self._evaluate(request, language, more, tried, notes)
        elif not candidates and primary_error is not None:
            raise SearchOutage(str(primary_error))

        decision, top = find.decide(candidates, self.cfg)
        top_dicts = [c.as_dict() for c in top]
        if decision == "found":
            best = top[0]
            self.requests.set_result(
                request.id, "found", chosen_url=best.url, candidates=top_dicts, score=best.score,
                reason=f"{best.recipe_name} (score {best.score:.2f})",
            )  # fmt: skip
            report.found.append(f"{label} -> {best.url}")
        elif decision == "needs_choice":
            self.requests.set_result(
                request.id, "needs_choice", candidates=top_dicts, score=top[0].score,
                reason=f"{len(top)} similar pages, best score {top[0].score:.2f}: choose one",
            )  # fmt: skip
            report.needs_choice.append(label)
        else:
            reason = "; ".join(notes[:4]) or "the search found no pages"
            self.requests.set_result(request.id, "not_found", reason=reason)
            report.not_found.append(f"{label}: {reason}")

    def _check_given_url(self, request: RecipeRequest) -> str | None:
        """None when the sheet's URL is a real single-recipe page (request becomes found)."""
        assert request.url
        label = f"{request.position or request.row_number} {request.name}"
        page = self.fetcher.fetch(request.url)
        recipe = (
            find.single_recipe(extract_recipes(page.html, page.final_url, self.selectors))
            if page.ok
            else None
        )
        if recipe is None:
            why = page.blocked or ("not a single recipe page" if page.ok else f"HTTP {page.status}")
            reason = f"the URL in the sheet is not usable: {why}"
            self.requests.set_result(request.id, "not_found", reason=reason)
            return f"{label}: {reason}"
        self.requests.set_result(
            request.id, "found", chosen_url=page.final_url, reason="URL given in the sheet"
        )
        return None

    def _evaluate(
        self,
        request: RecipeRequest,
        language: str,
        hits: list[SearchHit],
        tried: set[str],
        notes: list[str],
    ) -> list[Candidate]:
        found: list[Candidate] = []
        for hit in find.filter_hits(hits, self.policy, self.cfg.candidates, tried):
            key = normalize_website(hit.url)
            if key:
                tried.add(key)
            page = self.fetcher.fetch(hit.url)
            if page.blocked or not page.ok:
                notes.append(f"{hit.url}: {page.blocked or 'HTTP ' + str(page.status)}")
                continue
            recipe = find.single_recipe(extract_recipes(page.html, page.final_url, self.selectors))
            if recipe is None:
                notes.append(f"{hit.url}: not a single recipe page")
                continue
            candidate = find.score_candidate(
                request.name, language, page.final_url, recipe, page.html, self.cfg, hit.title
            )
            if candidate is None:
                notes.append(f"{hit.url}: recipe '{recipe.name}' is not what was asked for")
                continue
            found.append(candidate)
        return found

    # -- the user's choices ---------------------------------------------------------------

    def _choices_path(self) -> Path:
        return self.workspace / "reports" / "request_choices.csv"

    def _apply_choices(self, report: FindReport) -> None:
        path = self._choices_path()
        if not path.is_file():
            return
        with path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        for row in rows:
            choice = (row.get("choice") or "").strip()
            if not choice or not (row.get("request_id") or "").isdigit():
                continue
            request = next((r for r in self.requests.all() if r.id == int(row["request_id"])), None)
            if request is None or request.status != "needs_choice":
                continue
            label = f"{request.position or request.row_number} {request.name}"
            if choice.casefold() == "skip":
                self.requests.set_result(request.id, "not_found", candidates=request.candidates,
                                         reason="skipped by you")  # fmt: skip
                report.choices_applied.append(f"{label}: skipped")
            elif choice in ("1", "2", "3") and int(choice) <= len(request.candidates):
                picked = request.candidates[int(choice) - 1]
                self.requests.set_result(
                    request.id, "found", chosen_url=picked["url"], candidates=request.candidates,
                    score=picked.get("score"), reason=f"chosen by you (candidate {choice})",
                )  # fmt: skip
                report.choices_applied.append(f"{label}: candidate {choice} -> {picked['url']}")
            elif normalize_website(choice) and re.match(r"https?://", choice, re.IGNORECASE):
                self.requests.set_result(
                    request.id,
                    "found",
                    chosen_url=choice,
                    candidates=request.candidates,
                    reason="URL given by you",
                )
                report.choices_applied.append(f"{label}: {choice}")
            else:
                report.warnings.append(
                    f"{label}: choice {choice!r} not understood (write 1, 2, 3, a full URL, or skip)"
                )

    def _write_choices(self) -> None:
        """Rewrites `request_choices.csv` and the review files for every request still waiting."""
        waiting = self.requests.with_status("needs_choice")
        review_dir = self.workspace / "review"
        for stale in review_dir.glob("request-*.md") if review_dir.is_dir() else []:
            stale.unlink()
        path = self._choices_path()
        if not waiting:
            if path.is_file():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=CHOICE_COLUMNS)
            writer.writeheader()
            for request in waiting:
                row: dict[str, Any] = {
                    "request_id": request.id,
                    "position": request.position or "",
                    "name": request.name,
                    "category": request.category or "",
                    "choice": "",
                }
                for number, cand in enumerate(request.candidates[:3], start=1):
                    row[f"{number}_title"] = cand["title"]
                    row[f"{number}_url"] = cand["url"]
                    row[f"{number}_score"] = f"{cand['score']:.2f}"
                    row[f"{number}_ingredients"] = " | ".join(cand.get("ingredient_preview", []))
                writer.writerow(row)
                self._write_review(request)

    def _write_review(self, request: RecipeRequest) -> None:
        cell = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.position or str(request.row_number))
        lines = [
            f'# Which page is "{request.name}"?',
            "",
            f"- Cell: {request.position or request.row_number}   Category: {request.category or '-'}",
            "- Write `1`, `2`, `3`, a full URL, or `skip` in the `choice` column of "
            "`reports/request_choices.csv`, then run `mp run --stages find` again.",
            "",
        ]
        for number, cand in enumerate(request.candidates[:3], start=1):
            lines += [
                f"## {number}. {cand['title']}  (score {cand['score']:.2f})",
                "",
                cand["url"],
                "",
                f"Found through {cand['method']}. Name {cand['parts']['name']:.2f}, "
                f"structure {cand['parts']['structure']:.2f}, "
                f"completeness {cand['parts']['completeness']:.2f}, "
                f"language {cand['parts']['language']:.2f}.",
                "",
                "Ingredients (first ones):",
                *[f"- {i}" for i in cand.get("ingredient_preview", [])],
                "",
            ]
        path = self.workspace / "review" / f"request-{cell}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
