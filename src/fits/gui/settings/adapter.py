from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from copy import deepcopy
from pathlib import Path
from typing import Any

import tomlkit
from pydantic import ValidationError
from tomlkit import TOMLDocument
from fits_io.metadata.channel_colors import conversion_channel_labels

from fits.environment.constant import WORKFLOW_ORDER, StepName
from fits.workflows.definitions.registry import REGISTRY
from fits.settings.loader import SAVED_SETTINGS_NAME, normalize_registration_algorithms, resolve_step_params, run_settings_path, write_settings
from fits.settings.models import SegmentSettings
from fits.gui.settings.layouts import STEP_LAYOUTS


TEMPLATE_PATH = Path(__file__).parents[2] / "settings" / "template_settings.toml"


FIELD_LABELS: dict[str, str] = {
    "unlock_all_tabs": "Unlock all phase tabs",
    "draw_ref_mask": "Draw reference masks",
    "expected_ref_masks": "Expected reference masks",
    "compartments": "Measure cell compartments",
    "save_compartment_masks": "Save compartment masks",
    "membrane_thickness": "Membrane thickness (pixels)",
    "dilation_radius": "Cell expansion (pixels)",
    "draw_roi_mask": "Draw ROI masks",
    "expected_roi_masks": "Expected ROI masks",
    "bg_execution": "Frame execution",
    "bg_workers": "Frame workers",
    "cellprob_threshold": "Cell probability threshold (-6 to 6)",
    "stitch_threshold": "Stitch threshold (0–1)",
    "threshold": "Threshold (0–1)",
    "do_3D": "Process in 3D",
    "do_denoise": "Denoise",
    "export_channels": "Export channels",
    "shape_similarity": "Shape similarity",
    "minimum_appearances": "Minimum appearances",
    "extrapolate_start": "Complete track start",
    "extrapolate_end": "Complete track end",
    "fit_channel": "Fitting channel (optional)",
    "reference_channel": "Reference channel (required)",
    "backend": "Algorithm",
    "size": "Size (>=2)",
    "flow_threshold": "Flow threshold (>=0)",
    "frame_workers": "Frame workers",
    "nuclear_channel": "Nuclear channel",
    "reference_frame": "Reference frame",
    "reference_strategy": "Reference strategy",
    "bin_width": "Bin width (pixels)",
    "maximum_bins": "Maximum number of bins",
    "z_projection": "Z projection",
}

FIELD_PATH_LABELS: dict[str, str] = {
    "user_settings.pretrained_model": "Model type",
    "postprocess.enabled": "Repair masks and tracks (optional, for stationary cells only)",
    "postprocess.shape_similarity": "Minimum mask consistency (0–1)",
    "postprocess.minimum_appearances": "Minimum reliable frames",
    "postprocess.extrapolate_start": "Extend masks to the first frame",
    "postprocess.extrapolate_end": "Extend masks to the last frame",
}


FIELD_HINTS: dict[str, str] = {
    "channel_labels": ("ND2/TIFF colors are detected automatically. Enter optional labels in source order; "
                       "blank cells use color names, then C1, C2, etc."),
    "export_channels": "Select which channels to convert/export; multiple selections are allowed.",
    "exclude_channel": "Select channels to leave unchanged; None excludes no channels.",
    "context": "Choose a motion/alignment preset; hover for an explanation of each context.",
    "fit_channel": "Optional: None estimates motion using the first image channel.",
    "reference_channel": "Choose the fixed channel that the other channels align to.",
    "user_settings.diameter": "Expected cell diameter in pixels; 0 uses automatic sizing.",
    "user_settings.flow_threshold": "Higher accepts more masks; 0 disables flow-error filtering.",
    "user_settings.cellprob_threshold": "Lower finds more/larger masks; higher suppresses dim detections.",
    "user_settings.stitch_threshold": "0 disables stitching; higher requires closer overlap between Z planes.",
    "user_settings.do_3D": "Segment the full Z volume; requires multiple Z planes.",
    "algorithm": "Override the preset's algorithm, or leave None to follow the context.",
    "method": "Override the preset's transform, or leave None to follow the context.",
    "sigma": "Larger values blur over a wider area; 0 disables smoothing.",
    "threshold": "Lower values select fewer pixels as background.",
    "workers": "Parallel experiments; None selects automatically. Ignored in serial mode.",
    "frame_workers": "Worker processes for frames within one experiment.",
    "bg_workers": "Parallel background-subtraction frames; None selects automatically.",
    "maximum_bins": "Limit the profile length; None keeps all distance bins.",
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
        "Optional FITS metadata root. Leave blank to create .fits/logs and "
        ".fits/reports inside the run directory."
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
    (StepName.REGISTER_TIME, "algorithm"): ("None", "scikit", "pystackreg", "cv2"),
    (StepName.REGISTER_CHANNEL, "algorithm"): (
        "None",
        "scikit",
        "pystackreg",
        "cv2",
    ),
    (StepName.TRACK, "backend"): ("trackastra",),
}

