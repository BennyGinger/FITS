"""Translate preflight choices into execution settings without changing artifacts."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from copy import deepcopy
from typing import Any

from fits.environment import constant as cst
from fits.workflows.checks.models import PreflightReport
from fits.workflows.checks.planning import downstream_steps, rebuild_sources
from fits.workflows.definitions.inputs import configured_profile
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.errors import PipelineCancelled


def apply_decision(config: Mapping[str, Any], report: PreflightReport, decision: str) -> dict[str, Any]:
    """
    Return a settings copy implementing the selected pre-run decision.

    Supported decisions are ``cancel``, ``continue``, ``selected`` (selected
    step only), and ``rebuild``. Rebuilding enables affected work and restores
    required missing inputs. This function plans execution; it does not modify
    artifacts or the caller's settings.
    """
    if decision == "cancel":
        raise PipelineCancelled("Run cancelled before modifying artifacts.")
    if report.outdated_masters and decision != 'rebuild':
        raise ValueError('Combined analysis has outdated experiment membership. Rebuild analysis or cancel.')
    resolved = deepcopy(dict(config))
    if report.legacy and decision != "rebuild":
        raise ValueError("Earlier-version results are read-only. Rebuild or cancel.")
    if decision == "selected":
        _disable_downstream_steps(resolved, report)
    elif decision == "rebuild":
        _enable_rebuild_steps(resolved, report)
        _restore_missing_inputs(resolved, report.states)
    elif decision != "continue":
        raise ValueError(f"Unknown preflight decision: {decision}")
    return resolved


def _disable_downstream_steps(config: dict[str, Any], report: PreflightReport) -> None:
    """
    Keep requested overwrites while disabling their downstream work in the copy.
    """
    for step in report.affected:
        if step not in report.overwritten and step in config:
            config[step]["enabled"] = False


def _enable_rebuild_steps(config: dict[str, Any], report: PreflightReport) -> None:
    """
    Enable affected existing/configured work, validating original-data rebuilds.
    """
    records = tuple(record for record in report.records if record.legacy or record.step not in report.disabled_steps)
    sources, from_original = rebuild_sources(records, report.states, report.overwritten)
    if from_original:
        if not report.states or any(not state.original_image.is_file() for state in report.states):
            raise ValueError("Original acquisition files/state are unavailable. Rebuilding cannot proceed.")
    steps = sources | set(downstream_steps(sources))
    existing = {record.step for record in report.records if record.step}
    if from_original:
        existing.update(step for state in report.states for step in state.completed_steps)
    for step in steps:
        if step in config and (from_original or step not in report.disabled_steps) and (
                step in existing or config[step].get("enabled") or step == cst.StepName.CONVERT):
            config[step]["enabled"] = True
            config[step].setdefault("params", {})["overwrite"] = True


def _restore_missing_inputs(config: dict[str, Any], states: Sequence[ExperimentState]) -> None:
    """
    Enable missing prerequisites until the configured input chain is complete.
    """
    for _ in range(len(REGISTRY)):
        changed = False
        for state in states:
            for producer in _missing_input_producers(state, config):
                entry = config.setdefault(producer, {"enabled": False, "params": {}})
                if not entry.get("enabled"):
                    entry["enabled"] = True
                    changed = True
                entry.setdefault("params", {})["overwrite"] = True
        if not changed:
            break


def _missing_input_producers(state: ExperimentState, config: Mapping[str, Any]) -> Iterator[str]:
    """
    Find required producers along the enabled chain, rather than historical refs.
    """
    for step in cst.WORKFLOW_ORDER:
        if not config.get(step, {}).get("enabled"):
            continue
        profile = configured_profile(REGISTRY[step].profile, config)
        for kind in (profile.input_artifact, *profile.additional_artifacts):
            if kind not in (*cst.IMAGE_STAGE_ARTIFACTS, cst.ARTI_SEG, cst.ARTI_TRACK):
                continue
            path = state.artifact(kind)
            if path is not None and path.is_file():
                continue
            producer = next(name for name, spec in REGISTRY.items() if spec.profile.output_artifact == kind)
            if producer == cst.StepName.CONVERT and not state.original_image.is_file():
                raise ValueError(f"Missing original acquisition: {state.original_image}")
            yield producer
