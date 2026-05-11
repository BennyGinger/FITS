from collections import deque
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
import logging
import os
from typing import Any, Mapping

from progress_bar import pbar
from progress_bar.api import ProgressBar

import fits.environment.constant as cst
from fits.environment.context import ExecutionContext
from fits.environment.runtime import get_ctx, use_ctx
from fits.environment.state import ExperimentState
from fits.workflows.engines.registry import REGISTRY, StepSpec


logger = logging.getLogger(__name__)


DEFAULT_STEP_CONCURRENCY_CAPS: dict[str, int] = {
    cst.STEP_REGISTER_TIME: 1,
}
WAIT_HEARTBEAT_SECONDS = 60.0



@dataclass(frozen=True)
class Task:
    step_name: str
    exp_state: ExperimentState

# ------------ Main scheduler function ------------
def run_workflow_scheduler(user_cfg: Mapping[str, Any], exp_states: list[ExperimentState]) -> list[ExperimentState]:
    ctx = get_ctx()

    enabled_steps = _enabled_workflow_steps(user_cfg)
    logger.info("Scheduler starting with enabled steps: %s", enabled_steps)
    if not enabled_steps:
        return exp_states

    settings_by_step, step_specs = _resolve_step_runtime(user_cfg, enabled_steps)
    step_caps = _resolve_step_concurrency_caps(enabled_steps)

    cpu_ready: deque[Task] = deque()
    gpu_ready: deque[Task] = deque()

    first_step = enabled_steps[0]
    for st in exp_states:
        _enqueue_task(Task(step_name=first_step, exp_state=st), step_specs, cpu_ready, gpu_ready)

    initial_task_count = len(exp_states)
    logger.info("Scheduler seeded %d tasks for first step '%s'", initial_task_count, first_step)
    logger.info("Scheduler per-step concurrency caps: %s", step_caps)

    cpu_workers = os.cpu_count() or 1
    final_states: list[ExperimentState] = []

    with ThreadPoolExecutor(max_workers=cpu_workers) as cpu_ex, ThreadPoolExecutor(max_workers=1) as gpu_ex, pbar(total=initial_task_count, desc="Pipeline", logs="off") as pb:
        cpu_running: dict[Future[list[ExperimentState]], Task] = {}
        gpu_running: dict[Future[list[ExperimentState]], Task] = {}
        total_tasks = initial_task_count

        while cpu_ready or gpu_ready or cpu_running or gpu_running:
            _submit_ready_tasks(
                cpu_ready,
                cpu_running,
                cpu_workers,
                cpu_ex,
                step_caps=step_caps,
                ctx=ctx,
                settings_by_step=settings_by_step,
                step_specs=step_specs,)
            _submit_ready_tasks(
                gpu_ready,
                gpu_running,
                1,
                gpu_ex,
                step_caps=step_caps,
                ctx=ctx,
                settings_by_step=settings_by_step,
                step_specs=step_specs,)

            if not cpu_running and not gpu_running and not cpu_ready and not gpu_ready:
                break

            running_union = set(cpu_running) | set(gpu_running)
            if not running_union:
                continue

            done, _ = wait(running_union, timeout=WAIT_HEARTBEAT_SECONDS, return_when=FIRST_COMPLETED)
            if not done:
                running_labels = [f"{task.step_name}:{_task_label(task)}" for task in [*cpu_running.values(), *gpu_running.values()]]
                logger.warning(
                    "Scheduler heartbeat: no completion for %.1fs | running=%d ready_cpu=%d ready_gpu=%d in_flight=%s",
                    WAIT_HEARTBEAT_SECONDS,
                    len(running_union),
                    len(cpu_ready),
                    len(gpu_ready),
                    running_labels,
                )
                continue

            newly_queued = _drain_completed_tasks(
                done,
                cpu_running=cpu_running,
                gpu_running=gpu_running,
                enabled_steps=enabled_steps,
                step_specs=step_specs,
                cpu_ready=cpu_ready,
                gpu_ready=gpu_ready,
                final_states=final_states,
                pb=pb,)
            if newly_queued > 0:
                total_tasks += newly_queued
                pb.update(total=total_tasks)

    logger.info("Scheduler completed with %d terminal states", len(final_states))
    return final_states


# ------------ Helpers functions ------------
def _task_label(task: Task) -> str:
    st = task.exp_state
    return st.experiment_id or st.original_image_rel.as_posix()


def _enabled_workflow_steps(user_cfg: Mapping[str, Any]) -> list[str]:
    enabled_steps: list[str] = []
    for step_name in cst.WORKFLOW_ORDER:
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


