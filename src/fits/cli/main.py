from __future__ import annotations

from fits.workflows.checks.models import PreflightReport
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
def run(settings: Path = typer.Argument(..., help="Path to a FITS settings TOML file.")) -> None:
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


@app.command("channel-labels")
def channel_labels_command(run_dir: Path = typer.Argument(..., help="FITS run directory to inspect."),
                           set_label: list[str] = typer.Option([],
                                                               "--set",
                                                               help="New label as INDEX=NAME; repeat for channels.",
                                                               ),
                           apply: bool = typer.Option(False,
                                                      "--apply",
                                                      help="Write the rename after preview.",
                                                      ),
                           ) -> None:
    """
    Inspect channel labels, preview a run-wide rename, or apply it.
    """
    from fits.channel_labels import inspect_run, apply_labels, files_to_update, validate_labels

    try:
        plan = inspect_run(run_dir)
        proposed = dict(plan.labels)
        for item in set_label:
            index_text, separator, label = item.partition("=")
            if not separator:
                raise ValueError(f"Expected INDEX=NAME, got {item!r}.")
            proposed[int(index_text)] = label
        proposed = validate_labels(plan, proposed)
        for index, old in plan.labels:
            typer.echo(f"{index}: {old} -> {proposed[index]}")
        targets = files_to_update(plan, proposed)
        typer.echo(f"Scanned {len(plan.files)} FITS files. Files to update ({len(targets)}):")
        for path in targets:
            typer.echo(f"  {path.relative_to(plan.run_dir)}")
        if apply:
            changed = apply_labels(plan, proposed)
            typer.echo(f"Updated {len(changed)} files.")
        elif set_label:
            typer.echo("Preview only. Add --apply to save.")
    except (OSError, ValueError, RuntimeError) as error:
        typer.echo(f"Channel labels: {error}", err=True)
        raise typer.Exit(1) from error


@app.command("compact")
def compact_command(run_dir: Path = typer.Argument(..., help="Run directory to preview and compact."))-> None:
    """
    Review conflicts and exact cleanup in the shared interactive compact window.
    """
    from fits.gui.file_management.compaction import run_compaction_ui
    from fits.gui.theme import apply_dark_theme, get_application
    from fits.settings.loader import run_settings_path
    from fits.workflows.runtime.errors import PipelineCancelled
    app_instance = get_application()
    apply_dark_theme(app_instance)
    def rebuild(report: PreflightReport) -> None:
        """
        Return the current rebuild.
        """
        settings = run_settings_path(run_dir)
        if not settings.is_file():
            raise ValueError("No saved run settings are available for rebuilding.")
        run_pipeline_cli(settings, artifact_decision=lambda pending: "rebuild")
    try:
        files = run_compaction_ui(run_dir, rebuild=rebuild)
        typer.echo(f"Compactd {len(files)} final artifacts.")
    except PipelineCancelled as error:
        typer.echo(str(error))
    except Exception as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error


@app.command('manage')
def manage_command(run_dir: Path = typer.Argument(..., help='Run or processed acquisition folder to manage.'),
                   ) -> None:
    """
    Migrate files, update paths/tags or downstream results, and manage history.
    """
    from fits.gui.theme import apply_dark_theme, get_application
    from fits.gui.file_management.manager import manage_files
    from fits.workflows.experiments.roots import resolve_run_root
    application = get_application()
    apply_dark_theme(application)
    selected = run_dir.expanduser().resolve()
    quit_on_close = application.quitOnLastWindowClosed()
    application.setQuitOnLastWindowClosed(False)
    try:
        manage_files(resolve_run_root(selected), selected)
    except Exception as error:
        typer.echo(str(error), err=True)
        raise typer.Exit(1) from error
    finally:
        application.setQuitOnLastWindowClosed(quit_on_close)


def main() -> None:
    """
    Run the FITS command-line entry point.
    """
    app()


if __name__ == "__main__":
    main()
