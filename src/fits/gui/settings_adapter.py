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
        basic=("draw_ref_mask", "expected_ref_masks", "additional_properties", "overwrite"),
        advanced=("execution", "workers", "frame_workers"),
    ),
    StepName.DISTANCE_PROFILE: StepLayout(
        title="Distance profile",
        basic=("expected_ref_masks", "draw_roi_mask", "expected_roi_masks",
               "bin_width", "maximum_bins", "overwrite"),
        advanced=("execution", "workers"),
    ),
}


FIELD_LABELS: dict[str, str] = {
    "unlock_all_tabs": "Unlock all phase tabs",
    "draw_ref_mask": "Draw reference masks",
    "expected_ref_masks": "Expected reference masks",
    "draw_roi_mask": "Draw ROI masks",
    "expected_roi_masks": "Expected ROI masks",
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
    "bin_width": "Bin width (pixels)",
    "maximum_bins": "Maximum number of bins",
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
    "z_projection": ("None", "max", "mean", "sum", "std"),
}

RUNTIME_CHOICES: dict[str, tuple[str, ...]] = {
    "execution": ("batch", "conveyor"),
    "console_level": ("debug", "info", "warning", "error", "critical"),
    "file_level": ("debug", "info", "warning", "error", "critical"),
}

RUNTIME_FIELD_TOOLTIPS: dict[str, str] = {
    "execution": (
        "Pipeline scheduler mode. Batch completes each enabled step before the next; "
        "conveyor overlaps ready work between steps."
    ),
    "console_level": "Lowest severity written to the console log.",
    "file_level": "Lowest severity written to the log file.",
    "log_dir": (
        "Optional log root. Leave blank to create a logs folder inside the run "
        "directory."
    ),
    "unlock_all_tabs": (
        "Show all phase settings before converted arrays exist. Image viewers still "
        "require a real fits_array.tif file."
    ),
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

REQUIRED_USER_FIELDS: dict[StepName, tuple[tuple[str, str], ...]] = {
    StepName.CONVERT: (
        ("channel_labels", "Enter at least one channel label (channel_labels)."),
    ),
    StepName.REGISTER_CHANNEL: (
        ("reference_channel", "Choose a reference channel (reference_channel)."),
    ),
    StepName.SEGMENT: (
        ("channel_to_segment", "Choose at least one channel to segment (channel_to_segment)."),
    ),
    StepName.TRACK: (
        ("channel_to_track", "Choose at least one channel to track (channel_to_track)."),
    ),
}

STEP_FIELD_TOOLTIPS: dict[tuple[StepName, str], str] = {
    (StepName.CONVERT, "channel_labels"): (
        "Source-channel names in source order. The number of labels should match "
        "the channels in each input image."
    ),
    (StepName.CONVERT, "export_channels"): (
        'Channels to keep in the converted image. Use "all", one channel label, '
        "or a comma-separated list of labels."
    ),
    (StepName.CONVERT, "z_projection"): (
        "Projection applied across Z while loading: max, mean, sum, or standard "
        "deviation. Choose None to preserve the Z axis."
    ),
    (StepName.CONVERT, "overwrite"): (
        "Reconvert inputs even when an up-to-date converted artifact already exists."
    ),
    (StepName.CONVERT, "compression"): (
        "TIFF compression for converted images. Choose None for no requested "
        "compression."
    ),
    (StepName.CONVERT, "execution"): (
        "How experiments are converted: serially, with threads, or with processes."
    ),
    (StepName.CONVERT, "workers"): (
        "Maximum experiment workers. None lets the selected executor choose; this "
        "setting is ignored during serial execution."
    ),
    (StepName.REGISTER_TIME, "context"): (
        "Registration scenario used to choose suitable default backend and transform "
        "method settings."
    ),
    (StepName.REGISTER_TIME, "reference_strategy"): (
        "Frame used as the registration reference: the previous frame, the first "
        "frame, or the temporal mean."
    ),
    (StepName.REGISTER_TIME, "fit_channel"): (
        "Channel index or label used to estimate motion. None uses the first channel "
        "for multichannel images and is ignored for single-channel images."
    ),
    (StepName.REGISTER_TIME, "overwrite"): (
        "Repeat time registration even when an up-to-date registered artifact exists."
    ),
    (StepName.REGISTER_TIME, "backend"): (
        "Registration implementation. None uses the backend selected by the context."
    ),
    (StepName.REGISTER_TIME, "method"): (
        "Transform model fitted between frames. None uses the method selected by the "
        "context."
    ),
    (StepName.REGISTER_TIME, "execution"): (
        "How experiments are registered: serially, with threads, or with processes."
    ),
    (StepName.REGISTER_TIME, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
    (StepName.REGISTER_CHANNEL, "context"): (
        "Registration scenario used to choose suitable default backend and transform "
        "method settings for cross-channel alignment."
    ),
    (StepName.REGISTER_CHANNEL, "reference_channel"): (
        "Channel index or label held fixed while the other channels are aligned."
    ),
    (StepName.REGISTER_CHANNEL, "exclude_channel"): (
        "Channel labels to leave out of cross-channel registration."
    ),
    (StepName.REGISTER_CHANNEL, "reference_frame"): (
        "Zero-based frame used to estimate the cross-channel transforms."
    ),
    (StepName.REGISTER_CHANNEL, "overwrite"): (
        "Repeat channel registration even when an up-to-date registered artifact exists."
    ),
    (StepName.REGISTER_CHANNEL, "backend"): (
        "Registration implementation. None uses the backend selected by the context."
    ),
    (StepName.REGISTER_CHANNEL, "method"): (
        "Transform model fitted between channels. None uses the method selected by "
        "the context."
    ),
    (StepName.REGISTER_CHANNEL, "execution"): (
        "How experiments are registered: serially, with threads, or with processes."
    ),
    (StepName.REGISTER_CHANNEL, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
    (StepName.BG_SUB, "size"): (
        "Neighborhood size used to estimate the local image background."
    ),
    (StepName.BG_SUB, "sigma"): (
        "Gaussian smoothing sigma used during background estimation."
    ),
    (StepName.BG_SUB, "exclude_channel"): (
        "Channel labels copied without background subtraction."
    ),
    (StepName.BG_SUB, "overwrite"): (
        "Repeat background subtraction even when an up-to-date output exists."
    ),
    (StepName.BG_SUB, "threshold"): (
        "Background-subtraction threshold used by the local background estimator."
    ),
    (StepName.BG_SUB, "statistic"): (
        "Statistic used to summarize the local background: median or mean."
    ),
    (StepName.BG_SUB, "execution"): (
        "How experiments are processed. Serial execution avoids nesting the "
        "background step's frame-level workers."
    ),
    (StepName.BG_SUB, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
    (StepName.BG_SUB, "bg_execution"): (
        "How frames are processed inside background subtraction: sequentially or "
        "with threads."
    ),
    (StepName.BG_SUB, "bg_workers"): (
        "Maximum frame-level workers used by background subtraction. None lets the "
        "background routine choose."
    ),
    (StepName.SEGMENT, "channel_to_segment"): (
        "Channel labels on which Cellpose creates segmentation masks."
    ),
    (StepName.SEGMENT, "do_denoise"): (
        "Use Cellpose denoising when it is supported by the selected model."
    ),
    (StepName.SEGMENT, "nuclear_channel"): (
        "Optional additional channel supplied to Cellpose as nuclear input."
    ),
    (StepName.SEGMENT, "user_settings.model_type"): (
        "Cellpose model type used for segmentation."
    ),
    (StepName.SEGMENT, "user_settings.diameter"): (
        "Expected object diameter in pixels. Set 0 to let Cellpose estimate it."
    ),
    (StepName.SEGMENT, "user_settings.flow_threshold"): (
        "Cellpose flow-error cutoff. Lower values keep fewer masks; higher values "
        "accept more masks."
    ),
    (StepName.SEGMENT, "user_settings.cellprob_threshold"): (
        "Minimum Cellpose cell probability for a pixel to be included in a mask."
    ),
    (StepName.SEGMENT, "user_settings.do_3D"): (
        "Run Cellpose on image volumes instead of processing each Z plane separately."
    ),
    (StepName.SEGMENT, "user_settings.stitch_threshold"): (
        "Threshold for stitching 2D masks across Z planes. It is ignored when "
        "Process in 3D is enabled."
    ),
    (StepName.SEGMENT, "overwrite"): (
        "Repeat segmentation even when an up-to-date mask artifact already exists."
    ),
    (StepName.SEGMENT, "execution"): (
        "How experiments are segmented: serially, with threads, or with processes."
    ),
    (StepName.SEGMENT, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
    (StepName.TRACK, "channel_to_track"): (
        "Segmentation channel labels whose masks are linked into tracks."
    ),
    (StepName.TRACK, "filter_by_length"): (
        "Minimum track length in frames to retain. Set 0 to keep every track."
    ),
    (StepName.TRACK, "overwrite"): (
        "Repeat tracking even when an up-to-date tracked-label artifact already exists."
    ),
    (StepName.TRACK, "backend"): (
        "Tracking implementation used to link segmentation masks across frames."
    ),
    (StepName.TRACK, "trackastra.mode"): (
        "Trackastra linking mode: greedy, greedy without division, or integer "
        "linear programming."
    ),
    (StepName.TRACK, "trackastra.pretrained_model"): (
        "Pretrained Trackastra model used to extract tracking features."
    ),
    (StepName.TRACK, "trackastra.max_distance"): (
        "Maximum distance in pixels for matching objects in consecutive frames."
    ),
    (StepName.TRACK, "execution"): (
        "How experiments are tracked: serially, with threads, or with processes."
    ),
    (StepName.TRACK, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
    (StepName.EXTRACT, "draw_ref_mask"): (
        "Request interactive reference-mask drawing. Existing reference masks are "
        "still used when this is disabled."
    ),
    (StepName.EXTRACT, "expected_ref_masks"): (
        "Number of reference masks to request initially for each experiment."
    ),
    (StepName.EXTRACT, "additional_properties"): (
        "Extra scikit-image region properties to add to the default quantification "
        "measurements. Use None for no extras."
    ),
    (StepName.EXTRACT, "overwrite"): (
        "Repeat quantification even when an up-to-date measurement output exists."
    ),
    (StepName.EXTRACT, "execution"): (
        "How experiments are quantified. Serial execution avoids nesting experiment "
        "and frame process pools."
    ),
    (StepName.EXTRACT, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
    (StepName.EXTRACT, "frame_workers"): (
        "Number of Bioimagequant worker processes used for frames within one "
        "experiment."
    ),
    (StepName.DISTANCE_PROFILE, "expected_ref_masks"): (
        "Number of reference masks to request initially for each experiment. A "
        "reference mask marks the area from which distances are measured; at least "
        "one is required."
    ),
    (StepName.DISTANCE_PROFILE, "draw_roi_mask"): (
        "Request interactive region-of-interest (ROI) mask drawing. An ROI limits "
        "the analysis to its area; without an ROI, the whole image is analysed. "
        "Existing ROI masks are still discovered when drawing is disabled."
    ),
    (StepName.DISTANCE_PROFILE, "expected_roi_masks"): (
        "Number of ROI masks to request initially when drawing is enabled. Each ROI "
        "limits the distance-profile analysis to its selected region."
    ),
    (StepName.DISTANCE_PROFILE, "bin_width"): (
        "Width of each distance bin in pixels."
    ),
    (StepName.DISTANCE_PROFILE, "maximum_bins"): (
        "Maximum number of distance bins to retain. None covers the complete region."
    ),
    (StepName.DISTANCE_PROFILE, "overwrite"): (
        "Repeat distance profiling even when an up-to-date result already exists."
    ),
    (StepName.DISTANCE_PROFILE, "execution"): (
        "How experiments are profiled. Serial execution lets Bioimagequant manage "
        "its frame-level processes."
    ),
    (StepName.DISTANCE_PROFILE, "workers"): (
        "Maximum experiment workers. This setting is ignored during serial execution."
    ),
}


def field_choices(step: StepName, path: str) -> tuple[str, ...] | None:
    name = path.rsplit(".", 1)[-1]
    return STEP_FIELD_CHOICES.get((step, name), FIELD_CHOICES.get(name))


def field_label(path: str) -> str:
    name = path.rsplit(".", 1)[-1]
    return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def field_tooltip(step: StepName, path: str) -> str:
    """Return explanatory help for a GUI settings field."""
    return STEP_FIELD_TOOLTIPS.get((step, path), path)


def runtime_field_tooltip(name: str) -> str:
    """Return explanatory help for a runtime settings field."""
    return RUNTIME_FIELD_TOOLTIPS.get(name, name)


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

    def missing_user_fields(self, step: StepName | None = None) -> list[str]:
        """Describe enabled-step fields for which the user supplied no value."""
        steps = (step,) if step is not None else WORKFLOW_ORDER
        errors: list[str] = []
        for current_step in steps:
            if not self.step_enabled(current_step):
                continue
            for path, message in REQUIRED_USER_FIELDS.get(current_step, ()):
                value = self.field_value(current_step, path)
                missing = value is None
                if isinstance(value, str):
                    missing = value.strip().lower() in {"", "none"}
                elif isinstance(value, Sequence):
                    missing = len(value) == 0
                if missing:
                    errors.append(f"{STEP_LAYOUTS[current_step].title}: {message}")
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

        errors.extend(self.missing_user_fields())

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
