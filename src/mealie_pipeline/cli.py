"""The `mp` command line."""

import signal
import sys
import threading
from pathlib import Path
from typing import Annotated

import typer
import yaml
from rich.console import Console
from rich.table import Table

from mealie_pipeline.adapters import Adapters, build_adapters
from mealie_pipeline.classify import (
    REVIEW_KEYS,
    ClassifyRules,
    Verdict,
    review_queue,
    set_override,
    video_meta,
    write_classification_csv,
)
from mealie_pipeline.collect import sync_lists
from mealie_pipeline.doctor import exit_code, render, run_doctor
from mealie_pipeline.find import SitePolicy
from mealie_pipeline.login import run_login
from mealie_pipeline.pipeline import STAGES, Pipeline, RunReport
from mealie_pipeline.recipe_requests import STATUSES as REQUEST_STATUSES
from mealie_pipeline.recipe_requests import RecipeRequests, write_requests_report
from mealie_pipeline.reports import STATUSES, write_report
from mealie_pipeline.request_finder import RequestFinder
from mealie_pipeline.request_sheet import SheetError, read_sheet
from mealie_pipeline.sessions import load_platforms
from mealie_pipeline.settings import Settings, load_settings
from mealie_pipeline.store import StateStore
from mealie_pipeline.url_normalizer import normalize, normalize_list

LOGIN_POLL_SECONDS = 2.0  # how often `mp login` looks for the session cookies
REQUEST_STAGES = ("find",)  # stages of Recipe Requests, run with `mp run --stages find`

app = typer.Typer(
    help="Turn saved cooking videos into parsed, tagged recipes in Mealie.", no_args_is_help=True
)


class AppContext:
    def __init__(self, workspace: Path, settings: Settings, adapters: Adapters):
        self.workspace = workspace
        self.settings = settings
        self.adapters = adapters


@app.callback()
def main(
    ctx: typer.Context,
    workspace: Annotated[
        Path,
        typer.Option(
            "--workspace", help="Folder holding config/, .env, the database and reports.", file_okay=False
        ),
    ] = Path("."),
) -> None:
    workspace = workspace.resolve()
    settings = load_settings(workspace)
    # Tests inject fake adapters through the click context object; otherwise build the real ones.
    adapters = ctx.obj if isinstance(ctx.obj, Adapters) else build_adapters(settings, workspace)
    ctx.obj = AppContext(workspace, settings, adapters)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check the setup: tools, logins and the connection to Mealie."""
    app_ctx: AppContext = ctx.obj
    checks = run_doctor(app_ctx.adapters, app_ctx.settings, app_ctx.workspace)
    typer.echo(render(checks))
    raise typer.Exit(exit_code(checks))


@app.command()
def login(
    ctx: typer.Context,
    platform: Annotated[str, typer.Argument(help="youtube, instagram or facebook.")],
) -> None:
    """Log in once in the pipeline's own Chrome window; the cookies are then exported for yt-dlp."""
    app_ctx: AppContext = ctx.obj
    profiles = load_platforms(app_ctx.workspace)
    profile = profiles.get(platform.lower())
    if profile is None:
        typer.echo(f"unknown platform {platform!r}: use one of {', '.join(profiles)}")
        raise typer.Exit(2)
    typer.echo(
        f"A Chrome window opens on the {profile.label} login page (the pipeline's own profile, not your "
        "everyday Chrome). Log in there, including 2FA. This continues by itself once you are logged in; "
        "press Enter here to stop waiting."
    )
    entered = threading.Event()

    def wait_for_enter() -> None:
        try:
            line = sys.stdin.readline()
        except (OSError, ValueError):
            return
        if line:  # "" is end of input (no terminal), not a key press
            entered.set()

    threading.Thread(target=wait_for_enter, daemon=True).start()
    result = run_login(
        profile,
        app_ctx.adapters.browser,
        app_ctx.workspace,
        pressed_enter=entered.is_set,
        sleep=entered.wait,  # a poll ends early when Enter is pressed
        poll_s=LOGIN_POLL_SECONDS,
    )
    shown = result.cookies_path.relative_to(app_ctx.workspace)
    if not result.logged_in:
        typer.echo(
            f"no {profile.label} session found. Run `mp login {profile.name}` again and finish logging in."
        )
        raise typer.Exit(1)
    typer.echo(f"logged in to {profile.name}; exported {result.cookie_count} cookies to {shown}")


