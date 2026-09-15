from __future__ import annotations

from pathlib import Path

import typer

from fits.cli.interactive import run_pipeline_cli

app = typer.Typer(no_args_is_help=True, help="Run a FITS image-analysis pipeline.")


@app.callback()
def command_group() -> None:
    """

    Keep pipeline execution under the explicit ``run`` command.

    """


@app.command()
def run(settings: Path = typer.Argument(..., help="Path to a FITS settings TOML file."),) -> None:
    """

    Run the pipeline described by a settings file.

    """
    settings = settings.expanduser().resolve()
    if not settings.exists():
        raise typer.BadParameter(f"Settings file {settings} does not exist.")
    if not settings.is_file():
        raise typer.BadParameter(f"Settings path {settings} is not a file.")
    if settings.suffix.lower() != ".toml":
        raise typer.BadParameter(f"Settings file {settings} must use the .toml extension.")
    run_pipeline_cli(settings)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
