from __future__ import annotations

import logging
import os
from collections import deque
from collections.abc import Mapping
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ThreadPoolExecutor,
    wait,
)
from dataclasses import dataclass
from typing import Any

from progress_bar import pbar
from progress_bar.api import ProgressBar

from fits.environment.constant import WORKFLOW_ORDER
from fits.environment.state import ExperimentState
from fits.workflows.engines.models import StepSpec
from fits.workflows.engines.registry import REGISTRY


logger = logging.getLogger(__name__)


WAIT_HEARTBEAT_SECONDS = 60.0



@dataclass(frozen=True, slots=True)
class RuntimeStep:
    spec: StepSpec[Any]
    settings: Any


@dataclass(frozen=True, slots=True)
class Task:
    step_index: int
    state: ExperimentState


FutureResult = Future[list[ExperimentState]]
RunningTasks = dict[FutureResult, Task]


def run_workflow_scheduler(effective_cfg: Mapping[str, Any], exp_states: list[ExperimentState],) -> list[ExperimentState]:
    """
    Execute the configured workflow as a conveyor pipeline.

    Experiments advance independently through the enabled workflow steps.
    CPU and GPU tasks use separate executors, allowing later steps for one
    experiment to run while another experiment is still processing upstream.
    """
    runtime_steps = _resolve_runtime_steps(effective_cfg)

    if not runtime_steps:
        return exp_states

    logger.info("Scheduler starting with enabled steps: %s",
        [step.spec.profile.step_name for step in runtime_steps],)

    cpu_ready: deque[Task] = deque(
        Task(step_index=0, state=state)
        for state in exp_states
    )
    gpu_ready: deque[Task] = deque()

    # Move initial tasks into their correct executor queue.
    if runtime_steps[0].spec.pool == "gpu":
        gpu_ready.extend(cpu_ready)
        cpu_ready.clear()

    cpu_workers = os.cpu_count() or 1
    final_states: list[ExperimentState] = []

    with (
        ThreadPoolExecutor(max_workers=cpu_workers) as cpu_executor,
        ThreadPoolExecutor(max_workers=1) as gpu_executor,
        pbar(
            total=len(exp_states),
            desc="Pipeline",
            logs="off",
        ) as progress,
    ):
        cpu_running: RunningTasks = {}
        gpu_running: RunningTasks = {}
        total_tasks = len(exp_states)

        while cpu_ready or gpu_ready or cpu_running or gpu_running:
            _submit_ready_tasks(
                ready=cpu_ready,
                running=cpu_running,
                max_running=cpu_workers,
                executor=cpu_executor,
                runtime_steps=runtime_steps,
            )

            _submit_ready_tasks(
                ready=gpu_ready,
                running=gpu_running,
                max_running=1,
                executor=gpu_executor,
                runtime_steps=runtime_steps,
            )

            running_futures = set(cpu_running) | set(gpu_running)

            if not running_futures:
                break

            done, _ = wait(
                running_futures,
                timeout=WAIT_HEARTBEAT_SECONDS,
                return_when=FIRST_COMPLETED,
            )

            if not done:
                _log_heartbeat(
                    cpu_ready=cpu_ready,
                    gpu_ready=gpu_ready,
                    cpu_running=cpu_running,
                    gpu_running=gpu_running,
                    runtime_steps=runtime_steps,
                )
                continue

            queued_count = _process_completed_tasks(
                done=done,
                cpu_running=cpu_running,
                gpu_running=gpu_running,
                runtime_steps=runtime_steps,
                cpu_ready=cpu_ready,
                gpu_ready=gpu_ready,
                final_states=final_states,
                progress=progress,
            )

            if queued_count:
                total_tasks += queued_count
                progress.update(total=total_tasks)

    logger.info(
        "Scheduler completed with %d terminal states",
        len(final_states),
    )

    return final_states


def _resolve_runtime_steps(
    workflow_cfg: Mapping[str, Any],
) -> list[RuntimeStep]:
    """
    Resolve enabled registry entries and validate their settings.
    """
    runtime_steps: list[RuntimeStep] = []

    for step_name in WORKFLOW_ORDER:
        step_cfg = workflow_cfg.get(step_name)

        if not isinstance(step_cfg, Mapping):
            continue

        if not step_cfg.get("enabled", False):
            continue

        spec = REGISTRY.get(step_name)

        if spec is None:
            raise ValueError(
                f"Enabled step {step_name!r} is missing from the registry."
            )

        params = step_cfg.get("params", {})

        if not isinstance(params, Mapping):
            raise TypeError(
                f"Expected '{step_name}.params' to be a mapping."
            )

        runtime_steps.append(
            RuntimeStep(
                spec=spec,
                settings=spec.model_validate(params),
            )
        )

    return runtime_steps