def _open_pipeline(app_ctx: AppContext) -> Pipeline:
    store = StateStore(app_ctx.workspace / "pipeline.db")
    return Pipeline(app_ctx.workspace, app_ctx.settings, app_ctx.adapters, store)


@app.command()
def add(
    ctx: typer.Context,
    urls: Annotated[list[str] | None, typer.Argument(help="YouTube Video URLs.")] = None,
    file: Annotated[Path | None, typer.Option("--file", help="Text file with one URL per line.")] = None,
) -> None:
    """Register Videos in the State Store. Adding the same Video twice changes nothing."""
    app_ctx: AppContext = ctx.obj
    wanted = list(urls or [])
    if file is not None:
        wanted += [
            line.strip()
            for line in file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
    if not wanted:
        typer.echo("Nothing to add: give URLs or --file.")
        raise typer.Exit(2)
    pipeline = _open_pipeline(app_ctx)
    added = duplicates = unsupported = 0
    for url in wanted:
        normalized = normalize(url)
        if normalized is None or normalized.platform != "youtube":
            typer.echo(f"unsupported URL (only YouTube so far): {url}")
            unsupported += 1
        elif pipeline.add(normalized.canonical_url, url, normalized.platform, normalized.video_id):
            typer.echo(f"added {normalized.video_key}")
            added += 1
        else:
            typer.echo(f"already known {normalized.video_key}")
            duplicates += 1
    typer.echo(f"{added} added, {duplicates} already known, {unsupported} unsupported")


lists_app = typer.Typer(help="Saved Lists: the playlists whose Videos `mp sync` collects.")
app.add_typer(lists_app, name="lists")


@lists_app.callback(invoke_without_command=True)
def lists_show(ctx: typer.Context) -> None:
    """Without a subcommand: each Saved List with its item count and last sync time."""
    if ctx.invoked_subcommand is not None:
        return
    saved = _open_pipeline(ctx.obj).store.saved_lists()
    if not saved:
        typer.echo("No Saved Lists yet. Add one with `mp lists add <playlist url>`.")
        return
    table = Table(title="Saved Lists")
    for column in ("list", "items", "last synced", "url", "problem"):
        table.add_column(column, justify="right" if column == "items" else "left")
    for s in saved:
        table.add_row(s.list_key, str(s.item_count), s.last_synced or "never", s.url, s.last_error or "")
    Console(width=160).print(table)


@lists_app.command("add")
def lists_add(
    ctx: typer.Context,
    url: Annotated[
        str, typer.Argument(help="A YouTube playlist URL (also Watch Later: list=WL, Liked: list=LL).")
    ],
) -> None:
    """Register a Saved List. Its Videos are collected by `mp sync`."""
    normalized = normalize_list(url)
    if normalized is None:
        typer.echo(f"not a supported Saved List URL (YouTube playlists so far): {url}")
        raise typer.Exit(2)
    store = _open_pipeline(ctx.obj).store
    if store.add_list(normalized.list_key, normalized.platform, normalized.canonical_url):
        typer.echo(f"added {normalized.list_key}. Run `mp sync` to collect its Videos.")
    else:
        typer.echo(f"{normalized.list_key} is already registered")
    if normalized.private:
        typer.echo(
            f"{normalized.list_id} is private: `mp sync` needs `mp login {normalized.platform}` first."
        )


@app.command()
def sync(
    ctx: typer.Context,
    only: Annotated[
        str | None, typer.Option("--list", help="Sync only this Saved List (its URL or List Key).")
    ] = None,
) -> None:
    """Collect every Video of the Saved Lists into the State Store. Re-syncing adds only new ones."""
    app_ctx: AppContext = ctx.obj
    store = _open_pipeline(app_ctx).store
    if not store.saved_lists():
        typer.echo("No Saved Lists yet. Add one with `mp lists add <playlist url>`.")
        raise typer.Exit(2)
    keys = None
    if only is not None:
        normalized = normalize_list(only)
        keys = [normalized.list_key if normalized else only]
        if not any(s.list_key == keys[0] for s in store.saved_lists()):
            typer.echo(f"{only} is not a registered Saved List (see `mp lists`)")
            raise typer.Exit(2)
    results = sync_lists(store, app_ctx.adapters.collectors, app_ctx.adapters.web.expand, only=keys)
    for r in results:
        if r.error is not None:
            typer.echo(f"FAILED {r.list_key}: {r.error}")
            continue
        typer.echo(f"{r.list_key}: {r.seen} listed, {len(r.new)} new, {len(r.unsupported)} unsupported")
        for url in r.unsupported:
            typer.echo(f"  unsupported {url}")
    typer.echo(f"Videos in the State Store: {len(store.videos())}. Run `mp run` to process the new ones.")
    raise typer.Exit(1 if any(r.error for r in results) else 0)


@app.command()
def run(
    ctx: typer.Context,
    limit: Annotated[int | None, typer.Option(help="Process at most this many items per stage.")] = None,
    stages: Annotated[str | None, typer.Option(help="Comma-separated stages to run.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Write payloads under work/payloads; no Mealie writes.")
    ] = False,
    upgrade_existing: Annotated[
        bool,
        typer.Option(
            "--upgrade-existing",
            help="PATCH recipes already in Mealie (matched by link) with the parsed version, in place.",
        ),
    ] = False,
    mode: Annotated[
        str, typer.Option(help="skip: leave recipes already in Mealie alone. update: PATCH them in place.")
    ] = "skip",
    workers: Annotated[
        int | None,
        typer.Option(
            min=1,
            help="Items handled at the same time by find, scrape and extract (default: run.workers).",
        ),
    ] = None,
) -> None:
    """Take every registered Video through metadata, classify, extract, parse, tag and upload."""
    app_ctx: AppContext = ctx.obj
    worker_count = workers or app_ctx.settings.run.workers
    chosen = [s.strip() for s in stages.split(",")] if stages else None
    unknown = [s for s in chosen or [] if s not in STAGES and s not in REQUEST_STAGES]
    if unknown:
        typer.echo(f"unknown stage(s): {', '.join(unknown)}. Stages: {', '.join([*REQUEST_STAGES, *STAGES])}")
        raise typer.Exit(2)
    # A plain `mp run` also finds pages for pending Recipe Requests; with --stages, only if listed.
    find_requested = chosen is None or "find" in chosen
    if chosen is not None:
        chosen = [s for s in chosen if s != "find"]
    if mode not in ("skip", "update"):
        typer.echo("--mode must be skip or update")
        raise typer.Exit(2)
    pipeline = _open_pipeline(app_ctx)
    interrupted = False

    def on_interrupt(signum, frame):  # noqa: ARG001
        nonlocal interrupted
        if interrupted:  # a second Ctrl+C means it
            raise KeyboardInterrupt
        interrupted = True
        typer.echo("Ctrl+C: finishing the current item, then stopping (press again to abort)...")

    previous_handler = signal.signal(signal.SIGINT, on_interrupt)
    find_failed = False
    try:
        if find_requested:
            find_failed = _run_find(app_ctx, pipeline, limit, lambda: interrupted, worker_count)
        if chosen is None or chosen:
            report = pipeline.run(
                stages=chosen,
                limit=limit,
                dry_run=dry_run,
                mode=mode,
                upgrade_existing=upgrade_existing,
                should_stop=lambda: interrupted,
                workers=worker_count,
            )
        else:  # only `find` was asked for
            report = RunReport()
            report.stopped = (
                "Interrupted after the current request. Run again to continue."
                if (interrupted and find_failed)
                else None
            )
    finally:
        signal.signal(signal.SIGINT, previous_handler)
    for stage in STAGES:
        if stage in report.done:
            typer.echo(f"{stage}: {report.done[stage]} done")
    for line in report.uploaded:
        typer.echo(f"uploaded {line}")
    for path in report.dry_run_files:
        typer.echo(f"dry run: wrote {path}")
    for line in report.warnings:
        typer.echo(f"warning {line}")
    for line in report.already_in_mealie:
        typer.echo(f"already_in_mealie {line}")
    for line in report.upgraded_existing:
        typer.echo(f"upgraded_existing {line}")
    if report.already_in_mealie or report.upgraded_existing:
        typer.echo(
            f"{len(report.already_in_mealie)} already in Mealie (skipped), "
            f"{len(report.upgraded_existing)} existing recipes upgraded"
        )
    for line in report.not_recipes:
        typer.echo(f"skipped {line}")
    for line in report.review:
        typer.echo(f"REVIEW {line}")
    for line in report.failed:
        typer.echo(f"FAILED {line}")
    if report.stopped:
        typer.echo(report.stopped)
    _print_request_summary(pipeline, app_ctx.workspace)
    raise typer.Exit(1 if report.failed or report.stopped or find_failed else 0)


def _print_request_summary(pipeline: Pipeline, workspace: Path) -> None:
    requests = RecipeRequests(pipeline.store)
    counts = requests.counts()
    if not counts:
        return
    typer.echo(
        "requests: " + ", ".join(f"{n} {name}" for name in REQUEST_STATUSES if (n := counts.get(name, 0)))
    )
    typer.echo(f"wrote {write_requests_report(requests, workspace)}")


def _run_find(
    app_ctx: AppContext, pipeline: Pipeline, limit: int | None, should_stop, workers: int = 1
) -> bool:
    """The `find` stage for Recipe Requests; returns True when it stopped early (outage, Ctrl+C)."""
    requests = RecipeRequests(pipeline.store)
    if not requests.all():
        return False  # no sheet imported: nothing to find
    policy_file = app_ctx.workspace / "config" / "recipe_sites.yaml"
    policy = SitePolicy.from_config(
        yaml.safe_load(policy_file.read_text(encoding="utf-8")) if policy_file.is_file() else {}
    )
    finder = RequestFinder(
        app_ctx.workspace,
        app_ctx.settings.find,
        requests,
        app_ctx.adapters.search,
        app_ctx.adapters.search_fallback,
        app_ctx.adapters.web,
        pipeline.selectors,
        policy,
    )
    result = finder.run(limit=limit, should_stop=should_stop, workers=workers)
    for line in result.choices_applied:
        typer.echo(f"choice applied {line}")
    for line in result.found:
        typer.echo(f"found {line}")
    for line in result.needs_choice:
        typer.echo(f"needs_choice {line}")
    for line in result.not_found:
        typer.echo(f"not_found {line}")
    for line in result.warnings:
        typer.echo(f"warning {line}")
    counts = requests.counts()
    typer.echo(
        f"find: {len(result.found)} found, {len(result.needs_choice)} need a choice, "
        f"{len(result.not_found)} not found ({result.searched} searches, {result.fallback_used} "
        f"with the Claude fallback). Pending: {counts.get('pending', 0)}"
    )
    if counts.get("needs_choice"):
        typer.echo("Fill the `choice` column in reports/request_choices.csv, then run this stage again.")
    if result.stopped:
        typer.echo(result.stopped)
    write_requests_report(requests, app_ctx.workspace)
    return result.stopped is not None


@app.command()
def status(ctx: typer.Context) -> None:
    """Counts per stage and status, the totals, and the 10 most recent errors."""
    store = _open_pipeline(ctx.obj).store
    counts = store.stage_counts()
    table = Table(title="Stages")
    table.add_column("stage")
    for name in STATUSES:
        table.add_column(name, justify="right")
    for stage in STAGES:
        table.add_row(stage, *(str(counts.get((stage, name), 0)) for name in STATUSES))
    console = Console(width=120)
    console.print(table)
    console.print(f"Videos: {len(store.videos())}   Recipe Parts: {len(store.parts())}")
    retried = sum(1 for p in store.parts() if (p.verify or {}).get("extraction_attempts", 1) > 1)
    held = sum(1 for p in store.parts() if (p.verify or {}).get("outcome") == "review")
    console.print(f"Gate: {held} in the Review Queue, {retried} extracted a second time after a failed check")
    skipped = sum(n for (_stage, state), n in counts.items() if state == "already_in_mealie")
    upgraded = sum(n for (_stage, state), n in counts.items() if state == "upgraded_existing")
    console.print(f"Already in Mealie: {skipped}   Upgraded existing: {upgraded}")
    errors = store.recent_errors(10)
    if errors:
        console.print("\nRecent errors:")
        for record in errors:
            console.print(f"  {record.entity_key} [{record.stage}]: {record.last_error}", markup=False)


def _stages_from(stage: str) -> list[str]:
    if stage not in STAGES:
        typer.echo(f"unknown stage {stage!r}. Stages: {', '.join(STAGES)}")
        raise typer.Exit(2)
    return STAGES[STAGES.index(stage) :]


@app.command()
def retry(
    ctx: typer.Context,
    key: Annotated[str, typer.Argument(help="An item key (youtube:ID#1) or a Video Key (youtube:ID).")],
    stage: Annotated[
        str | None, typer.Option(help="Re-run from this stage instead of the failed one.")
    ] = None,
) -> None:
    """Run a failed item again (and every stage after the failed one) on the next `mp run`."""
    store = _open_pipeline(ctx.obj).store
    if stage is None:
        failed = [
            r.stage
            for r in store.stage_records()
            if r.status == "failed" and (r.entity_key == key or r.entity_key.startswith(f"{key}#"))
        ]
        if not failed:
            typer.echo(f"nothing failed for {key}")
            raise typer.Exit(1)
        stage = min(failed, key=STAGES.index)
    removed = store.reset_stages(_stages_from(stage), keys=[key])
    typer.echo(f"{key}: reset from {stage} ({removed} stage records). Run `mp run` to process it.")


@app.command()
def reset(
    ctx: typer.Context,
    stage: Annotated[str, typer.Argument(help="Stage to run again, together with every later stage.")],
    failed_only: Annotated[bool, typer.Option("--failed-only", help="Only items that failed.")] = False,
) -> None:
    """Forget a stage (and the later ones) for every item. Re-run with `mp run --mode update`."""
    store = _open_pipeline(ctx.obj).store
    removed = store.reset_stages(_stages_from(stage), failed_only=failed_only)
    typer.echo(
        f"reset {stage} onward: {removed} stage records. Run `mp run` (`--mode update` to PATCH recipes)."
    )


@app.command()
def report(ctx: typer.Context) -> None:
    """Write reports/report.csv: one row per Recipe Part."""
    app_ctx: AppContext = ctx.obj
    path = write_report(_open_pipeline(app_ctx).store, app_ctx.workspace)
    typer.echo(f"wrote {path}")


requests_app = typer.Typer(help="Recipe Requests: a one-off sheet of recipe names to find and import.")
app.add_typer(requests_app, name="requests")


def _open_requests(ctx: typer.Context) -> tuple[RecipeRequests, Path]:
    app_ctx: AppContext = ctx.obj
    return RecipeRequests(StateStore(app_ctx.workspace / "pipeline.db")), app_ctx.workspace


@requests_app.callback(invoke_without_command=True)
def requests_list(
    ctx: typer.Context,
    show: Annotated[int, typer.Option(help="How many requests to list (0 = none).")] = 25,
) -> None:
    """Without a subcommand: status counts, the requests (with category and cell) and the latest errors."""
    if ctx.invoked_subcommand is not None:
        return
    requests, workspace = _open_requests(ctx)
    counts = requests.counts()
    table = Table(title="Recipe Requests")
    table.add_column("status")
    table.add_column("count", justify="right")
    for name in REQUEST_STATUSES:
        table.add_row(name, str(counts.get(name, 0)))
    console = Console(width=120)
    console.print(table)
    console.print(f"Requests: {sum(counts.values())}")
    everything = requests.all()
    if show > 0 and everything:
        listing = Table(title="Requests")
        for column in ("cell", "category", "name", "status"):
            listing.add_column(column)
        for r in everything[:show]:
            listing.add_row(r.position or "", r.category or "", r.name, r.status)
        console.print(listing)
        if len(everything) > show:
            console.print(f"... and {len(everything) - show} more (all of them are in reports/requests.csv)")
    errors = requests.recent_errors(10)
    if errors:
        console.print("\nRecent errors:")
        for r in errors:
            console.print(f"  row {r.row_number} {r.name}: {r.last_error}", markup=False)
    write_requests_report(requests, workspace)


@requests_app.command("add")
def requests_add(
    ctx: typer.Context,
    file: Annotated[Path, typer.Option("--file", help="A .csv or .xlsx with a header row.")],
    sheet: Annotated[str | None, typer.Option(help="Worksheet name (default: the first).")] = None,
    layout: Annotated[
        str,
        typer.Option(
            help="auto, list (one recipe per row, header with a name column) or grid "
            "(category titles in row 1, a recipe in every cell below)."
        ),
    ] = "auto",
) -> None:
    """Register one Recipe Request per recipe name in a CSV or Excel sheet."""
    requests, workspace = _open_requests(ctx)
    try:
        parsed = read_sheet(file, sheet, layout)
    except (SheetError, OSError) as err:
        typer.echo(f"cannot import {file}: {err}")
        raise typer.Exit(2) from err
    new, known = requests.add_rows(parsed.rows, file.name)
    how = "auto-detected" if layout == "auto" else "chosen with --layout"
    typer.echo(
        f"layout: {parsed.layout} ({how}); {len(parsed.rows)} request(s) from {parsed.columns} column(s)"
    )
    for warning in parsed.warnings:
        typer.echo(f"warning {warning}")
    if parsed.repeated:
        names = "; ".join(parsed.repeated)
        typer.echo(
            f"{len(parsed.repeated)} name(s) appear in more than one cell and are kept as separate "
            f"requests with their own category: {names}"
        )
    if parsed.duplicates:
        names = "; ".join(parsed.duplicates)
        typer.echo(f"{len(parsed.duplicates)} duplicate name(s) in the sheet, registered once: {names}")
    typer.echo(f"{new} new, {known} already known")
    write_requests_report(requests, workspace)


@requests_app.command("retry")
def requests_retry(
    ctx: typer.Context,
    ref: Annotated[str, typer.Argument(help="A cell like R2C1, a row number or a recipe name.")],
) -> None:
    """Put a request back to pending so the next run tries it again."""
    requests, workspace = _open_requests(ctx)
    reset, finished = requests.retry(ref)
    for r in finished:
        typer.echo(f"row {r.row_number} {r.name}: already {r.status}, left alone")
    if not reset and not finished:
        typer.echo(f"no request matches {ref!r}")
        raise typer.Exit(1)
    for r in reset:
        typer.echo(f"row {r.row_number} {r.name}: back to pending")
    write_requests_report(requests, workspace)


@requests_app.command("reset")
def requests_reset(
    ctx: typer.Context,
    failed_only: Annotated[bool, typer.Option("--failed-only", help="Reset the failed requests.")] = False,
) -> None:
    """Put failed requests back to pending."""
    if not failed_only:
        typer.echo("only `mp requests reset --failed-only` exists: pass --failed-only")
        raise typer.Exit(2)
    requests, workspace = _open_requests(ctx)
    typer.echo(f"{requests.reset_failed()} failed request(s) back to pending")
    write_requests_report(requests, workspace)


review_app = typer.Typer(help="Decide the Videos the pipeline could not sort by itself.")
app.add_typer(review_app, name="review")


@review_app.command("classify")
def review_classify(ctx: typer.Context) -> None:
    """Walk the Videos the classifier was unsure about; each answer is saved as an Override."""
    app_ctx: AppContext = ctx.obj
    store = _open_pipeline(app_ctx).store
    rules = ClassifyRules.load(app_ctx.workspace / "config" / "classify_rules.yaml")
    path = write_classification_csv(store, app_ctx.workspace / "reports" / "classification.csv", rules)
    queue = review_queue(store, path, app_ctx.settings.classify.confidence_threshold)
    if not queue:
        typer.echo("Nothing to review: no unsure Videos without an override.")
        return
    keys = ", ".join(f"{k}={label}" for k, label in REVIEW_KEYS.items())
    typer.echo(f"{len(queue)} Video(s) to review. Keys: {keys}, s=skip for now, q=quit")
    decided = 0
    for number, video in enumerate(queue, start=1):
        meta = video_meta(video)
        verdict = Verdict.from_dict(video.classification or {"label": "uncertain"})
        typer.echo(f"\n[{number}/{len(queue)}] {video.canonical_url}")
        typer.echo(f"Title:   {meta.title}")
        typer.echo(f"Creator: {meta.uploader}")
        typer.echo(f"Caption: {meta.description.strip()[:300]}")
        typer.echo(f"Classifier: {verdict.label} ({verdict.confidence:.2f}): {'; '.join(verdict.reasons)}")
        while True:
            answer = typer.prompt("Label", default="s", show_default=False).strip().lower()
            if answer in REVIEW_KEYS or answer in ("s", "q"):
                break
            typer.echo(f"Press one of: {', '.join(REVIEW_KEYS)}, s, q")
        if answer == "q":
            break
        if answer == "s":
            continue
        set_override(path, video.video_key, REVIEW_KEYS[answer])
        decided += 1
    typer.echo(f"\n{decided} override(s) saved to {path.name}. Run `mp run` to continue with them.")
