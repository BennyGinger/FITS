from __future__ import annotations
from pathlib import Path
from typing import Any
import tomllib
import os
import tomlkit
from collections.abc import Mapping, MutableMapping
from tempfile import NamedTemporaryFile
from datetime import datetime, timezone
from fisch.environment.paths import ensure_metadata_directory, pipeline_dir
from fisch.environment import naming


SAVED_SETTINGS_NAME = naming.SETTINGS


def write_settings(path: Path, contents: str, *, backup: bool = False) -> Path:
    """
    Publish settings atomically, retaining a changed run snapshot before replacement.
    """
    path = path.expanduser().resolve()
    encoded = contents.encode("utf-8")
    previous = path.read_bytes() if path.is_file() else None
    if previous == encoded:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(dir=path.parent, prefix=".settings.", suffix=".tmp", delete=False) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(encoded)
        if backup and previous is not None:
            history = path.parent / "settings_history"
            history.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
            (history / f"settings_{stamp}.toml").write_bytes(previous)
        os.replace(temporary_path, path)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
    return path


def normalize_registration_algorithms(document: MutableMapping[str, Any]) -> bool:
    """
    Rename legacy registration backend keys while preserving their TOML values.
    """
    changed = False
    for name in ("register_time", "register_channel"):
        step = document.get(name)
        if not isinstance(step, Mapping):
            continue
        params = step.get("params")
        if isinstance(params, MutableMapping) and "backend" in params:
            previous = params.pop("backend")
            if "algorithm" not in params:
                params["algorithm"] = previous
            changed = True
    return changed


def run_settings_path(run_dir: Path) -> Path:
    """
    Return the canonical settings snapshot path for a FIScH run.
    """
    current = pipeline_dir(run_dir) / SAVED_SETTINGS_NAME
    legacy = run_dir / naming.LEGACY_RUN_METADATA / naming.LEGACY_SETTINGS
    return current if current.is_file() or not legacy.is_file() else legacy


def load_settings(path: str | Path) -> dict[str, Any]:
    """
    Load settings from a TOML file and return them as a dictionary.
    """
    input_path = Path(path).expanduser().resolve()
    settings = tomllib.loads(input_path.read_text())
    normalize_registration_algorithms(settings)
    if input_path.name in (SAVED_SETTINGS_NAME, naming.LEGACY_SETTINGS) and input_path.parent.name in (naming.RUN_METADATA, naming.LEGACY_RUN_METADATA):
        settings['run_dir'] = str(input_path.parent.parent)
    return settings


def save_run_settings(source: Path, run_dir: Path) -> Path:
    """
    Preserve the input TOML, including comments, in the run's ``.pipeline`` folder.

    Replace the previous snapshot only after the complete copy is written.
    GUI launches already use this file, so copying it onto itself is a no-op.
    """
    source = source.expanduser().resolve()
    destination = run_settings_path(run_dir)
    contents = source.read_bytes()
    document = tomlkit.parse(contents.decode('utf-8'))
    renamed = normalize_registration_algorithms(document)
    if document.get('run_dir') != str(run_dir.resolve()) or renamed:
        document['run_dir'] = str(run_dir.resolve())
        contents = tomlkit.dumps(document).encode('utf-8')
    if source == destination.resolve() and contents == source.read_bytes():
        return destination
    ensure_metadata_directory(destination.parent)
    return write_settings(destination, contents.decode("utf-8"), backup=True)


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
