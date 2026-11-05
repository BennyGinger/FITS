"""Translate reviewed numerical rebuild scopes into file previews."""

from collections.abc import Mapping
from dataclasses import replace
from typing import Any
from pathlib import Path

from fits.environment import constant as cst
from fits.gui.file_preview.models import PreviewFile, PreviewGroup, file_stage, file_title
from fits.tasks.analysis.extraction.compartment_export import compartment_export_paths
from fits.workflows.artifacts.branch_masks import is_branch
from fits.workflows.definitions.inputs import configured_profile
from fits.workflows.definitions.models import StepProfile
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState, discover_saved_states
from fits.workflows.file_management.compaction import run_config
from fits.workflows.file_management.rebuild import ProcessingPlan, execution_config, full_rebuild_scope
from fits.workflows.file_management.relocation import PortablePlan
from fits.gui.file_preview.portable import portable_groups


def _existing_files(state: ExperimentState) -> dict[Path, PreviewFile]:
    """
    Include actual saved artifacts and manual drawings as preserved inputs.
    """
    producers = {spec.profile.output_artifact: name for name, spec in REGISTRY.items()}
    files: dict[Path, PreviewFile] = {}
    for kind in state.artifacts:
        path = state.artifact(kind)
        if path is not None and path.is_file():
            step = producers.get(kind)
            files[path] = PreviewFile(path, file_title(path, step), stage=file_stage(path, step), branch=is_branch(path))
    for name in cst.MANAGED_NAMES:
        path = state.workdir / name
        if path.is_file() and path not in files:
            files[path] = PreviewFile(path, file_title(path), stage=file_stage(path))
    for template in (cst.FITS_REFERENCE_TEMPLATE, cst.FITS_ROI_TEMPLATE):
        for path in state.workdir.glob(template.format(label='*')):
            files[path] = PreviewFile(path, file_title(path), branch=True)
    return files


def _planned_inputs(state: ExperimentState, profile: StepProfile, known: dict[str, Path]) -> list[Path]:
    """
    Resolve saved or future paths without requiring planned outputs to exist yet.
    """
    inputs = next(([known[kind]] for kind in (profile.input_artifact, *profile.input_alternatives) if kind in known), [])
    inputs.extend(known[kind] for kind in profile.additional_artifacts if kind in known)
    if profile.step_name == cst.StepName.EXTRACT:
        masks = next((known[kind] for kind in (cst.ARTI_TRACK, cst.ARTI_SEG) if kind in known), None)
        if masks is not None:
            inputs.append(masks)
    if profile.step_name in (cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE):
        inputs.extend(state.workdir.glob(cst.FITS_REFERENCE_TEMPLATE.format(label='*')))
        if profile.step_name == cst.StepName.DISTANCE_PROFILE:
            inputs.extend(state.workdir.glob(cst.FITS_ROI_TEMPLATE.format(label='*')))
    return inputs


def _add_compartments(files: dict[Path, PreviewFile],
                      known: dict[str, Path],
                      edges: set[tuple[Path, Path]],
                      ) -> set[Path]:
    """
    Add enabled compartment exports as children of the active planned full mask.
    """
    source = next((known[kind] for kind in (cst.ARTI_TRACK, cst.ARTI_SEG) if kind in known), None)
    if source is None:
        return set()
    files[source] = replace(files[source], title='Tracked (full)' if cst.ARTI_TRACK in known else 'Segmented (full)')
    outputs = set(compartment_export_paths(source))
    for output in outputs:
        existing = files.get(output)
        files[output] = PreviewFile(output, file_title(output), 'rebuild' if existing is not None else 'create',
                                    'Compartment mask export is enabled in the reviewed settings.',
                                    source=existing.source if existing is not None else None,
                                    stage=file_stage(output, cst.StepName.EXTRACT))
        edges.add((source, output))
    return outputs


