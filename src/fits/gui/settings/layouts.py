"""Declarative field layouts for workflow-step settings."""

from dataclasses import dataclass

from fits.environment.constant import StepName


@dataclass(frozen=True)
class StepLayout:
    title: str
    basic: tuple[str, ...]
    advanced: tuple[str, ...]


STEP_LAYOUTS: dict[StepName, StepLayout] = {
    StepName.CONVERT: StepLayout(title="Convert",
                                 basic=("channel_labels", "export_channels",
                                        "z_projection", "overwrite",),
                                 advanced=("compression", "execution", "workers",),),
    StepName.REGISTER_TIME: StepLayout(title="Register time",
                                       basic=("context", "reference_strategy",
                                              "fit_channel", "overwrite",),
                                       advanced=("backend", "method", "execution",
                                                 "workers",),),
    StepName.REGISTER_CHANNEL: StepLayout(title="Register channels",
                                          basic=("context", "reference_channel",
                                                 "exclude_channel", "reference_frame",
                                                 "overwrite",),
                                          advanced=("backend", "method", "execution",
                                                    "workers",),),
    StepName.BG_SUB: StepLayout(title="Background subtraction",
                                basic=("size", "sigma", "exclude_channel", "overwrite",),
                                advanced=("threshold", "statistic", "execution", "workers",
                                          "bg_execution", "bg_workers",),),
    StepName.SEGMENT: StepLayout(title="Segmentation",
                                 basic=("overwrite",),
                                 advanced=("execution", "workers",),),
    StepName.TRACK: StepLayout(title="Tracking",
                               basic=("channel_to_track", "postprocess.enabled",
                                      "postprocess.shape_similarity",
                                      "postprocess.minimum_appearances",
                                      "postprocess.extrapolate_start",
                                      "postprocess.extrapolate_end", "overwrite",),
                               advanced=("backend", "trackastra.mode",
                                         "trackastra.pretrained_model",
                                         "trackastra.max_distance", "execution", "workers",),),
    StepName.EDIT_TRACK: StepLayout(title="Edit tracking",
                                    basic=("overwrite",),
                                    advanced=("execution", "workers",),),
    StepName.EXTRACT: StepLayout(title="Quantification",
                                 basic=("draw_ref_mask", "expected_ref_masks",
                                        "additional_properties", "overwrite",),
                                 advanced=("execution", "workers", "frame_workers",),),
    StepName.DISTANCE_PROFILE: StepLayout(title="Distance profile",
                                          basic=("expected_ref_masks", "draw_roi_mask",
                                                 "expected_roi_masks", "bin_width",
                                                 "maximum_bins", "overwrite",),
                                          advanced=("execution", "workers",),),
}
