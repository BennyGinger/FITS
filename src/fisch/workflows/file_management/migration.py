"""Adopt existing results without rerunning numerical processing."""

from __future__ import annotations

from collections.abc import Sequence, Mapping
from typing import Any
from scope_io.metadata.models import ImageMetadata
from fisch.workflows.experiments import ExperimentState
from fisch.workflows.definitions.models import StepProfile
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from fisch.workflows.artifacts.provenance import compatible, produced_metadata, read_metadata, input_references
from fisch.environment import constant as cst
from fisch.environment import naming
from fisch.workflows.metadata import PipelineMetadata
from fisch.workflows.metadata._values import utc_now
from fisch.workflows.definitions.inputs import IMAGE_OUTPUTS
from fisch.workflows.artifacts.branch_masks import is_branch


def prepare_state(state: ExperimentState) -> ExperimentState:
    """
    Bind a single historical final array to the stage it actually represents.
    """
    image = state.artifact(cst.ARTI_IMG)
    if image is None or not image.is_file():
        image = next((state.workdir / name for name in cst.IMAGE_NAMES
                      if (state.workdir / name).is_file()), None)
    if image is None:
        raise ValueError(f'Cannot migrate {state.workdir}: no saved image is available.')

    recorded = set(state.completed_steps) | set(read_metadata(image).custom_metadata.get('steps', {}))
    last = next((step for step in reversed(cst.WORKFLOW_ORDER)
                 if step in IMAGE_OUTPUTS and step in recorded), cst.StepName.CONVERT)
    artifacts = dict(state.artifacts)
    artifacts[cst.ARTI_IMG] = state._to_relative(state.workdir, image)
    # A final legacy array is one checkpoint, never several invented intermediates.
    if naming.canonical_name(image.name) == cst.ARRAY_NAME and not state.compacted:
        for kind in cst.IMAGE_STAGE_ARTIFACTS:
            if state.artifact(kind) == image:
                artifacts.pop(kind, None)
        artifacts[IMAGE_OUTPUTS[last]] = artifacts[cst.ARTI_IMG]
        checkpoint = str(last)
    else:
        checkpoint = state.migration_checkpoint
    mask_names: tuple[tuple[cst.ArtifactType, tuple[str, ...]], ...] = ((cst.ARTI_SEG, cst.SEGMENTATION_NAMES), (cst.ARTI_TRACK, cst.TRACKING_NAMES))
    for kind, names in mask_names:
        current = state.artifact(kind)
        if current is None or not current.is_file():
            found = next((state.workdir / name for name in reversed(names)
                          if (state.workdir / name).is_file()), None)
            if found is not None:
                artifacts[kind] = state._to_relative(state.workdir, found)
    data = state.metadata_dump
    data = produced_metadata(data)
    completed = list(state.completed_steps)
    for step in cst.WORKFLOW_ORDER:
        if step in IMAGE_OUTPUTS and step in recorded and step not in completed:
            completed.append(step)
    if last not in completed:
        completed.append(last)
    if cst.StepName.CONVERT not in completed:
        completed.insert(0, cst.StepName.CONVERT)
    output_steps: tuple[tuple[cst.StepName, cst.ArtifactType], ...] = ((cst.StepName.SEGMENT, cst.ARTI_SEG), (cst.StepName.TRACK, cst.ARTI_TRACK),
                       (cst.StepName.EXTRACT, cst.ARTI_QUANTI), (cst.StepName.DISTANCE_PROFILE, cst.ARTI_DIST_PROF))
    for step, kind in output_steps:
        path = artifacts.get(kind)
        if path is not None and (state.workdir / path).is_file() and step not in completed:
            completed.append(step)
    return replace(state,
                   artifacts=artifacts,
                   metadata=PipelineMetadata.from_dict(data),
                   completed_steps=tuple(completed),
                   migration_checkpoint=checkpoint,
                   )


def migrate_payload(payload: ImageMetadata, *, inputs: Sequence[Mapping[str, Any]] = ()) -> ImageMetadata:
    """
    Record an accepted baseline; preserve original versions and step times.
    """
    if compatible(payload):
        return payload
    custom = deepcopy(dict(payload.custom_metadata))
    has_lineage = bool(payload.artifact.created_at and isinstance(payload.artifact.derived_from, list))
    custom['migration'] = {
        'adopted_at': utc_now(),
        'original_pipeline_meta': deepcopy(custom.get('pipeline_meta', {})),
        'original_artifact': deepcopy(payload.artifact.to_dict()),
        'historical_lineage': 'preserved' if has_lineage else 'unavailable',
        'revision_origin': 'existing' if payload.artifact.created_at else 'migration',
    }
    custom = produced_metadata(custom)
    revision = payload if payload.artifact.created_at else payload.new_revision()
    return replace(revision.with_custom_metadata(custom), artifact=replace(revision.artifact,
                                                                          derived_from=revision.artifact.derived_from if has_lineage else [dict(item) for item in inputs],
                                                                          ))


def checkpoint_complete(state: ExperimentState, profile: StepProfile, overwrite: bool = False) -> bool:
    """
    Earlier stages are represented by the checkpoint unless explicitly overwritten.
    """
    checkpoint = state.migration_checkpoint
    if checkpoint is None or overwrite or profile.step_name not in cst.WORKFLOW_ORDER:
        return False
    if profile.step_name not in IMAGE_OUTPUTS:
        return False
    path = state.artifact(IMAGE_OUTPUTS[cst.StepName(checkpoint)])
    return bool(path is not None and path.is_file() and
                cst.WORKFLOW_ORDER.index(profile.step_name) <= cst.WORKFLOW_ORDER.index(checkpoint))


def accepted_inputs(path: Path, state: ExperimentState) -> list[dict[str, Any]]:
    """
    Accept dependencies that exist now; never invent absent historical inputs.
    """
    if is_branch(path):
        return []
    if path.name in cst.IMAGE_NAMES:
        stage = next((step for step, kind in IMAGE_OUTPUTS.items()
                      if state.artifact(kind) == path), None)
        if stage is None or stage == cst.StepName.CONVERT:
            return []
        previous = [state.artifact(IMAGE_OUTPUTS[step]) for step in cst.WORKFLOW_ORDER[:cst.WORKFLOW_ORDER.index(stage)]
                    if step in IMAGE_OUTPUTS]
        parent = next((item for item in reversed(previous) if item is not None and item.is_file()), None)
        return input_references([parent], path.parent) if parent is not None else []
    paths = [state.artifact(cst.ARTI_IMG)]
    if path.name in cst.TRACKING_NAMES:
        paths.append(state.artifact(cst.ARTI_SEG))
    elif path.suffix == '.parquet':
        paths.append(state.artifact(cst.ARTI_TRACK) or state.artifact(cst.ARTI_SEG))
        for template in (cst.REFERENCE_TEMPLATE, cst.ROI_TEMPLATE):
            paths.extend(state.workdir.glob(template.format(label='*')))
    return input_references([item for item in paths if item is not None and item.is_file() and item != path],
                            path.parent,
                            )
