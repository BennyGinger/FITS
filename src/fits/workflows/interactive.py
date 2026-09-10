"""Small conveyor for image preparation, interactive masks, and analysis.

No Qt dependencies: callbacks announce work; a thread-safe queue returns outcomes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
from queue import Empty, Queue
from threading import Event
from typing import Any, Callable, Mapping

from fits.environment.constant import ARTI_IMG, StepName
from fits.environment.state import ExperimentState
from fits.sessions.collection import MaskCollectionRequest, MaskCollectionOutcome
from fits.workflows.engines.scheduler import _resolve_runtime_steps

logger = logging.getLogger(__name__)
PREPARATION = {StepName.CONVERT, StepName.REGISTER_TIME, StepName.REGISTER_CHANNEL, StepName.BG_SUB}
COMPUTATION = {StepName.SEGMENT, StepName.TRACK}
ANALYSIS = {StepName.DISTANCE_PROFILE, StepName.EXTRACT}


class PipelineCancelled(Exception):
    """User-requested cancellation, distinct from a processing failure."""


class MaskInteraction:
    def __init__(self, request: Callable[[MaskCollectionRequest], None],
                 input_complete: Callable[[], None] = lambda: None) -> None:
        self.request = request
        self.input_complete = input_complete
        self.cancelled = Event()
        self.finished = Event()
        self.outcomes = Queue()

    def resolve(self, outcome: MaskCollectionOutcome) -> None:
        self.outcomes.put(outcome)

    def finish(self) -> None:
        self.finished.set()

    def cancel(self) -> None:
        self.cancelled.set()

    def check_cancelled(self) -> None:
        if self.cancelled.is_set():
            raise PipelineCancelled("Pipeline cancelled. Completed artifacts have been kept.")


def interactive_masks_requested(config: Mapping[str, Any]) -> bool:
    profile = config.get('distance_profile', {})
    extraction = config.get('extract', {})
    return bool(profile.get('enabled', False) or (
        extraction.get('enabled', False) and extraction.get('params', {}).get('draw_ref_mask', False)))


def _existing_outcome(request: MaskCollectionRequest) -> MaskCollectionOutcome:
    folder = request.image_path.parent
    refs = tuple(sorted(p for p in folder.glob('fits_ref_*.tif') if p.is_file()))
    rois = tuple(sorted(p for p in folder.glob('fits_roi_*.tif') if p.is_file()))
    return MaskCollectionOutcome(request, refs, rois,
        max(0, request.expected_ref_masks - len(refs)), max(0, request.expected_roi_masks - len(rois)))


def _validate_outcome(request: MaskCollectionRequest, outcome: MaskCollectionOutcome) -> None:
    """Check the exact mask set before tasks discover and consume those files."""
    from fits_io import FitsIO
    from fits.tasks.reference_mask.artifact import load_reference_artifact
    from fits.tasks.roi_mask.artifact import load_roi_artifact

    if outcome.request != request:
        raise ValueError('Mask result does not match its experiment request.')
    existing = _existing_outcome(request)
    if (set(existing.reference_paths) != set(outcome.reference_paths)
            or set(existing.roi_paths) != set(outcome.roi_paths)):
        raise ValueError(f'Mask files changed after finalization for {request.experiment_id}.')
    reader = FitsIO.from_path(request.image_path)
    loaded = reader.get_array()
    for paths, loader in ((outcome.reference_paths, load_reference_artifact),
                          (outcome.roi_paths if request.uses_roi else (), load_roi_artifact)):
        for path in paths:
            loader(path, source_path=request.image_path, source_axes=loaded.axes,
                   source_shape=loaded.array.shape, source_channels=tuple(reader.channel_labels))


def run_interactive_workflow(config: Mapping[str, Any], states: list[ExperimentState],
                             interaction: MaskInteraction, *,
                             step_delay_seconds: float = 0.0) -> list[ExperimentState]:
    """Prepare experiments one by one while drawing and downstream work overlap."""
    if step_delay_seconds < 0:
        raise ValueError('Demo step delay cannot be negative.')
    steps = _resolve_runtime_steps(config)
    if any(step.spec.profile.step_name not in PREPARATION | COMPUTATION | ANALYSIS for step in steps):
        raise ValueError('An enabled step has no interactive pipeline phase.')
    preparation = [s for s in steps if s.spec.profile.step_name in PREPARATION]
    computation = [s for s in steps if s.spec.profile.step_name in COMPUTATION]
    analysis = [s for s in steps if s.spec.profile.step_name in ANALYSIS]
    settings = {s.spec.profile.step_name: s.settings for s in steps}
    prepared = Queue()
    producer_done = Event()
    stop_preparation = Event()

    def pause():
        interaction.check_cancelled()
        if stop_preparation.is_set():
            raise PipelineCancelled('Preparation stopped.')
        if step_delay_seconds:
            logger.info('Demo pause: %.1f seconds.', step_delay_seconds)
            # Short waits make cancellation responsive even during the demo delay.
            from time import monotonic
            deadline = monotonic() + step_delay_seconds
            while monotonic() < deadline:
                if stop_preparation.wait(min(.1, max(0, deadline - monotonic()))):
                    raise PipelineCancelled('Preparation stopped.')
                interaction.check_cancelled()

    def run_steps(current, selected_steps):
        for step in selected_steps:
            produced = []
            for state in current:
                interaction.check_cancelled()
                if stop_preparation.is_set():
                    raise PipelineCancelled('Preparation stopped.')
                logger.info('Starting %s for %s', step.spec.profile.step_name, state.experiment_id)
                produced.extend(step.spec.item_runner(step.settings, state, step.spec.profile))
                logger.info('Finished %s for %s', step.spec.profile.step_name, state.experiment_id)
                pause()
            current = produced
        return current

    def prepare():
        try:
            for original in states:
                interaction.check_cancelled()
                for state in run_steps([original], preparation):
                    if not preparation:
                        pause()
                    image = state.artifact(ARTI_IMG)
                    if image is None or not image.is_file():
                        raise ValueError(f'No prepared image for {state.experiment_id}. Enable conversion first.')
                    request = MaskCollectionRequest.from_settings(image,
                        extraction=settings.get(StepName.EXTRACT), profile=settings.get(StepName.DISTANCE_PROFILE))
                    request = replace(request, experiment_id=state.experiment_id)
                    logger.info('Ready for mask drawing: %s', state.experiment_id)
                    if not interaction.finished.is_set():
                        interaction.request(request)
                    prepared.put((state, request))
        finally:
            producer_done.set()
            interaction.input_complete()

    final_states = []
    pending = {}
    received = {}
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix='fits-preparation') as executor:
        producer = executor.submit(prepare)
        try:
            while not producer_done.is_set() or not prepared.empty() or pending:
                interaction.check_cancelled()
                if producer.done():
                    producer.result()  # Surface preparation errors even while waiting for drawing.
                while True:
                    try:
                        outcome = interaction.outcomes.get_nowait()
                    except Empty:
                        break
                    received[outcome.request.image_path] = outcome
                for key, (request, computed) in list(pending.items()):
                    outcome = received.pop(key, None)
                    if outcome is None and interaction.finished.is_set():
                        outcome = _existing_outcome(request)
                        logger.info('Drawing ended early; using existing masks for %s.', request.experiment_id)
                    if outcome is None:
                        continue
                    _validate_outcome(request, outcome)
                    selected = analysis
                    if not outcome.reference_paths:
                        selected = [s for s in analysis if s.spec.profile.step_name != StepName.DISTANCE_PROFILE]
                        if request.requires_reference:
                            logger.warning('Omitting distance profiling for %s: no reference mask was finalized.', request.experiment_id)
                    logger.info('Masks finalized for %s: %d references, %d ROIs, %d skipped requests.',
                        request.experiment_id, len(outcome.reference_paths), len(outcome.roi_paths),
                        outcome.skipped_references + outcome.skipped_rois)
                    final_states.extend(run_steps(computed, selected))
                    del pending[key]
                try:
                    state, request = prepared.get(timeout=.1)
                except Empty:
                    continue
                computed = run_steps([state], computation)
                pending[request.image_path] = (request, computed)
            producer.result()
            interaction.check_cancelled()
        finally:
            stop_preparation.set()
    return final_states
