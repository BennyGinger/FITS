"""Update known channel-bearing settings, provenance, and table fields."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import cast

import pandas as pd
import pyarrow.parquet as parquet
import tomlkit

from fits.environment import constant as cst
from fits.tasks.analysis.identity import add_quantification_ids


_TABLE_COLUMNS = {
    cst.FITS_QUANTI_NAME: ("object_channel", "intensity_channel", "ref_channel"),
    "master_quantification.parquet": ("object_channel", "intensity_channel", "ref_channel"),
    cst.FITS_DISTANCE_PROFILE_NAME: ("channel", "ref_channel", "roi_channel"),
    "master_distance_profile.parquet": ("channel", "ref_channel", "roi_channel"),
}
_SETTINGS_FIELDS = {
    "convert": ("channel_labels", "export_channels"),
    "register_time": ("fit_channel",),
    "register_channel": ("reference_channel", "exclude_channel"),
    "bg_sub": ("exclude_channel",),
    "track": ("channel_to_track",),
}
_WORKFLOW_FIELDS = ("channel_label", "fit_channel", "reference_channel",
                    "exclude_channel", "channel_to_track", "nuclear_channel")


def _labels_in(value) -> set[str]:
    if isinstance(value, str):
        return {value}
    if isinstance(value, (list, tuple)):
        return set().union(*(_labels_in(item) for item in value))
    return set()


def _settings_entries(doc):
    for section, keys in _SETTINGS_FIELDS.items():
        params = doc.get(section, {}).get("params", {})
        for key in keys:
            if key in params:
                yield params, key
    for channel in doc.get("segment", {}).get("channels", []):
        for key in ("channel", "nuclear_channel"):
            if key in channel:
                yield channel, key


def labels_in_settings(path: Path) -> frozenset[str]:
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    return frozenset().union(*(_labels_in(entry[key]) for entry, key in _settings_entries(doc)))


def _workflow_entries(meta):
    display = meta.get("tracking_viewer_display")
    if isinstance(display, dict):
        for key in ("raw_image_channel", "mask_channel"):
            if key in display:
                yield display, key
    for step in meta.get("steps", {}).values():
        for params in [step.get("params", {}),
                       *(entry for entry in step.get("channels", {}).values())]:
            for key in _WORKFLOW_FIELDS:
                if key in params:
                    yield params, key


def labels_in_workflow_meta(meta) -> frozenset[str]:
    return frozenset().union(*(_labels_in(entry[key]) for entry, key in _workflow_entries(meta)))


def labels_in_state(path: Path) -> frozenset[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return labels_in_workflow_meta(data.get("meta", {}))


def labels_in_table(path: Path) -> frozenset[str]:
    available = set(parquet.read_schema(path).names)
    columns = [column for column in _TABLE_COLUMNS[path.name] if column in available]
    if not columns:
        return frozenset()
    data = pd.read_parquet(path, columns=columns)
    return frozenset().union(*(
        {value for value in data[column].dropna().unique() if isinstance(value, str)}
        for column in columns))


def _replace_value(value, mapping: Mapping[str, str]):
    if isinstance(value, str):
        return mapping.get(value, value)
    if isinstance(value, list):
        return [_replace_value(item, mapping) for item in value]
    return value


def rename_settings_document(doc, mapping: Mapping[str, str]) -> None:
    """Update only named channel fields in a tomlkit settings document."""
    for entry, key in _settings_entries(doc):
        entry[key] = _replace_value(entry[key], mapping)


def render_settings(path: Path, mapping: Mapping[str, str]) -> bytes:
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    rename_settings_document(doc, mapping)
    return tomlkit.dumps(doc).encode("utf-8")


def render_state(path: Path, mapping: Mapping[str, str]) -> bytes:
    data = json.loads(path.read_text(encoding="utf-8"))
    rename_workflow_meta(data.get("meta", {}), mapping)
    return (json.dumps(data, indent=2) + "\n").encode("utf-8")


def rename_workflow_meta(meta: dict, mapping: Mapping[str, str]) -> None:
    for entry, key in _workflow_entries(meta):
        entry[key] = _replace_value(entry[key], mapping)


def rename_table(path: Path, mapping: Mapping[str, str]) -> pd.DataFrame:
    data = pd.read_parquet(path)
    changed = [old for old, new in mapping.items() if old != new]
    object_channel_changed = False
    if "object_channel" in data:
        channels = cast(pd.Series, data["object_channel"])
        object_channel_changed = cast(bool, channels.isin(changed).any())
    for column in _TABLE_COLUMNS[path.name]:
        if column in data:
            data[column] = data[column].replace(mapping)
    if (path.name.endswith("quantification.parquet") and "cell_id" in data
            and object_channel_changed):
        if "experiment_id" not in data:
            raise ValueError(f"{path}: cannot rebuild cell_id without experiment_id.")
        pieces = [add_quantification_ids(group, str(experiment_id))
                  for experiment_id, group in data.groupby("experiment_id", sort=False, dropna=False)]
        if pieces:
            data = pd.concat(pieces).sort_index()
    return data


