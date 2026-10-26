"""The `mp` command line."""

from pathlib import Path
from typing import Annotated

import typer

from mealie_pipeline.adapters import Adapters, build_adapters
from mealie_pipeline.doctor import exit_code, render, run_doctor
from mealie_pipeline.settings import Settings, load_settings

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
    adapters = ctx.obj if isinstance(ctx.obj, Adapters) else build_adapters(settings)
    ctx.obj = AppContext(workspace, settings, adapters)


@app.command()
def doctor(ctx: typer.Context) -> None:
    """Check the setup: tools, logins and the connection to Mealie."""
    app_ctx: AppContext = ctx.obj
    checks = run_doctor(app_ctx.adapters, app_ctx.settings)
    typer.echo(render(checks))
    raise typer.Exit(exit_code(checks))