def _mark_superseded(files: dict[Path, PreviewFile], known: dict[str, Path], outputs: set[Path]) -> None:
    """
    Mirror full-rebuild cleanup while retaining originals in the reviewed backup.
    """
    kept = {path for kind, path in known.items() if kind not in (cst.ARTI_IMG_COMPACTED, cst.ARTI_MASK_COMPACTED)} | outputs
    for path in list(files):
        if path.name in cst.MANAGED_NAMES and path not in kept:
            files[path] = replace(files[path], action='remove', detail='Superseded after successful rebuilding. The original is retained in the rebuild backup.')


def _processing_group(state: ExperimentState,
                      steps: tuple[str, ...],
                      config: Mapping[str, Any],
                      full_rebuild: bool,
                      existing_files: dict[Path, PreviewFile] | None = None,
                      ) -> PreviewGroup:
    """
    Resolve planned inputs from the same profiles and enabled chain used during execution.
    """
    files = dict(existing_files) if existing_files is not None else _existing_files(state)
    known = {str(kind): path for kind in state.artifacts
             if (path := state.artifact(kind)) is not None and path in files}
    edges: set[tuple[Path, Path]] = set()
    outputs: set[Path] = set()
    geometry_source: Path | None = None
    for step in steps:
        profile = configured_profile(REGISTRY[step].profile, config)
        output = state.workdir / profile.output_name
        inputs = _planned_inputs(state, profile, known)
        existing = files.get(output)
        files[output] = PreviewFile(output, file_title(output, step), 'rebuild' if existing is not None else 'create',
                                    'Recreated from the reviewed processing inputs. Existing results are backed up first.',
                                    source=existing.source if existing is not None else None,
                                    stage=file_stage(output, step))
        edges.update((source, output) for source in inputs if source != output)
        outputs.add(output)
        known[profile.output_artifact] = output
        if profile.output_artifact in cst.IMAGE_STAGE_ARTIFACTS:
            known[cst.ARTI_IMG] = output
        if step in (cst.StepName.CONVERT, cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME):
            geometry_source = output
    registration = any(step in steps for step in (cst.StepName.REGISTER_CHANNEL, cst.StepName.REGISTER_TIME))
    drawings = [path for path in files if is_branch(path)]
    for path in drawings:
        files[path] = replace(files[path], action='review' if registration else 'keep',
                               detail='Drawing pixels are preserved. Review alignment after registration changes.' if registration else
                                      'Drawing pixels are preserved; intensity changes do not change geometry.')
    geometry_edges = tuple((geometry_source, path) for path in drawings) if geometry_source is not None else ()
    params = config.get(cst.StepName.EXTRACT, {}).get('params', {})
    if cst.StepName.EXTRACT in steps and params.get('compartments') and params.get('save_compartment_masks'):
        outputs.update(_add_compartments(files, known, edges))
    if full_rebuild:
        _mark_superseded(files, known, outputs)
    return PreviewGroup(state.workdir, tuple(files.values()), tuple(sorted(edges)), geometry_edges, planned_edges=True)


def processing_groups(plan: ProcessingPlan) -> tuple[PreviewGroup, ...]:
    """
    Build previews for the exact experiments and steps in an accepted processing scope.
    """
    states = {state.workdir: state for state in discover_saved_states(plan.root)}
    config = execution_config(run_config(plan.root), plan)
    return tuple(_processing_group(states[folder], steps, config, plan.fully_rebuilds(folder)) for folder, steps in plan.scope.items())


def migration_rebuild_groups(plan: PortablePlan) -> tuple[PreviewGroup, ...]:
    """
    Project full reconstruction onto migrated destinations without moving or rebuilding files.
    """
    migrated = {group.directory: {item.path: item for item in group.files} for group in portable_groups(plan)}
    available = {path for files in migrated.values() for path in files}
    config = run_config(plan.root)
    scope = full_rebuild_scope(plan.states, config, available=available)
    selected = {step for steps in scope.values() for step in steps}
    enabled = {**config, **{str(step): {**config.get(step, {}), 'enabled': step in selected} for step in cst.WORKFLOW_ORDER}}
    return tuple(_processing_group(state, scope[state.workdir], enabled, True, migrated[state.workdir]) for state in plan.states)
