from __future__ import annotations

import typer

from fits.cli.metadata import metadata_app
from fits.cli.pipeline import pipeline_app

app = typer.Typer(
    no_args_is_help=True,
    help="FITS pipeline command line interface.",
)

app.add_typer(metadata_app, name="metadata")
app.add_typer(pipeline_app, name="pipeline")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