REQUIRED_USER_FIELDS: dict[StepName, tuple[tuple[str, str], ...]] = {
    StepName.CONVERT: (
        ("export_channels", "Select at least one channel to convert/export."),
    ),
    StepName.REGISTER_CHANNEL: (
        ("reference_channel", "Choose a reference channel (reference_channel)."),
    ),
    StepName.TRACK: (
        ("channel_to_track", "Choose at least one channel to track (channel_to_track)."),
    ),
}

STEP_FIELD_TOOLTIPS: dict[tuple[StepName, str], str] = {
    (StepName.SEGMENT, "user_settings.pretrained_model"): (
        "Built-in model available in the installed Cellpose version."
    ),
    (StepName.CONVERT, "channel_labels"): (
        "Enter optional labels in source-channel order. Blank labels use the detected source color, "
        "or C1, C2, etc. when unavailable. Expected colors come from ND2 metadata or ImageJ TIFF LUTs. "
        "Converted-file LUTs follow labels, including any user overrides."
    ),
    (StepName.CONVERT, "export_channels"): (
        "Select which source channels to convert/export. Multiple channels may be selected; all source channels are selected by default."
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
        "Choose the motion to correct:\nlinear_drift: X/Y shifts (translation).\nrotational_drift: translation and rotation (rigid-body).\ncomplex_drift: translation and rotation, plus scaling/shear (affine)."
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
    (StepName.REGISTER_TIME, "algorithm"): (
        "Registration algorithm. None uses the algorithm selected by the context."
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
        "Choose the alignment between channels:\nchannel_shift: X/Y offset only (translation).\nchannel_shift_dual_cam: offset and rotation, for example between cameras (rigid-body).\nchannel_shift_complex: offset and rotation, plus scaling/shear (affine)."
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
    (StepName.REGISTER_CHANNEL, "algorithm"): (
        "Registration algorithm. None uses the algorithm selected by the context."
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
    (StepName.SEGMENT, "channel"): (
        "Target channel on which Cellpose creates segmentation masks."
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
        "Cellpose flow-error cutoff. Higher values accept more masks. This is squared error, so values above 1 are meaningful. 0 disables filtering. Negative values also bypass the filter; use 0 instead. Ignored during native 3D segmentation."
    ),
    (StepName.SEGMENT, "user_settings.cellprob_threshold"): (
        "Minimum Cellpose cell probability for a pixel to be included in a mask. "
        "Cellpose suggests a working range of -6 to 6; this is not a hard limit."
    ),
    (StepName.SEGMENT, "user_settings.do_3D"): (
        "Run Cellpose on image volumes instead of processing each Z plane separately."
    ),
    (StepName.SEGMENT, "user_settings.stitch_threshold"): (
        "Minimum overlap (0–1) for stitching 2D masks across Z planes. "
        "0 disables stitching. It is ignored when "
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
    (StepName.TRACK, "postprocess.enabled"): (
        "Repair masks for cells that remain in approximately the same position. "
        "Leave off for migrating cells."
    ),
    (StepName.TRACK, "postprocess.shape_similarity"): (
        "Minimum Dice similarity between an observed mask and its track's temporal "
        "consensus, expressed as a proportion from 0 to 1. "
        "Also controls identity matching and how much of a reconstructed mask must "
        "survive collisions with other cells. Higher values reject more doubtful masks; "
        "identity matching and reconstruction always require at least 50% IoU."
    ),
    (StepName.TRACK, "postprocess.minimum_appearances"): (
        "Number of consistent observations needed to keep a track. "
        "Tracks with fewer reliable frames are removed."
    ),
    (StepName.TRACK, "postprocess.extrapolate_start"): (
        "Copy the first valid mask into preceding frames."
    ),
    (StepName.TRACK, "postprocess.extrapolate_end"): (
        "Copy the last valid mask into following frames."
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
    (StepName.EXTRACT, "compartments"): (
        "Measure full cells, membrane (mb) and cytoplasm (cyto). All compartments "
        "share the full-cell centroid and cell identity."
    ),
    (StepName.EXTRACT, "save_compartment_masks"): (
        "Save labelled mb/cyto TIFFs alongside the source mask. Compaction removes "
        "them; rebuilding regenerates them when this option remains enabled."
    ),
    (StepName.EXTRACT, "membrane_thickness"): (
        "Membrane thickness in pixels. An eroded-away cytoplasm retains the cell "
        "pixel nearest the full-cell centroid."
    ),
    (StepName.EXTRACT, "dilation_radius"): (
        "Expand labels without overlap before compartment extraction. The expanded "
        "cell defines full and its centroid. Zero disables expansion."
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
    if path in FIELD_PATH_LABELS:
        return FIELD_PATH_LABELS[path]
    name = path.rsplit(".", 1)[-1]
    return FIELD_LABELS.get(name, name.replace("_", " ").capitalize())


def field_tooltip(step: StepName, path: str) -> str:
    """Return explanatory help for a GUI settings field."""
    if path == "overwrite":
        return "Recompute this step even if its output already exists. " + STEP_FIELD_TOOLTIPS.get((step, path), "")
    return STEP_FIELD_TOOLTIPS.get((step, path), path)


def field_hint(step: StepName, path: str) -> str:
    """
    Return a practical inline hint while leaving complete help in the tooltip.
    """
    return FIELD_HINTS.get(path, field_tooltip(step, path).split(". ", 1)[0].rstrip(".") + ".")


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
        self.saved_image_channels: list[str] = []
        self.raw_channel_count: int | None = None
        self.raw_channel_colors: list[str | None] | None = None

    @staticmethod
    def _parse(path: Path) -> TOMLDocument:
        """
        Read a settings document using the current registration field names.
        """
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
        normalize_registration_algorithms(document)
        return document

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
        """Validate GUI drafts; missing segmentation targets are checked separately."""
        errors: dict[StepName, ValidationError] = {}
        for step in WORKFLOW_ORDER:
            params: Any = resolve_step_params(step, self.as_mapping()[step])
            if hasattr(params, "unwrap"):
                params = params.unwrap()
            if step == StepName.SEGMENT:
                # Unassigned sections are valid while editing/saving settings.
                # missing_user_fields blocks enabled segmentation at run time.
                params["channels"] = [entry for entry in params.get("channels", [])
                                      if entry.get("channel", "").strip()]
            try:
                REGISTRY[step].model_validate(params)
            except ValidationError as error:
                errors[step] = error
        return errors

    def source_channel_labels(self) -> list[str]:
        """
        Resolve user labels and color defaults in their original channel order.
        """
        value = self.field_value(StepName.CONVERT, "channel_labels")
        entries = value.split(",") if isinstance(value, str) else value or []
        if self.raw_channel_count is not None:
            return conversion_channel_labels(entries, self.raw_channel_count, self.raw_channel_colors)
        return list(dict.fromkeys(str(label).strip() for label in entries if str(label).strip()))

    def exported_channel_labels(self) -> list[str]:
        """
        Return the image channels available to registration and segmentation.
        """
        channels = self.source_channel_labels() or self.saved_image_channels
        selected = self.field_value(StepName.CONVERT, "export_channels")
        if selected == "all":
            return list(channels)
        requested = [selected] if isinstance(selected, str) else selected
        return [channel for channel in channels if channel in requested]

    def segment_channels(self) -> list[dict[str, Any]]:
        return deepcopy(self.as_mapping()["segment"].get("channels", []))

    def set_segment_channels(self, entries: list[dict[str, Any]]) -> None:
        def toml_value(value):
            if value is None:
                return "None"
            if isinstance(value, dict):
                return {key: toml_value(child) for key, child in value.items()}
            return value
        tables = tomlkit.aot()
        for entry in entries:
            tables.append(tomlkit.item(toml_value(entry)))
        self.document["segment"]["channels"] = tables

    def segmentation_settings(self, *, for_tuning: bool = False) -> SegmentSettings:
        config = self.as_mapping()["segment"]
        if for_tuning:
            config["channels"] = [entry for entry in config.get("channels", [])
                                  if entry.get("channel", "").strip()]
        return SegmentSettings.model_validate(
            resolve_step_params("segment", config))

    def missing_user_fields(self, step: StepName | None = None) -> list[str]:
        """Describe enabled-step fields for which the user supplied no value."""
        steps = (step,) if step is not None else WORKFLOW_ORDER
        errors: list[str] = []
        for current_step in steps:
            if not self.step_enabled(current_step):
                continue
            if current_step == StepName.SEGMENT:
                entries = self.segment_channels()
                if not entries or any(not entry.get("channel", "").strip() for entry in entries):
                    errors.append("Segmentation: Choose a target channel for every section.")
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

    def validate_for_run(self, steps: Sequence[StepName] | None = None) -> list[str]:
        errors: list[str] = []
        run_dir = self.run_dir.strip()
        if not run_dir:
            errors.append("Select a run directory.")
        elif not Path(run_dir).expanduser().is_dir():
            errors.append("The selected run directory does not exist.")
        if not self.user_name.strip():
            errors.append("Enter a user name.")

        selected = steps if steps is not None else WORKFLOW_ORDER
        for step in selected:
            errors.extend(self.missing_user_fields(step))

        for step, error in self.validate_steps().items():
            if step in selected and self.step_enabled(step):
                errors.append(f"{STEP_LAYOUTS[step].title}: {error.errors()[0]['msg']}")
        return errors

    def save(self, path: str | Path) -> Path:
        """
        Save current settings, backing up a changed canonical run snapshot.
        """
        destination = Path(path).expanduser().resolve()
        write_settings(destination, tomlkit.dumps(self.document),
                       backup=destination == run_settings_path(Path(self.run_dir)).resolve(),
                       )
        self.source_path = destination
        return destination

    def protocol_document(self) -> TOMLDocument:
        """
        Copy reusable settings without run identity, output paths or overwrite requests.
        """
        document = deepcopy(self.document)
        for key in ("user_name", "run_dir", "optimize"):
            document.pop(key, None)
        document["runtime"].pop("log_dir", None)
        for step in WORKFLOW_ORDER:
            document[step]["params"]["overwrite"] = False
        return document

    def protocol_candidate(self, path: Path) -> SettingsAdapter:
        """
        Load a separate draft preserving the current identity and log destination.
        """
        candidate = SettingsAdapter(self.template_path)
        candidate.load(path)
        candidate.document = candidate.protocol_document()
        candidate.run_dir = self.run_dir
        candidate.user_name = self.user_name
        candidate.set_runtime_value("log_dir", self.runtime_value("log_dir"))
        candidate.saved_image_channels = list(self.saved_image_channels)
        candidate.raw_channel_count = self.raw_channel_count
        candidate.raw_channel_colors = self.raw_channel_colors
        candidate.source_path = self.source_path
        return candidate

    def save_to_run_dir(self) -> Path:
        run_dir = Path(self.run_dir).expanduser().resolve()
        return self.save(run_settings_path(run_dir))

    def as_mapping(self) -> Mapping[str, Any]:
        return self.document.unwrap()
