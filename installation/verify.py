"""Check installed imports and model-cache permissions without loading models."""

from importlib import import_module
from pathlib import Path
from tempfile import TemporaryFile


def check_writable(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        with TemporaryFile(dir=directory):
            pass
    except OSError as error:
        raise RuntimeError(f"Model cache is not writable: {directory}. Run as your normal user. {error}") from error
    print(f"Writable model cache: {directory}", flush=True)


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


if __name__ == "__main__":
    main()
