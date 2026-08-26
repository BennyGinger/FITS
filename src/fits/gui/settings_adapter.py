from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import ValidationError
from tomlkit import TOMLDocument

from fits.environment.constant import WORKFLOW_ORDER, StepName
from fits.workflows.engines.registry import REGISTRY


TEMPLATE_PATH = Path(__file__).parents[1] / "settings" / "template_settings.toml"
SAVED_SETTINGS_NAME = "fits_settings.toml"


@dataclass(frozen=True)
class StepLayout:
    title: str
    basic: tuple[str, ...]
    advanced: tuple[str, ...]


STEP_LAYOUTS: dict[StepName, StepLayout] = {
    StepName.CONVERT: StepLayout(
        title="Convert",
        basic=("channel_labels", "export_channels", "z_projection", "overwrite",),
        advanced=("compression", "execution", "workers"),
    ),
    StepName.REGISTER_TIME: StepLayout(
        title="Register time",
        basic=("context", "reference_strategy", "fit_channel", "overwrite"),
        advanced=("backend", "method", "execution", "workers"),
    ),
    StepName.REGISTER_CHANNEL: StepLayout(
        title="Register channels",
        basic=(
            "context",
            "reference_channel",
            "exclude_channel",
            "reference_frame",
            "overwrite",
        ),
        advanced=("backend", "method", "execution", "workers"),
    ),
    StepName.BG_SUB: StepLayout(
        title="Background subtraction",
        basic=("size", "sigma", "exclude_channel", "overwrite"),
        advanced=(
            "threshold",
            "statistic",
            "execution",
            "workers",
            "bg_execution",
            "bg_workers",
        ),
    ),
    StepName.SEGMENT: StepLayout(
        title="Segmentation",
        basic=(
            "channel_to_segment",
            "do_denoise",
            "nuclear_channel",
            "user_settings.model_type",
            "user_settings.diameter",
            "user_settings.flow_threshold",
            "user_settings.cellprob_threshold",
            "user_settings.do_3D",
            "user_settings.stitch_threshold",
            "overwrite",
        ),
        advanced=("execution", "workers"),
    ),
    StepName.TRACK: StepLayout(
        title="Tracking",
        basic=("channel_to_track", "filter_by_length", "overwrite"),
        advanced=(
            "backend",
            "trackastra.mode",
            "trackastra.pretrained_model",
            "trackastra.max_distance",
            "execution",
            "workers",
        ),
    ),
    StepName.EXTRACT: StepLayout(
        title="Quantification",
        basic=("additional_properties", "overwrite"),
        advanced=("execution", "workers", "frame_workers"),
    ),
}


FIELD_LABELS: dict[str, str] = {
    "bg_execution": "Frame execution",
    "bg_workers": "Frame workers",
    "cellprob_threshold": "Cell probability threshold",
    "do_3D": "Process in 3D",
    "do_denoise": "Denoise",
    "export_channels": "Export channels",
    "filter_by_length": "Minimum track length",
    "fit_channel": "Fitting channel",
    "frame_workers": "Frame workers",
    "nuclear_channel": "Nuclear channel",
    "reference_frame": "Reference frame",
    "reference_strategy": "Reference strategy",
    "z_projection": "Z projection",
}


FIELD_CHOICES: dict[str, tuple[str, ...]] = {
    "bg_execution": ("sequential", "thread"),
    "compression": ("zlib", "lzma", "jpeg", "None"),
    "execution": ("serial", "thread", "process"),
    "method": ("None", "translation", "rigid_body", "affine"),
    "mode": ("greedy", "greedy_nodiv", "ilp"),
    "pretrained_model": ("ctc", "general_2d", "general_2d_w_SAM2_features"),
    "reference_strategy": ("previous", "first", "mean"),
    "statistic": ("median", "mean"),
    "z_projection": ("max", "mean", "sum", "std"),
}

RUNTIME_CHOICES: dict[str, tuple[str, ...]] = {
    "execution": ("batch", "conveyor"),
    "console_level": ("debug", "info", "warning", "error", "critical"),
    "file_level": ("debug", "info", "warning", "error", "critical"),
}


STEP_FIELD_CHOICES: dict[tuple[StepName, str], tuple[str, ...]] = {
    (StepName.REGISTER_TIME, "context"): (
        "linear_drift",
        "rotational_drift",
        "complex_drift",
    ),
    (StepName.REGISTER_CHANNEL, "context"): (
        "channel_shift",
        "channel_shift_dual_cam",
        "channel_shift_complex",
    ),
    (StepName.REGISTER_TIME, "backend"): ("None", "scikit", "pystackreg", "cv2"),
    (StepName.REGISTER_CHANNEL, "backend"): (
        "None",
        "scikit",
        "pystackreg",
        "cv2",
    ),
    (StepName.TRACK, "backend"): ("trackastra",),
}


