"""The `mp` command line."""

from pathlib import Path
from typing import Annotated

import typer

from mealie_pipeline.adapters import Adapters, build_adapters
from mealie_pipeline.doctor import exit_code, render, run_doctor
from mealie_pipeline.pipeline import STAGES, Pipeline
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
    bad = 0
    for url in wanted:
        normalized = normalize(url)
        if normalized is None:
            typer.echo(f"unsupported URL (only YouTube so far): {url}")
            bad += 1
        elif pipeline.add(normalized.canonical_url, url, normalized.platform, normalized.video_id):
            typer.echo(f"added {normalized.video_key}")
        else:
            typer.echo(f"already known {normalized.video_key}")
    raise typer.Exit(1 if bad else 0)


@app.command()
def run(
    ctx: typer.Context,
    limit: Annotated[int | None, typer.Option(help="Process at most this many items per stage.")] = None,
    stages: Annotated[str | None, typer.Option(help="Comma-separated stages to run.")] = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Write payloads under work/payloads; no Mealie writes.")
    ] = False,
) -> None:
    """Take every registered Video through metadata, extract, parse, tag and upload."""
    app_ctx: AppContext = ctx.obj
    chosen = [s.strip() for s in stages.split(",")] if stages else None
    unknown = [s for s in chosen or [] if s not in STAGES]
    if unknown:
        typer.echo(f"unknown stage(s): {', '.join(unknown)}. Stages: {', '.join(STAGES)}")
        raise typer.Exit(2)
    pipeline = _open_pipeline(app_ctx)
    report = pipeline.run(stages=chosen, limit=limit, dry_run=dry_run)
    for stage in STAGES:
        if stage in report.done:
            typer.echo(f"{stage}: {report.done[stage]} done")
    for line in report.uploaded:
        typer.echo(f"uploaded {line}")
    for path in report.dry_run_files:
        typer.echo(f"dry run: wrote {path}")
    for line in report.warnings:
        typer.echo(f"warning {line}")
    for line in report.failed:
        typer.echo(f"FAILED {line}")
    if report.stopped:
        typer.echo(report.stopped)
    raise typer.Exit(1 if report.failed or report.stopped else 0)
