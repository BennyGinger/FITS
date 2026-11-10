"""Resolve step inputs once for execution, provenance and preflight checking."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from fisch.environment import constant as cst
from fisch.workflows.definitions.models import StepProfile
from fisch.workflows.experiments import ExperimentState


IMAGE_OUTPUTS: dict[cst.StepName, cst.ArtifactType] = {
    cst.StepName.CONVERT: cst.ARTI_IMG_RAW,
    cst.StepName.REGISTER_CHANNEL: cst.ARTI_IMG_CHANNEL,
    cst.StepName.REGISTER_TIME: cst.ARTI_IMG_TIME,
    cst.StepName.BG_SUB: cst.ARTI_IMG_BGSUB,
}


def quantification_mask_kind(config: Mapping[str, Any]) -> cst.ArtifactType:
    """
    Select the latest included mask producer before looking for any saved files.
    """
    if config.get(cst.StepName.TRACK, {}).get("enabled"):
        return cst.ARTI_TRACK
    if config.get(cst.StepName.SEGMENT, {}).get("enabled"):
        return cst.ARTI_SEG
    raise ValueError("Quantification requires Segmentation or Tracking to be included in the workflow.")


def configured_profile(profile: StepProfile, config: Mapping[str, Any]) -> StepProfile:
    """
    Disabled preprocessing stages are bypassed, even when old files exist.
    """
    image = cst.ARTI_IMG_RAW
    for step in cst.WORKFLOW_ORDER:
        if step == profile.step_name:
            break
        if step in IMAGE_OUTPUTS and config.get(step, {}).get("enabled", False):
            image = IMAGE_OUTPUTS[step]
    if profile.step_name == cst.StepName.EXTRACT:
        return replace(profile, input_artifact=image, input_alternatives=(),
                       additional_artifacts=(quantification_mask_kind(config),),
                       use_tracking_edits=bool(config.get(cst.StepName.EDIT_TRACK, {}).get("enabled")))
    if profile.step_name in (*IMAGE_OUTPUTS.keys(), cst.StepName.SEGMENT) and profile.step_name != cst.StepName.CONVERT:
        return replace(profile, input_artifact=image, input_alternatives=())
    if profile.input_artifact == cst.ARTI_IMG:
        return replace(profile, input_artifact=image, input_alternatives=())
    if cst.ARTI_IMG in profile.additional_artifacts:
        return replace(profile, additional_artifacts=tuple(
            image if kind == cst.ARTI_IMG else kind for kind in profile.additional_artifacts))
    return profile


def resolve_quantification_mask(state: ExperimentState, profile: StepProfile | None = None) -> tuple[str, Path]:
    """
    Require the configured mask source, with no fallback to bypassed outputs.
    """
    kinds: tuple[cst.ArtifactType, ...] = tuple(kind for kind in profile.additional_artifacts if kind in (cst.ARTI_TRACK, cst.ARTI_SEG)) if profile else ()
    if (kinds == (cst.ARTI_TRACK,) and profile is not None and profile.use_tracking_edits
            and cst.StepName.EDIT_TRACK not in state.completed_steps):
        raise ValueError(f"Quantification requires an accepted Edit tracking result for {state.experiment_id}.")
    fallback: tuple[cst.ArtifactType, ...] = (cst.ARTI_TRACK, cst.ARTI_SEG)
    for kind in kinds or fallback:
        path = state.artifact(kind)
        if (kind == cst.ARTI_TRACK and profile is not None and not profile.use_tracking_edits
                and path is not None and (path.name in (cst.MASK_TRACK_EDITED, cst.MASK_TRACK_EDITED_FILTERED)
                                          or (state.compacted and cst.StepName.EDIT_TRACK in state.completed_steps))):
            path = next((state.workdir / name for name in cst.UNEDITED_TRACKING_NAMES
                         if (state.workdir / name).is_file()), state.workdir / cst.MASK_TRACK)
        if path is not None and path.is_file():
            return kind, path
    expected = kinds[0] if kinds else "tracking or segmentation"
    raise ValueError(f"Quantification requires the selected {expected} mask for {state.experiment_id}.")


def resolve_inputs(state: ExperimentState, profile: StepProfile) -> dict[str, Path]:
    """
    Resolve required images, object masks and analysis branches from saved state.
    """
    paths: dict[str, Path] = {}
    for kind in (profile.input_artifact, *profile.input_alternatives):
        path = state.artifact(kind)
        if path is not None and path.is_file():
            paths[kind] = path
            break
    if not paths:
        raise ValueError(f"{profile.step_name}: missing {profile.input_artifact} input for {state.experiment_id}")
    for kind in profile.additional_artifacts:
        if profile.step_name == cst.StepName.EXTRACT and kind in (cst.ARTI_TRACK, cst.ARTI_SEG):
            continue
        path = state.artifact(kind)
        if path is None or not path.is_file():
            raise ValueError(f"{profile.step_name}: missing {kind} input for {state.experiment_id}")
        paths[kind] = path
    if profile.step_name == cst.StepName.EXTRACT:
        kind, path = resolve_quantification_mask(state, profile)
        paths[kind] = path
    if profile.step_name in (cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE):
        for path in sorted(state.workdir.glob(cst.REFERENCE_TEMPLATE.format(label="*"))):
            paths[str(path)] = path
        if profile.step_name == cst.StepName.DISTANCE_PROFILE:
            for path in sorted(state.workdir.glob(cst.ROI_TEMPLATE.format(label="*"))):
                paths[str(path)] = path
    return paths
