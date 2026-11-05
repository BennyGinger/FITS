"""Inspect recorded artifact inputs and propagate conflicts in workflow order."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

from fits.environment import constant as cst
from fits.environment.paths import is_internal_path
from fits.workflows.artifacts.branch_masks import geometry, is_branch
from fits.workflows.artifacts.provenance import compatible, read_metadata
from fits.workflows.checks.decisions import apply_decision
from fits.workflows.checks.models import ArtifactRecord, PreflightReport
from fits.workflows.checks.settings import settings_problem
from fits.workflows.checks.planning import downstream_steps, overwrite_steps, rebuild_sources
from fits.workflows.definitions.inputs import configured_profile, resolve_inputs
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState, discover_saved_states
from fits.workflows.file_management.migration import checkpoint_complete
from fits_io.metadata.models import FitsIOMeta


def inspect_run(root: Path, config: Mapping[str, Any], *, for_execution: bool = True) -> PreflightReport:
    """
    Inspect saved artifacts and describe conflicts and possible rebuilds.

    This is read-only: no files or settings are changed. Set ``for_execution``
    to False for GUI loading, where requested overwrites and intentionally absent
    compacted intermediates should not produce execution warnings.
    """
    states = discover_saved_states(root)
    states_by_directory: dict[Path, ExperimentState] = {}
    for state in states:
        states_by_directory.setdefault(state.workdir, state)

    records = _collect_records(root, states, states_by_directory, for_execution=for_execution)
    records.extend(_missing_input_records(states, config, for_execution=for_execution))
    records = _propagate_conflicts(records, states_by_directory, config, for_execution=for_execution)
    return _build_report(records, states, config, for_execution=for_execution)


def _collect_records(root: Path,
                     states: Sequence[ExperimentState],
                     states_by_directory: Mapping[Path, ExperimentState],
                     *,
                     for_execution: bool,
                     ) -> list[ArtifactRecord]:
    """
    Collect workflow outputs, then remaining managed files, without duplicates.
    """
    records: list[ArtifactRecord] = []
    seen: set[Path] = set()
    for state in states:
        for path, step, problem in _state_outputs(state, for_execution=for_execution):
            _append_record(records, seen, path, step, problem)

    # Standalone files do not imply a new source experiment state.
    paths = {path for name in cst.MANAGED_NAMES for path in root.rglob(name)}
    paths.update(root.rglob(cst.FITS_REFERENCE_TEMPLATE.format(label="*")))
    paths.update(root.rglob(cst.FITS_ROI_TEMPLATE.format(label="*")))
    for path in sorted(paths):
        if is_internal_path(path, root):
            continue
        state = states_by_directory.get(path.parent)
        if (state is not None and state.artifact(cst.ARTI_IMG_RAW) is not None
                and not is_branch(path) and path.name in cst.LEGACY_RESULT_NAMES):
            # Retained earlier results are not active inputs.
            continue
        _append_record(records, seen, path)
    return records


def _state_outputs(state: ExperimentState, *, for_execution: bool) -> Iterator[tuple[Path, str | None, str]]:
    """
    Yield ordered step outputs and any additional canonical compacted outputs.
    """
    for step in cst.WORKFLOW_ORDER:
        profile = REGISTRY[step].profile
        path = state.workdir / profile.output_name
        active_output = state.artifact(profile.output_artifact)
        if not path.is_file() and active_output is not None and active_output.is_file():
            path = active_output
        if step == cst.StepName.EDIT_TRACK:
            active = state.artifact(cst.ARTI_TRACK)
            if active is not None and active.name in (cst.FITS_MASK_TRACK_EDITED, cst.FITS_MASK_TRACK_EDITED_FILTERED):
                path = active
        yield path, step, ""
    if state.compacted:
        problem = "Compacted inputs must be rebuilt before reprocessing." if for_execution else ""
        for kind in (cst.ARTI_IMG, cst.ARTI_TRACK, cst.ARTI_SEG):
            path = state.artifact(kind)
            if path is not None:
                yield path, None, problem


def _append_record(records: list[ArtifactRecord],
                   seen: set[Path],
                   path: Path,
                   step: str | None = None,
                   problem: str = "",
                   ) -> None:
    """
    Read an existing artifact once, retaining its first workflow assignment.
    """
    if not path.is_file():
        return
    resolved = path.resolve()
    if resolved not in seen:
        records.append(_record(path, step, problem))
        seen.add(resolved)


def _missing_input_records(states: Sequence[ExperimentState],
                           config: Mapping[str, Any],
                           *,
                           for_execution: bool,
                           ) -> list[ArtifactRecord]:
    """
    Report unavailable inputs for enabled work, allowing accepted checkpoints.
    """
    records: list[ArtifactRecord] = []
    for state in states:
        if state.compacted and not for_execution:
            continue
        for step in cst.WORKFLOW_ORDER:
            entry = config.get(step, {})
            if not entry.get("enabled"):
                continue
            profile = configured_profile(REGISTRY[step].profile, config)
            if checkpoint_complete(state, profile, entry.get("params", {}).get("overwrite", False)):
                continue
            output = state.artifact(profile.output_artifact)
            if output is not None and output.is_file():
                continue
            if not for_execution and output is None and step not in state.completed_steps:
                # Future enabled work has no saved result to mark as outdated.
                continue
            try:
                resolve_inputs(state, profile)
            except ValueError as error:
                records.append(ArtifactRecord(state.workdir / profile.output_name, step, None, str(error)))
    return records


def _propagate_conflicts(records: list[ArtifactRecord],
                         states_by_directory: Mapping[Path, ExperimentState],
                         config: Mapping[str, Any],
                         *,
                         for_execution: bool,
                         ) -> list[ArtifactRecord]:
    """
    Propagate upstream conflicts until no additional artifacts become stale.
    """
    problems = {record.path.resolve(): record.problem for record in records if record.problem}
    for _ in range(len(records) + 1):
        changed = False
        updated: list[ArtifactRecord] = []
        for record in records:
            state = states_by_directory.get(record.path.parent)
            if is_branch(record.path):
                reason = _branch_problem(record, state, config)
                if reason:
                    problems[record.path.resolve()] = reason
                    changed = changed or not record.problem
                updated.append(replace(record, problem=reason))
                continue
            reason = record.problem
            if not reason:
                reason = (settings_problem(record, config)
                          or _reference_problem(record, state, problems, for_execution=for_execution)
                          or _configured_input_problem(record, state, config))
            if reason and not record.problem:
                changed = True
                problems[record.path.resolve()] = reason
                record = replace(record, problem=reason)
            updated.append(record)
        records = updated
        if not changed:
            break
    return records


def _branch_problem(record: ArtifactRecord, state: ExperimentState | None, config: Mapping[str, Any]) -> str:
    """
    Check drawing geometry independently of image-intensity revisions.
    """
    image = (state.artifact(configured_profile(REGISTRY[cst.StepName.DISTANCE_PROFILE].profile, config).input_artifact)
             if state is not None else None)
    if state is not None and state.compacted:
        image = state.artifact(cst.ARTI_IMG)
    if image is not None and record.metadata is not None:
        try:
            if geometry(record.metadata) != geometry(read_metadata(image)):
                return "Registration geometry changed; review this REF/ROI drawing."
        except Exception as error:
            return str(error)
    return record.problem


def _reference_problem(record: ArtifactRecord,
                       state: ExperimentState | None,
                       problems: Mapping[Path, str],
                       *,
                       for_execution: bool,
                       ) -> str:
    """
    Find the first missing, stale or unreadable recorded input revision.
    """
    if record.metadata is None:
        return ""
    for ref in _recorded_inputs(record.metadata):
        if ref.get("external"):
            continue
        parent = (record.path.parent / ref["artifact_path"]).resolve()
        if state is not None and state.compacted and not for_execution and parent.parent == state.workdir and not parent.is_file():
            continue
        if parent in problems:
            return f"Upstream input is outdated: {parent.name}"
        if not parent.is_file():
            return f"Required input is missing: {parent.name}"
        try:
            stamp = read_metadata(parent).fits_io.created_at
            if not stamp or stamp != ref.get("created_at"):
                return f"Input revision differs: {parent.name}"
        except Exception as error:
            return f"Cannot verify input {parent.name}: {error}"
    return ""


def _recorded_inputs(metadata: FitsIOMeta) -> list[dict[str, Any]]:
    """
    Return structured input references; older string or absent forms have none.
    """
    refs = metadata.fits_io.derived_from
    return refs if isinstance(refs, list) else []


def _configured_input_problem(record: ArtifactRecord,
                              state: ExperimentState | None,
                              config: Mapping[str, Any],
                              ) -> str:
    """
    Compare saved inputs with the enabled chain without inventing old lineage.
    """
    if record.metadata is None or state is None or record.step is None or record.step == cst.StepName.CONVERT or state.compacted:
        return ""
    try:
        profile = configured_profile(REGISTRY[record.step].profile, config)
        expected = resolve_inputs(state, profile)
        recorded = {(record.path.parent / ref["artifact_path"]).resolve()
                    for ref in _recorded_inputs(record.metadata)}
        for path in expected.values():
            if path.resolve() not in recorded:
                if record.metadata.custom_metadata.get("migration"):
                    return f"Upstream input {path.name} is now available or changed; the preserved migrated result has unverified lineage."
                return f"Configured input changed: {path.name}"
    except ValueError as error:
        if not record.metadata.custom_metadata.get("migration"):
            return str(error)
    return ""


def _build_report(records: Sequence[ArtifactRecord],
                  states: Sequence[ExperimentState],
                  config: Mapping[str, Any],
                  *,
                  for_execution: bool,
                  ) -> PreflightReport:
    """
    Describe requested overwrites, affected downstream work and output paths.
    """
    existing_steps = {record.step for record in records}
    overwritten = tuple(step for step in overwrite_steps(config) if step in existing_steps) if for_execution else ()
    sources, from_original = rebuild_sources(records, states, overwritten)
    affected = downstream_steps(sources)
    steps = sources | set(affected)
    outputs: list[tuple[str, Path]] = []
    for state in states:
        existing = {record.step for record in records if record.path.parent == state.workdir}
        if from_original:
            existing.update(state.completed_steps)
        for step in cst.WORKFLOW_ORDER:
            if step in steps and (step in existing or config.get(step, {}).get("enabled")):
                outputs.append((str(step), state.workdir / REGISTRY[step].profile.output_name))
    report = PreflightReport(tuple(records), overwritten, affected, tuple(states), tuple(outputs))
    return _include_required_rebuild_outputs(report, config) if report.needs_decision else report


def _include_required_rebuild_outputs(report: PreflightReport, config: Mapping[str, Any]) -> PreflightReport:
    """
    Include missing prerequisites enabled by the actual rebuild decision.
    """
    try:
        planned = apply_decision(config, report, "rebuild")
    except ValueError:
        return report
    outputs = list(report.rebuild_outputs)
    for state in report.states:
        for step in overwrite_steps(planned):
            output = (str(step), state.workdir / REGISTRY[step].profile.output_name)
            if output not in outputs:
                outputs.append(output)
    return replace(report, rebuild_outputs=tuple(outputs))


def _record(path: Path, step: str | None, problem: str = "") -> ArtifactRecord:
    """
    Read artifact metadata and turn compatibility/read failures into a record.
    """
    try:
        metadata = read_metadata(path)
        legacy = not compatible(metadata)
        if is_branch(path):
            return ArtifactRecord(path.resolve(), step, metadata, problem, False)
        if legacy:
            problem = "Earlier FITS version or missing revision provenance: read-only; rebuilding is required."
        return ArtifactRecord(path.resolve(), step, metadata, problem, legacy)
    except Exception as error:
        return ArtifactRecord(path.resolve(), step, None, f"Cannot read artifact metadata: {error}", True)
