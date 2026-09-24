"""Execute one workflow step across a batch of experiment states."""

import logging
from collections.abc import Callable
from functools import partial
from typing import Any, cast

from progress_bar import pbar

from fits.workflows.experiments import ExperimentState
from fits.settings.models import SettingsModel
from fits.workflows.definitions.models import StepSpec, item_runner_for
from fits.workflows.runtime.batch.workers import execute_items
from fits.workflows.runtime.progress.reporting import WorkflowReporter


logger = logging.getLogger(__name__)

ReportedResult = tuple[ExperimentState, list[ExperimentState], Exception | None]
WorkerResult = list[ExperimentState] | ReportedResult


def execute_batch_step(spec: StepSpec[Any],
                        settings: SettingsModel,
                        exp_states: list[ExperimentState],
                        reporter: WorkflowReporter | None = None,
                        ) -> list[ExperimentState]:
    """
    Execute one configured step for every state in the current batch.
    """
    profile = spec.profile
    item_runner = item_runner_for(spec)
    logger.debug("Executing %s with mode=%s workers=%s ordered=%s",
                profile.step_name,
                settings.execution,
                settings.workers,
                settings.ordered_execution,)

    def worker(state: ExperimentState) -> list[ExperimentState]:
        return item_runner(settings, state, profile)

    batch_worker: Callable[[ExperimentState], WorkerResult] = worker

    if reporter is not None:
        for state in exp_states:
            reporter.started(profile.step_name, state)
        batch_worker = partial(
            _execute_reported_item, spec, settings, item_runner)

    output_states: list[ExperimentState] = []
    first_error: Exception | None = None
    with pbar(total=len(exp_states),
            desc=profile.step_name.capitalize(),
            logs="buffered",) as progress:
        for produced_states in execute_items(exp_states,
                                            batch_worker,
                                            mode=settings.execution,
                                            workers=settings.workers,
                                            ordered=settings.ordered_execution,):
            if reporter is not None:
                source, outputs, error = cast(ReportedResult, produced_states)
                if error is not None:
                    reporter.failed(profile.step_name, source, error)
                    if settings.execution == "serial":
                        raise error
                    first_error = first_error or error
                    progress.advance()
                    continue
                reporter.completed(profile.step_name, source, outputs)
                produced_states = outputs
            output_states.extend(cast(list[ExperimentState], produced_states))
            progress.advance()

    if first_error is not None:
        raise first_error
    return output_states


def _execute_reported_item(spec: StepSpec[Any], settings: SettingsModel,
                           item_runner: Callable,
                           state: ExperimentState,) -> ReportedResult:
    """
    Return an item's output or error so the parent can update reporting.
    """
    try:
        return state, item_runner(settings, state, spec.profile), None
    except Exception as error:
        return state, [], error