def _resolve_step_runtime(user_cfg: Mapping[str, Any], enabled_steps: list[str]) -> tuple[dict[str, Any], dict[str, StepSpec[Any]]]:
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

    return settings_by_step, step_specs


def _resolve_step_concurrency_caps(enabled_steps: list[str]) -> dict[str, int]:
    # Keep this internal for now; override support can be added later.
    return {
        step_name: cap
        for step_name, cap in DEFAULT_STEP_CONCURRENCY_CAPS.items()
        if step_name in enabled_steps and cap > 0
    }


def _enqueue_task(task: Task, step_specs: Mapping[str, StepSpec[Any]], cpu_ready: deque[Task], gpu_ready: deque[Task]) -> None:
    pool = step_specs[task.step_name].pool
    if pool == "cpu":
        cpu_ready.append(task)
        return
    if pool == "gpu":
        gpu_ready.append(task)
        return
    raise ValueError(f"Unsupported pool '{pool}' for step '{task.step_name}'.")


def _submit_task(task: Task, executor: ThreadPoolExecutor, running: dict[Future[list[ExperimentState]], Task], *, ctx: ExecutionContext, settings_by_step: Mapping[str, Any], step_specs: Mapping[str, StepSpec[Any]]) -> None:
    step_name = task.step_name
    settings = settings_by_step[step_name]
    step_spec = step_specs[step_name]

    logger.debug("Submitting %s for %s", step_name, _task_label(task),)

    def run_task() -> list[ExperimentState]:
        with use_ctx(ctx):
            return step_spec.item_runner(settings, task.exp_state, step_spec.step_profile, step_spec.output_name)

    fut = executor.submit(run_task)
    running[fut] = task


def _running_count_for_step(running: Mapping[Future[list[ExperimentState]], Task], step_name: str) -> int:
    return sum(1 for task in running.values() if task.step_name == step_name)


def _within_step_cap(task: Task, running: Mapping[Future[list[ExperimentState]], Task], step_caps: Mapping[str, int]) -> bool:
    cap = step_caps.get(task.step_name)
    if cap is None:
        return True
    return _running_count_for_step(running, task.step_name) < cap


def _pop_next_eligible_task(ready: deque[Task], running: Mapping[Future[list[ExperimentState]], Task], step_caps: Mapping[str, int]) -> Task | None:
    if not ready:
        return None

    scan_count = len(ready)
    for _ in range(scan_count):
        task = ready[0]
        if _within_step_cap(task, running, step_caps):
            return ready.popleft()
        ready.rotate(-1)
    return None


def _submit_ready_tasks(ready: deque[Task], running: dict[Future[list[ExperimentState]], Task], max_running: int, executor: ThreadPoolExecutor, *, step_caps: Mapping[str, int], ctx: ExecutionContext, settings_by_step: Mapping[str, Any], step_specs: Mapping[str, StepSpec[Any]]) -> None:
    while ready and len(running) < max_running:
        task = _pop_next_eligible_task(ready, running, step_caps)
        if task is None:
            # No currently eligible task due to per-step running caps.
            return

        _submit_task(
            task,
            executor,
            running,
            ctx=ctx,
            settings_by_step=settings_by_step,
            step_specs=step_specs,
        )


def _drain_completed_tasks(done: set[Future[list[ExperimentState]]], *, cpu_running: dict[Future[list[ExperimentState]], Task], gpu_running: dict[Future[list[ExperimentState]], Task], enabled_steps: list[str], step_specs: Mapping[str, StepSpec[Any]], cpu_ready: deque[Task], gpu_ready: deque[Task], final_states: list[ExperimentState], pb: ProgressBar) -> int:
    newly_queued = 0

    for fut in done:
        task = cpu_running.pop(fut, None)
        if task is None:
            task = gpu_running.pop(fut)

        produced_states = fut.result()
        pb.advance()
        logger.debug("Completed %s for %s -> produced %d state(s)", task.step_name, _task_label(task), len(produced_states))

        next_step = _next_enabled_step(task.step_name, enabled_steps)
        for produced_state in produced_states:
            if next_step is None:
                final_states.append(produced_state)
                continue

            next_task = Task(step_name=next_step, exp_state=produced_state)
            newly_queued += 1
            logger.debug("Queued %s for %s", next_step, produced_state.experiment_id or produced_state.original_image_rel.as_posix())
            _enqueue_task(next_task, step_specs, cpu_ready, gpu_ready)

    return newly_queued



