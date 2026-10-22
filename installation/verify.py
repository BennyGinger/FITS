"""Check installed imports and model-cache permissions without loading models."""

from importlib import import_module
from pathlib import Path
from tempfile import TemporaryFile
import sys


def check_writable(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryFile(dir=directory):
            pass
    except OSError as error:
        raise RuntimeError(f"Model cache is not writable: {directory}. Run as your normal user. {error}") from error
    print(f"Writable model cache: {directory}", flush=True)


def hide_checkout_dot_entries(root: Path) -> None:
    """Hide only direct dot-prefixed checkout entries, without traversing data."""
    if sys.platform != "win32":
        return
    from fits.environment.hidden import hide_on_windows

    try:
        entries = list(root.iterdir())
    except OSError as error:
        print(f"Note: could not inspect checkout visibility: {error}", flush=True)
        return
    for entry in entries:
        if entry.name.startswith(".") and not hide_on_windows(entry):
            print(f"Note: could not hide {entry}; installation will continue.", flush=True)
    print("Checked Windows visibility of dot-prefixed checkout entries.", flush=True)


def main() -> None:
    for module in (
        "fits.gui.main", "cellpose.models", "tracklink.backends.trackastra.base",
        "micro_sam.util", "micro_sam.prompt_based_segmentation", "mobile_sam",
    ):
        import_module(module)
        print(f"Import OK: {module}", flush=True)

    from cellpose.models import MODEL_DIR
    from micro_sam.util import get_cache_directory
    from platformdirs import user_data_dir
    import torch

    for directory in (
        Path(MODEL_DIR), Path(get_cache_directory()) / "models",
        Path(user_data_dir("trackastra")) / "models",
    ):
        check_writable(directory)
    print(f"CUDA available: {torch.cuda.is_available()} (informational; not required)", flush=True)
    hide_checkout_dot_entries(Path(__file__).resolve().parents[1])


if __name__ == "__main__":
    main()