def _submit_ready_tasks(
    *,
    ready: deque[Task],
    running: RunningTasks,
    max_running: int,
    executor: ThreadPoolExecutor,
    runtime_steps: list[RuntimeStep],
) -> None:
    while ready and len(running) < max_running:
        task = _pop_eligible_task(
            ready=ready,
            running=running,
            runtime_steps=runtime_steps,
        )

        if task is None:
            return

        runtime_step = runtime_steps[task.step_index]
        profile = runtime_step.spec.profile

        logger.debug(
            "Submitting %s for %s",
            profile.step_name,
            task.state.experiment_id,
        )

        future = executor.submit(
            runtime_step.spec.item_runner,
            runtime_step.settings,
            task.state,
            profile,
        )

        running[future] = task


def _pop_eligible_task(
    *,
    ready: deque[Task],
    running: RunningTasks,
    runtime_steps: list[RuntimeStep],
) -> Task | None:
    """
    Return the next task that does not exceed its step concurrency cap.
    """
    for _ in range(len(ready)):
        task = ready[0]

        if _within_step_cap(
            task=task,
            running=running,
            runtime_steps=runtime_steps,
        ):
            return ready.popleft()

        ready.rotate(-1)

    return None


def _within_step_cap(
    *,
    task: Task,
    running: RunningTasks,
    runtime_steps: list[RuntimeStep],
) -> bool:
    spec = runtime_steps[task.step_index].spec
    cap = spec.max_concurrency

    if cap is None:
        return True

    running_for_step = sum(
        running_task.step_index == task.step_index
        for running_task in running.values()
    )

    return running_for_step < cap


def _process_completed_tasks(
    *,
    done: set[FutureResult],
    cpu_running: RunningTasks,
    gpu_running: RunningTasks,
    runtime_steps: list[RuntimeStep],
    cpu_ready: deque[Task],
    gpu_ready: deque[Task],
    final_states: list[ExperimentState],
    progress: ProgressBar,
) -> int:
    queued_count = 0

    for future in done:
        task = cpu_running.pop(future, None)

        if task is None:
            task = gpu_running.pop(future)

        runtime_step = runtime_steps[task.step_index]
        step_name = runtime_step.spec.profile.step_name
        produced_states = future.result()

        progress.advance()

        logger.debug(
            "Completed %s for %s; produced %d state(s)",
            step_name,
            task.state.experiment_id,
            len(produced_states),
        )

        next_step_index = task.step_index + 1

        for state in produced_states:
            if next_step_index >= len(runtime_steps):
                final_states.append(state)
                continue

            next_task = Task(
                step_index=next_step_index,
                state=state,
            )

            _enqueue_task(
                next_task,
                runtime_steps=runtime_steps,
                cpu_ready=cpu_ready,
                gpu_ready=gpu_ready,
            )

            queued_count += 1

    return queued_count


def _enqueue_task(
    task: Task,
    *,
    runtime_steps: list[RuntimeStep],
    cpu_ready: deque[Task],
    gpu_ready: deque[Task],
) -> None:
    pool = runtime_steps[task.step_index].spec.pool

    if pool == "cpu":
        cpu_ready.append(task)
    elif pool == "gpu":
        gpu_ready.append(task)
    else:
        step_name = runtime_steps[task.step_index].spec.profile.step_name
        raise ValueError(
            f"Unsupported pool {pool!r} for step {step_name!r}."
        )


def _log_heartbeat(
    *,
    cpu_ready: deque[Task],
    gpu_ready: deque[Task],
    cpu_running: RunningTasks,
    gpu_running: RunningTasks,
    runtime_steps: list[RuntimeStep],
) -> None:
    running_labels = [
        (
            runtime_steps[task.step_index].spec.profile.step_name,
            task.state.experiment_id,
        )
        for task in (*cpu_running.values(), *gpu_running.values())
    ]

    logger.warning(
        "Scheduler heartbeat: no completion for %.1fs | "
        "running=%d ready_cpu=%d ready_gpu=%d in_flight=%s",
        WAIT_HEARTBEAT_SECONDS,
        len(cpu_running) + len(gpu_running),
        len(cpu_ready),
        len(gpu_ready),
        running_labels,
    )