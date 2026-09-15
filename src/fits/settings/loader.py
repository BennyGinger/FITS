from pathlib import Path
from typing import Any
import tomllib
from collections.abc import Mapping
import os
from tempfile import NamedTemporaryFile

from fits.environment.paths import fits_dir


SAVED_SETTINGS_NAME = "fits_settings.toml"


def run_settings_path(run_dir: Path) -> Path:
    """Return the canonical settings snapshot path for a FITS run."""
    return fits_dir(run_dir) / SAVED_SETTINGS_NAME


def load_settings(path: str | Path) -> dict[str, Any]:
    """
    Load settings from a TOML file and return them as a dictionary.
    """
    input_path = Path(path).expanduser().resolve()
    return tomllib.loads(input_path.read_text())


def save_run_settings(source: Path, run_dir: Path) -> Path:
    """
    Preserve the input TOML, including comments, in the run's ``.fits`` folder.

    Replace the previous snapshot only after the complete copy is written.
    GUI launches already use this file, so copying it onto itself is a no-op.
    """
    source = source.expanduser().resolve()
    destination = run_settings_path(run_dir)
    if source == destination.resolve():
        return destination
    contents = source.read_bytes()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = None
    try:
        with NamedTemporaryFile(dir=destination.parent,
                                prefix=".fits_settings.", suffix=".tmp",
                                delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(contents)
        os.replace(temporary_path, destination)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return destination


def resolve_step_params(step_name: str, step_config: Mapping[str, Any]) -> dict[str, Any]:
    """
    Return model parameters, including step-level structured settings.

    Segmentation channel tables live at ``segment.channels`` in TOML so that
    shared execution controls remain grouped under ``segment.params``.
    """
    params = step_config.get("params", {})
    if not isinstance(params, Mapping):
        raise TypeError(f"Expected '{step_name}.params' to be a mapping.")

    resolved = dict(params)
    if step_name == "segment" and "channels" in step_config:
        if "channels" in resolved:
            raise ValueError("Define segmentation channels only once.")
        resolved["channels"] = step_config["channels"]
    return resolved
