"""The `mp` command line."""

import signal
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from mealie_pipeline.adapters import Adapters, build_adapters
from mealie_pipeline.doctor import exit_code, render, run_doctor
from mealie_pipeline.pipeline import STAGES, Pipeline
from mealie_pipeline.reports import STATUSES, write_report
from mealie_pipeline.settings import Settings, load_settings
from mealie_pipeline.store import StateStore
from mealie_pipeline.url_normalizer import normalize

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
    checks = run_doctor(app_ctx.adapters, app_ctx.settings)
    typer.echo(render(checks))
    raise typer.Exit(exit_code(checks))


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
        if normalized is None:
            typer.echo(f"unsupported URL (only YouTube so far): {url}")
            unsupported += 1
        elif pipeline.add(normalized.canonical_url, url, normalized.platform, normalized.video_id):
            typer.echo(f"added {normalized.video_key}")
            added += 1
        else:
            typer.echo(f"already known {normalized.video_key}")
            duplicates += 1
    typer.echo(f"{added} added, {duplicates} already known, {unsupported} unsupported")


@app.command()
def run(
    ctx: typer.Context,
    limit: Annotated[int | None, typer.Option(help="Process at most this many items per stage.")] = None,
    stages: Annotated[str | None, typer.Option(help="Comma-separated stages to run.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Write payloads under work/payloads; no Mealie writes.")
    ] = False,
    mode: Annotated[
        str, typer.Option(help="skip: leave recipes already in Mealie alone. update: PATCH them in place.")
    ] = "skip",
) -> None:
    """Take every registered Video through metadata, extract, parse, tag and upload."""
    app_ctx: AppContext = ctx.obj
    chosen = [s.strip() for s in stages.split(",")] if stages else None
    unknown = [s for s in chosen or [] if s not in STAGES]
    if unknown:
        typer.echo(f"unknown stage(s): {', '.join(unknown)}. Stages: {', '.join(STAGES)}")
        raise typer.Exit(2)
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
    try:
        report = pipeline.run(
            stages=chosen, limit=limit, dry_run=dry_run, mode=mode, should_stop=lambda: interrupted
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
    for line in report.review:
        typer.echo(f"REVIEW {line}")
    for line in report.failed:
        typer.echo(f"FAILED {line}")
    if report.stopped:
        typer.echo(report.stopped)
    raise typer.Exit(1 if report.failed or report.stopped else 0)


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