def field_choices(step: StepName, path: str) -> tuple[str, ...] | None:
    name = path.rsplit(".", 1)[-1]
    return STEP_FIELD_CHOICES.get((step, name), FIELD_CHOICES.get(name))


def field_label(path: str) -> str:
    name = path.rsplit(".", 1)[-1]
    return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def _merge_missing(
    target: MutableMapping[str, Any],
    defaults: Mapping[str, Any],
) -> None:
    for key, default_value in defaults.items():
        if key not in target:
            target[key] = deepcopy(default_value)
            continue
        target_value = target[key]
        if isinstance(target_value, MutableMapping) and isinstance(default_value, Mapping):
            _merge_missing(target_value, default_value)


class SettingsAdapter:
    """Own a comment-preserving settings document for the GUI."""

    def __init__(self, template_path: Path = TEMPLATE_PATH) -> None:
        self.template_path = template_path
        self.document = self._parse(template_path)
        self.source_path: Path | None = None

    @staticmethod
    def _parse(path: Path) -> TOMLDocument:
        return tomlkit.parse(path.read_text(encoding="utf-8"))

    def reset(self) -> None:
        self.document = self._parse(self.template_path)
        self.source_path = None

    def load(self, path: str | Path) -> None:
        source = Path(path).expanduser().resolve()
        document = self._parse(source)
        defaults = self._parse(self.template_path)
        _merge_missing(document, defaults)
        self.document = document
        self.source_path = source

    @property
    def run_dir(self) -> str:
        return str(self.document.get("run_dir", ""))

    @run_dir.setter
    def run_dir(self, value: str) -> None:
        self.document["run_dir"] = value

    @property
    def user_name(self) -> str:
        return str(self.document.get("user_name", ""))

    @user_name.setter
    def user_name(self, value: str) -> None:
        self.document["user_name"] = value

    def step_enabled(self, step: StepName) -> bool:
        return bool(self.document[step].get("enabled", False))

    def set_step_enabled(self, step: StepName, enabled: bool) -> None:
        self.document[step]["enabled"] = enabled

    def runtime_value(self, name: str) -> Any:
        return self.document["runtime"][name]

    def default_runtime_value(self, name: str) -> Any:
        defaults = self._parse(self.template_path)
        return defaults["runtime"][name]

    def set_runtime_value(self, name: str, value: Any) -> None:
        self.document["runtime"][name] = value

    def field_value(self, step: StepName, path: str) -> Any:
        return self._field_value_from_document(self.document, step, path)

    def default_field_value(self, step: StepName, path: str) -> Any:
        defaults = self._parse(self.template_path)
        return self._field_value_from_document(defaults, step, path)

    @staticmethod
    def _field_value_from_document(
        document: TOMLDocument,
        step: StepName,
        path: str,
    ) -> Any:
        node: Any = document[step]["params"]
        for part in path.split("."):
            node = node[part]
        if isinstance(node, Sequence) and not isinstance(node, str):
            return list(node)
        return node

    def set_field_value(self, step: StepName, path: str, value: Any) -> None:
        parts = path.split(".")
        node: Any = self.document[step]["params"]
        for part in parts[:-1]:
            if part not in node:
                node[part] = tomlkit.table()
            node = node[part]
        node[parts[-1]] = value

    def step_description(self, step: StepName) -> str:
        docstring = REGISTRY[step].settings_model.__doc__ or ""
        return docstring.strip().split("\n\n", 1)[0].replace("\n", " ")

    def step_documentation(self, step: StepName) -> str:
        return (REGISTRY[step].settings_model.__doc__ or "").strip()

    def validate_steps(self) -> dict[StepName, ValidationError]:
        errors: dict[StepName, ValidationError] = {}
        for step in WORKFLOW_ORDER:
            params = self.document[step].get("params", {})
            if hasattr(params, "unwrap"):
                params = params.unwrap()
            try:
                REGISTRY[step].model_validate(params)
            except ValidationError as error:
                errors[step] = error
        return errors

    def validate_for_run(self) -> list[str]:
        errors: list[str] = []
        run_dir = self.run_dir.strip()
        if not run_dir:
            errors.append("Select a run directory.")
        elif not Path(run_dir).expanduser().is_dir():
            errors.append("The selected run directory does not exist.")
        if not self.user_name.strip():
            errors.append("Enter a user name.")

        for step, error in self.validate_steps().items():
            if self.step_enabled(step):
                errors.append(f"{STEP_LAYOUTS[step].title}: {error.errors()[0]['msg']}")
        return errors

    def save(self, path: str | Path) -> Path:
        destination = Path(path).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(tomlkit.dumps(self.document), encoding="utf-8")
        self.source_path = destination
        return destination

    def save_to_run_dir(self) -> Path:
        run_dir = Path(self.run_dir).expanduser().resolve()
        return self.save(run_dir / SAVED_SETTINGS_NAME)

    def as_mapping(self) -> Mapping[str, Any]:
        return self.document.unwrap()
