"""Discover FITS-owned files and validate source-index-to-label mappings."""

from __future__ import annotations

import json
import tomllib
from collections.abc import Mapping
from pathlib import Path

from fits_io import FitsIO

from fits.channel_labels.lock import run_write_guard
from fits.channel_labels.model import LabelPlan
from fits.channel_labels.documents import (labels_in_settings, labels_in_state,
                                           labels_in_table, labels_in_workflow_meta)
from fits.environment import constant as cst
from fits.settings.loader import run_settings_path


_TIFF_NAMES = {name for name in cst.FITS_FILES if name.endswith(".tif")}
_TABLE_NAMES = {cst.FITS_QUANTI_NAME, "master_quantification.parquet",
                cst.FITS_DISTANCE_PROFILE_NAME, "master_distance_profile.parquet"}

def _tiff_name(name: str) -> bool:
    prefixes = (cst.FITS_REFERENCE_TEMPLATE.split("{", 1)[0],
                cst.FITS_ROI_TEMPLATE.split("{", 1)[0],
                cst.FITS_TRACK_OVERLAY_PREFIX)
    return (name in _TIFF_NAMES or name.startswith(prefixes)) and name.endswith(".tif")


def _fingerprint(path: Path) -> tuple[int, int]:
    stat = path.stat()
    return stat.st_size, stat.st_mtime_ns


def inspect_run(run_dir: str | Path) -> LabelPlan:
    """Validate all known FITS TIFFs against their original source indices."""
    root = Path(run_dir).expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f"Run directory does not exist: {root}")
    with run_write_guard(root):
        return _inspect_unlocked(root)


def _inspect_unlocked(root: Path) -> LabelPlan:
    tiffs = sorted(p for p in root.rglob("*.tif") if _tiff_name(p.name)
                   and ".fits" not in p.relative_to(root).parts)
    tables = sorted(p for p in root.rglob("*.parquet") if p.name in _TABLE_NAMES)
    settings_path = run_settings_path(root)
    settings = (settings_path,) if settings_path.is_file() else ()
    states = tuple(sorted(root.rglob("experiment_state.json")))
    labels: dict[int, str] = {}
    origins: dict[int, Path] = {}
    reverse: dict[str, int] = {}
    file_labels: dict[Path, frozenset[str]] = {}
    for path in tiffs:
        reader = FitsIO.from_path(path)
        indices = reader.artifact_channel_indices
        current = reader.channel_labels
        if not indices or len(indices) != len(current):
            raise ValueError(f"{path}: missing or invalid artifact_channel_indices; "
                             "channel identity cannot be established safely.")
        for index, label in zip(indices, current, strict=True):
            if not isinstance(index, int) or index < 0 or not label.strip():
                raise ValueError(f"{path}: invalid channel index or label.")
            if index in labels and labels[index] != label:
                raise ValueError(f"Channel {index} is {labels[index]!r} in {origins[index]} "
                                 f"but {label!r} in {path}.")
            if label in reverse and reverse[label] != index:
                raise ValueError(f"Label {label!r} maps to both source channel "
                                 f"{reverse[label]} and {index} ({path}).")
            labels[index], origins[index], reverse[label] = label, path, index
        file_labels[path] = frozenset(current) | labels_in_workflow_meta(
            reader.metadata.custom_metadata)
    if not labels:
        raise ValueError(f"No FITS TIFFs with channel lineage were found in {root}.")
    for path in settings:
        saved = tomllib.loads(path.read_text(encoding="utf-8"))
        configured = saved.get("convert", {}).get("params", {}).get("channel_labels")
        if isinstance(configured, str):
            configured = [configured]
        if isinstance(configured, list):
            for index, label in enumerate(configured):
                if index in labels and label != labels[index]:
                    raise ValueError(f"Source channel {index} is {labels[index]!r} in "
                                     f"{origins[index]} but {label!r} in {path}.")
        file_labels[path] = labels_in_settings(path)
    for path in states:
        data = json.loads(path.read_text(encoding="utf-8"))
        for step in data.get("meta", {}).get("steps", {}).values():
            for entry in step.get("channels", {}).values():
                index, label = entry.get("channel"), entry.get("channel_label")
                if isinstance(index, int) and isinstance(label, str):
                    if index in labels and label != labels[index]:
                        raise ValueError(f"Source channel {index} is {labels[index]!r} "
                                         f"in {origins[index]} but {label!r} in {path}.")
        file_labels[path] = labels_in_state(path)
    for path in tables:
        file_labels[path] = labels_in_table(path)
    files = (*tiffs, *tables, *settings, *states)
    return LabelPlan(root, tuple(sorted(labels.items())), tuple(tiffs), tuple(tables),
                     settings, states, tuple((p, file_labels[p]) for p in files),
                     tuple((p, _fingerprint(p)) for p in files))


def validate_labels(plan: LabelPlan, proposed: Mapping[int, str]) -> dict[int, str]:
    expected = dict(plan.labels)
    if set(proposed) != set(expected):
        raise ValueError("Provide exactly one label for each discovered source channel.")
    labels = {index: value.strip() for index, value in proposed.items()}
    if any(not value for value in labels.values()):
        raise ValueError("Channel labels cannot be empty.")
    if len(set(labels.values())) != len(labels):
        raise ValueError("Channel labels must be unique.")
    return labels


def files_to_update(plan: LabelPlan, proposed: Mapping[int, str]) -> tuple[Path, ...]:
    """Return only files referencing a source channel whose label will change."""
    labels = validate_labels(plan, proposed)
    changed = {old for index, old in plan.labels if labels[index] != old}
    return tuple(path for path, present in plan.file_labels if changed.intersection(present))


