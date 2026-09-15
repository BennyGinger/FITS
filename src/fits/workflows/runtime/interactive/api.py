"""Orchestrate image preparation, interactive masks, and analysis.

No Qt dependencies: callbacks announce work; a thread-safe queue returns outcomes.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import logging
from queue import Empty, Queue
from threading import Event
from typing import Any, Mapping

from fits.environment.constant import ARTI_IMG, StepName
from fits.workflows.runtime.progress import RunProgress, StageStatus, WorkflowStage
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.interactive.messages import MaskCollectionRequest
from fits.workflows.runtime.errors import (
    AllExperimentsFailed, PipelineCancelled)
from fits.workflows.runtime.interactive.interaction import MaskInteraction
from fits.workflows.runtime.interactive.masks import (
    existing_mask_outcome, validate_mask_outcome)
from fits.workflows.runtime.interactive.progress import input_progress_id
from fits.workflows.runtime.scheduler import resolve_runtime_steps

logger = logging.getLogger(__name__)
CONVERSION = {StepName.CONVERT}
PREPROCESSING = {StepName.REGISTER_TIME, StepName.REGISTER_CHANNEL, StepName.BG_SUB}
COMPUTATION = {StepName.SEGMENT, StepName.TRACK}
ANALYSIS = {StepName.DISTANCE_PROFILE, StepName.EXTRACT}


def run_interactive_workflow(config: Mapping[str, Any], states: list[ExperimentState],
                             interaction: MaskInteraction, *,
                             step_delay_seconds: float = 0.0,
                             progress: RunProgress | None = None) -> list[ExperimentState]:
    """
    Prepare experiments one by one while drawing and downstream work overlap.
    """
    if step_delay_seconds < 0:
        raise ValueError('Demo step delay cannot be negative.')
    
    steps = resolve_runtime_steps(config)
    if any(step.spec.profile.step_name not in CONVERSION | PREPROCESSING | COMPUTATION | ANALYSIS for step in steps):
        raise ValueError('An enabled step has no interactive pipeline phase.')
    
    conversion = [s for s in steps if s.spec.profile.step_name in CONVERSION]
    preprocessing = [s for s in steps if s.spec.profile.step_name in PREPROCESSING]
    computation = [s for s in steps if s.spec.profile.step_name in COMPUTATION]
    analysis = [s for s in steps if s.spec.profile.step_name in ANALYSIS]
    settings = {s.spec.profile.step_name: s.settings for s in steps}
    progress = progress or RunProgress()
    required_stages = {WorkflowStage.DRAWING}
    for stage, selected in ((WorkflowStage.CONVERT, conversion),
                            (WorkflowStage.PREPROCESS, preprocessing),
                            (WorkflowStage.PROCESS, computation),
                            (WorkflowStage.ANALYSIS, analysis)):
        if selected:
            required_stages.add(stage)
    
    for state in states:
        progress.add(input_progress_id(state), required_stages)
    
    interaction.expected_count(len(states))
    expected_drawings = [len(states)]
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

    def run_steps(current, selected_steps, stage, experiment_id):
        if not selected_steps:
            return current
        progress.update(experiment_id, stage, StageStatus.ACTIVE)
        try:
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
        
        except PipelineCancelled:
            progress.update(experiment_id, stage, StageStatus.SKIPPED)
            raise
        
        except Exception as error:
            progress.update(experiment_id, stage, StageStatus.FAILED,
                            error=str(error))
            raise
        progress.update(experiment_id, stage, StageStatus.COMPLETED)
        return current

    def adjust_expected_drawings(delta: int) -> None:
        if not delta:
            return
        expected_drawings[0] = max(0, expected_drawings[0] + delta)
        interaction.expected_count(expected_drawings[0])

    def contain_failure(experiment_id: str, stage: WorkflowStage,
                        error: Exception) -> None:
        progress.skip_pending(
            experiment_id, detail=f'not run because {stage.value} failed')
        logger.error(
            "Experiment failed during %s and will be omitted; remaining experiments will continue: %s | experiment=%s",
            stage.value, error, experiment_id,
            exc_info=error.__traceback__ is not None)

    def prepare():
        try:
            for original in states:
                interaction.check_cancelled()
                original_id = input_progress_id(original)
                try:
                    converted = run_steps([original], conversion, WorkflowStage.CONVERT,
                                          original_id)
                except PipelineCancelled:
                    raise
                except Exception as error:
                    contain_failure(original_id, WorkflowStage.CONVERT, error)
                    adjust_expected_drawings(-1)
                    continue
                progress.replace_experiment(
                    original_id, (state.experiment_id for state in converted))
                adjust_expected_drawings(len(converted) - 1)
                for converted_state in converted:
                    experiment_id = converted_state.experiment_id
                    try:
                        prepared_states = run_steps(
                            [converted_state], preprocessing, WorkflowStage.PREPROCESS,
                            experiment_id)
                    except PipelineCancelled:
                        raise
                    except Exception as error:
                        contain_failure(experiment_id, WorkflowStage.PREPROCESS, error)
                        adjust_expected_drawings(-1)
                        continue
                    for state in prepared_states:
                        if not conversion and not preprocessing:
                            pause()
                        image = state.artifact(ARTI_IMG)
                        if image is None or not image.is_file():
                            error = f'No prepared image for {state.experiment_id}. Enable conversion first.'
                            progress.update(state.experiment_id, WorkflowStage.PREPROCESS,
                                            StageStatus.FAILED, error=error)
                            contain_failure(state.experiment_id, WorkflowStage.PREPROCESS,
                                            ValueError(error))
                            adjust_expected_drawings(-1)
                            continue
                        request = MaskCollectionRequest.from_settings(image,
                            extraction=settings.get(StepName.EXTRACT), profile=settings.get(StepName.DISTANCE_PROFILE))
                        request = replace(request, experiment_id=state.experiment_id)
                        progress.update(state.experiment_id, WorkflowStage.DRAWING,
                                        StageStatus.ACTIVE)
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
                        outcome = existing_mask_outcome(request)
                        logger.info('Drawing ended early; using existing masks for %s.', request.experiment_id)
                    if outcome is None:
                        continue
                    try:
                        validate_mask_outcome(request, outcome)
                    except Exception as error:
                        progress.update(request.experiment_id, WorkflowStage.DRAWING,
                                        StageStatus.FAILED, error=str(error))
                        progress.skip_pending(
                            request.experiment_id,
                            detail='not run because mask validation failed')
                        logger.error(
                            'Experiment mask validation failed and analysis will be omitted; remaining experiments will continue: %s | experiment=%s',
                            error, request.experiment_id, exc_info=True)
                        del pending[key]
                        continue
                    skipped = outcome.skipped_references + outcome.skipped_rois
                    missing_inputs = []
                    if request.requires_reference and not outcome.reference_paths:
                        missing_inputs.append('reference mask input missing')
                    if outcome.skipped_rois:
                        missing_inputs.append('ROI mask input missing')
                    drawing_status = (StageStatus.SKIPPED if skipped and not (
                        outcome.reference_paths or outcome.roi_paths) else StageStatus.COMPLETED)
                    progress.update(request.experiment_id, WorkflowStage.DRAWING,
                                    drawing_status,
                                    detail='; '.join(missing_inputs) or None)
                    selected = analysis
                    if not outcome.reference_paths:
                        selected = [s for s in analysis if s.spec.profile.step_name != StepName.DISTANCE_PROFILE]
                        if request.requires_reference:
                            logger.warning('Omitting distance profiling for %s: no reference mask was finalized.', request.experiment_id)
                    logger.info('Masks finalized for %s: %d references, %d ROIs, %d skipped requests.',
                        request.experiment_id, len(outcome.reference_paths), len(outcome.roi_paths),
                        outcome.skipped_references + outcome.skipped_rois)
                    if selected and computed is not None:
                        try:
                            final_states.extend(run_steps(
                                computed, selected, WorkflowStage.ANALYSIS,
                                request.experiment_id))
                        except PipelineCancelled:
                            raise
                        except Exception as error:
                            contain_failure(request.experiment_id,
                                            WorkflowStage.ANALYSIS, error)
                        else:
                            if missing_inputs:
                                detail = '; '.join(missing_inputs)
                                if not outcome.reference_paths and request.requires_reference:
                                    detail += '; distance profile skipped; extraction completed'
                                elif not outcome.roi_paths and request.uses_roi:
                                    detail += '; distance profile completed over the whole image'
                                progress.update(
                                    request.experiment_id, WorkflowStage.ANALYSIS,
                                    StageStatus.PARTIAL, detail=detail)
                    else:
                        status = StageStatus.PARTIAL if missing_inputs and computed is not None else StageStatus.SKIPPED
                        progress.update(
                            request.experiment_id, WorkflowStage.ANALYSIS, status,
                            detail=('; '.join(missing_inputs) + '; configured analysis could not run')
                            if missing_inputs else None)
                        if computed is not None:
                            final_states.extend(computed)
                    del pending[key]
                try:
                    state, request = prepared.get(timeout=.1)
                except Empty:
                    continue
                try:
                    computed = run_steps([state], computation, WorkflowStage.PROCESS,
                                         request.experiment_id)
                except PipelineCancelled:
                    raise
                except Exception as error:
                    contain_failure(request.experiment_id, WorkflowStage.PROCESS,
                                    error)
                    computed = None
                pending[request.image_path] = (request, computed)
            producer.result()
            interaction.check_cancelled()
        except PipelineCancelled:
            progress.skip_unfinished()
            raise
        finally:
            stop_preparation.set()
    snapshot = progress.snapshot()
    for stage in WorkflowStage:
        counts = {status: 0 for status in StageStatus}
        failures = []
        for experiment in snapshot:
            stage_progress = experiment.stage(stage)
            if stage_progress is None:
                continue
            counts[stage_progress.status] += 1
            if stage_progress.status == StageStatus.FAILED:
                failures.append(f'{experiment.experiment_id}: {stage_progress.error}')
        logger.info(
            'Run report %s: %d completed, %d partial, %d skipped, %d failed.',
            stage.value, counts[StageStatus.COMPLETED],
            counts[StageStatus.PARTIAL],
            counts[StageStatus.SKIPPED], counts[StageStatus.FAILED])
        for failure in failures:
            logger.error('Run report %s failure: %s', stage.value, failure)
    if states and not final_states:
        failures = [f'{experiment.experiment_id}: {stage.error}'
            for experiment in snapshot for stage in experiment.stages.values()
            if stage.status == StageStatus.FAILED]
        detail = '; '.join(failures) or 'no experiment produced a final state'
        raise AllExperimentsFailed(f'All experiments failed. {detail}')
    return final_states
