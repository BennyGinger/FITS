"""Resolve step inputs once for execution, provenance and preflight checking."""

from __future__ import annotations

from dataclasses import replace
from collections.abc import Mapping
from pathlib import Path
from typing import Any
from fits.environment import constant as cst
from fits.workflows.definitions.models import StepProfile
from fits.workflows.experiments import ExperimentState


IMAGE_OUTPUTS: dict[cst.StepName, cst.ArtifactType] = {
    cst.StepName.CONVERT: cst.ARTI_IMG_RAW,
    cst.StepName.REGISTER_CHANNEL: cst.ARTI_IMG_CHANNEL,
    cst.StepName.REGISTER_TIME: cst.ARTI_IMG_TIME,
    cst.StepName.BG_SUB: cst.ARTI_IMG_BGSUB,
}


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
    if profile.step_name in (*IMAGE_OUTPUTS.keys(), cst.StepName.SEGMENT) and profile.step_name != cst.StepName.CONVERT:
        return replace(profile, input_artifact=image, input_alternatives=())
    if profile.input_artifact == cst.ARTI_IMG:
        return replace(profile, input_artifact=image, input_alternatives=())
    if cst.ARTI_IMG in profile.additional_artifacts:
        return replace(profile, additional_artifacts=tuple(
            image if kind == cst.ARTI_IMG else kind for kind in profile.additional_artifacts))
    return profile


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
        path = state.artifact(kind)
        if path is None or not path.is_file():
            raise ValueError(f"{profile.step_name}: missing {kind} input for {state.experiment_id}")
        paths[kind] = path
    if profile.step_name == cst.StepName.EXTRACT:
        for kind in (cst.ARTI_TRACK, cst.ARTI_SEG):
            path = state.artifact(kind)
            if path is not None and path.is_file():
                paths[kind] = path
                break
        else:
            raise ValueError("Quantification requires a tracking or segmentation mask.")
    if profile.step_name in (cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE):
        for path in sorted(state.workdir.glob(cst.FITS_REFERENCE_TEMPLATE.format(label="*"))):
            paths[str(path)] = path
        if profile.step_name == cst.StepName.DISTANCE_PROFILE:
            for path in sorted(state.workdir.glob(cst.FITS_ROI_TEMPLATE.format(label="*"))):
                paths[str(path)] = path
    return paths
