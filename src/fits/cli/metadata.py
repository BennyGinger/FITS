from pathlib import Path

import typer
from fits_io.readers._types import StatusFlag

from fits.workflows.tasks.metadata_change import change_labels, change_status

metadata_app = typer.Typer(no_args_is_help=True)

def _read_dirs(path: Path) -> list[Path]:
    path = path.expanduser().resolve()
    
    if not path.exists():
        raise typer.BadParameter(f"{path} does not exist.")
    
    if path.is_file():
        if path.suffix != '.txt':
            raise typer.BadParameter("Selection file must be a .txt file listing experiment directories.")
        
        return [
            Path(line.strip()).expanduser().resolve()
            for line in path.read_text(encoding="utf-8").splitlines()
            if (s := line.strip()) and not s.startswith("#")
        ]
    return [path]

@metadata_app.command("labels")
def labels(
    path: Path = typer.Argument(..., help="Experiment dir OR text file (.txt only) listing experiment dirs. One path per line. Lines starting with # and empty lines are ignored."),
    label: list[str] = typer.Option(..., "--label", "-l", help="Repeat for multiple labels."),
    recursive: bool = typer.Option(False, "--recursive", "-r"),
) -> None:
    dirs = _read_dirs(path)
    
    if any(not x.strip() for x in label):
        raise typer.BadParameter("Empty labels are not allowed.")
    
    change_labels(dirs, label, recursive=recursive)

@metadata_app.command("status")
def status(
    path: Path = typer.Argument(..., help="Experiment dir OR text file (.txt only) listing experiment dirs. One path per line. Lines starting with # and empty lines are ignored."),
    status: StatusFlag = typer.Option(..., "--status", "-s", help="New status to set. Must be either 'active' or 'skip'."),
    recursive: bool = typer.Option(False, "--recursive", "-r"),
) -> None:
    dirs = _read_dirs(path)

    change_status(dirs, status, recursive=recursive)