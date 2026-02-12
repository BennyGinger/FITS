from pathlib import Path
import typer

from fits.pipeline import start_pipeline

pipeline_app = typer.Typer(no_args_is_help=True)


@pipeline_app.command("start")
def start(
    settings: Path | None = typer.Option(None, "--settings", "-s", help="Path to user_settings.toml. If omitted, uses the default packaged settings.")
) -> None:
    
    if settings is not None:
        settings = settings.expanduser().resolve()
        if not settings.exists():
            raise typer.BadParameter(f"Settings file {settings} does not exist.")
        if not settings.is_file():
            raise typer.BadParameter(f"Settings path {settings} is not a file.")

    start_pipeline(settings_path=settings)
