from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import logging
import os
from typing import Any, Mapping

from progress_bar import pbar

from fits.environment.constant import STEP_CONVERT, STEP_SEGMENT
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.state import ExperimentState
from fits.workflows.registry import REGISTRY, StepSpec
from fits.workflows.tasks.convert import convert_one
from fits.workflows.tasks.segment import segment_one


logger = logging.getLogger(__name__)

WORKFLOW_ORDER = [
    STEP_CONVERT,
    STEP_SEGMENT,
]


@dataclass(frozen=True)
class Task:
    step_name: str
    exp_state: ExperimentState


def _task_label(task: Task) -> str:
    st = task.exp_state
    return st.experiment_id or st.original_image_rel.as_posix()


def _enabled_workflow_steps(user_cfg: Mapping[str, Any]) -> list[str]:
    enabled_steps: list[str] = []
    for step_name in WORKFLOW_ORDER:
        step_cfg = user_cfg.get(step_name) or {}
        if step_cfg.get("enabled", False):
            enabled_steps.append(step_name)
    return enabled_steps


def _next_enabled_step(current_step: str, enabled_steps: list[str]) -> str | None:
    try:
        idx = enabled_steps.index(current_step)
    except ValueError:
        return None

    next_idx = idx + 1
    if next_idx >= len(enabled_steps):
        return None
    return enabled_steps[next_idx]


def _task_pool(step_name: str) -> str:
    if step_name == STEP_CONVERT:
        return "cpu"
    if step_name == STEP_SEGMENT:
        return "gpu"
    raise ValueError(f"Unsupported step for scheduler prototype: {step_name}")


def run_workflow_scheduler(
    user_cfg: Mapping[str, Any],
    exp_states: list[ExperimentState],
) -> list[ExperimentState]:
    ctx = get_ctx()

    enabled_steps = _enabled_workflow_steps(user_cfg)
    logger.info("Scheduler starting with enabled steps: %s", enabled_steps)
    if not enabled_steps:
        return exp_states

    settings_by_step: dict[str, Any] = {}
    step_specs: dict[str, StepSpec[Any]] = {}
    for step_name in enabled_steps:
        step_spec = REGISTRY.get(step_name)
        if step_spec is None:
            raise ValueError(f"Enabled step '{step_name}' missing from workflow registry.")

        step_cfg = user_cfg.get(step_name) or {}
        params = step_cfg.get("params", {})

        settings_by_step[step_name] = step_spec.model_validate(params)
        step_specs[step_name] = step_spec

    cpu_ready: deque[Task] = deque()
    gpu_ready: deque[Task] = deque()

    first_step = enabled_steps[0]
    for st in exp_states:
        task = Task(step_name=first_step, exp_state=st)
        if _task_pool(first_step) == "cpu":
            cpu_ready.append(task)
        else:
            gpu_ready.append(task)

    initial_task_count = len(exp_states)
    logger.info("Scheduler seeded %d tasks for first step '%s'", initial_task_count, first_step)

    cpu_workers = os.cpu_count() or 1
    final_states: list[ExperimentState] = []

    with ThreadPoolExecutor(max_workers=cpu_workers) as cpu_ex, ThreadPoolExecutor(max_workers=1) as gpu_ex, pbar(total=initial_task_count, desc="Pipeline", logs="off") as pb:
        cpu_running: dict[Future[list[ExperimentState]], Task] = {}
        gpu_running: dict[Future[list[ExperimentState]], Task] = {}
        total_tasks = initial_task_count

        def submit_task(task: Task, executor: ThreadPoolExecutor, running: dict[Future[list[ExperimentState]], Task]) -> None:
            step_name = task.step_name
            settings = settings_by_step[step_name]
            step_spec = step_specs[step_name]

            logger.debug("Submitting %s for %s", step_name, _task_label(task),)

            def run_task() -> list[ExperimentState]:
                with use_ctx(ctx):
                    if step_name == STEP_CONVERT:
                        return convert_one(settings, task.exp_state, step_spec.step_profile, step_spec.output_name)
                    if step_name == STEP_SEGMENT:
                        return [segment_one(settings, task.exp_state, step_spec.step_profile, step_spec.output_name)]
                    raise ValueError(f"Unsupported step for scheduler prototype: {step_name}")

            fut = executor.submit(run_task)
            running[fut] = task

        while cpu_ready or gpu_ready or cpu_running or gpu_running:
            while cpu_ready and len(cpu_running) < cpu_workers:
                submit_task(cpu_ready.popleft(), cpu_ex, cpu_running)

            while gpu_ready and len(gpu_running) < 1:
                submit_task(gpu_ready.popleft(), gpu_ex, gpu_running)

            if not cpu_running and not gpu_running and not cpu_ready and not gpu_ready:
                break

            running_union = set(cpu_running) | set(gpu_running)
            if not running_union:
                continue

            done, _ = wait(running_union, return_when=FIRST_COMPLETED)

            for fut in done:
                task = cpu_running.pop(fut, None)
                if task is None:
                    task = gpu_running.pop(fut)

                produced_states = fut.result()
                pb.advance()
                logger.debug("Completed %s for %s -> produced %d state(s)", task.step_name, _task_label(task), len(produced_states))

                next_step = _next_enabled_step(task.step_name, enabled_steps)
                newly_queued = 0
                for produced_state in produced_states:
                    if next_step is None:
                        final_states.append(produced_state)
                        continue

                    next_task = Task(step_name=next_step, exp_state=produced_state)
                    newly_queued += 1
                    logger.debug("Queued %s for %s", next_step, produced_state.experiment_id or produced_state.original_image_rel.as_posix())
                    
                    if _task_pool(next_step) == "cpu":
                        cpu_ready.append(next_task)
                    else:
                        gpu_ready.append(next_task)

                if newly_queued > 0:
                    total_tasks += newly_queued
                    pb.update(total=total_tasks)

    logger.info("Scheduler completed with %d terminal states", len(final_states))
    return final_states
