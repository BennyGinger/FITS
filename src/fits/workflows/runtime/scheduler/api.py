"""Public orchestration for the concurrent workflow scheduler."""

import logging
import os
from collections import deque
from collections.abc import Mapping
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Any

from progress_bar import pbar

from fits.workflows.runtime.progress import RunProgress
from fits.workflows.experiments import ExperimentState
from fits.workflows.runtime.progress.reporting import WorkflowReporter
from fits.workflows.runtime.scheduler.dispatch import (
    RunningTasks, Task, process_completed_tasks, submit_ready_tasks)
from fits.workflows.runtime.scheduler.monitoring import (
    WAIT_HEARTBEAT_SECONDS, log_scheduler_heartbeat)
from fits.workflows.runtime.scheduler.planning import resolve_runtime_steps
from fits.workflows.definitions.models import require_automatic_specs


logger = logging.getLogger(__name__)


def run_workflow_scheduler(effective_cfg: Mapping[str, Any],
                           exp_states: list[ExperimentState], *,
                           run_progress: RunProgress | None = None,
                           ) -> list[ExperimentState]:
    """
    Execute configured steps as a concurrent CPU/GPU conveyor pipeline.
    """
    runtime_steps = resolve_runtime_steps(effective_cfg)
    require_automatic_specs(step.spec for step in runtime_steps)
    if run_progress is not None:
        reporter = WorkflowReporter(run_progress,
                                    [step.spec.profile.step_name for step in runtime_steps],
                                    exp_states,)
    else:
        reporter = None
    
    if not runtime_steps:
        return exp_states

    logger.info("Scheduler starting with enabled steps: %s",
                [str(step.spec.profile.step_name) for step in runtime_steps])
    cpu_ready = deque(Task(step_index=0, state=state) for state in exp_states)
    gpu_ready: deque[Task] = deque()
    if runtime_steps[0].spec.pool == "gpu":
        gpu_ready.extend(cpu_ready)
        cpu_ready.clear()

    cpu_workers = os.cpu_count() or 1
    final_states: list[ExperimentState] = []
    with (ThreadPoolExecutor(max_workers=cpu_workers) as cpu_executor,
          ThreadPoolExecutor(max_workers=1) as gpu_executor,
          pbar(total=len(exp_states), desc="Pipeline", logs="off") as progress,):
        cpu_running: RunningTasks = {}
        gpu_running: RunningTasks = {}
        total_tasks = len(exp_states)
        
        while cpu_ready or gpu_ready or cpu_running or gpu_running:
            submit_ready_tasks(ready=cpu_ready, 
                               running=cpu_running, 
                               max_running=cpu_workers,
                               executor=cpu_executor, 
                               runtime_steps=runtime_steps,
                               reporter=reporter)
            submit_ready_tasks(ready=gpu_ready, 
                               running=gpu_running, 
                               max_running=1,
                               executor=gpu_executor, 
                               runtime_steps=runtime_steps,
                               reporter=reporter)
            running_futures = set(cpu_running) | set(gpu_running)
            if not running_futures:
                break
            done, _ = wait(running_futures, timeout=WAIT_HEARTBEAT_SECONDS,
                            return_when=FIRST_COMPLETED)
            if not done:
                log_scheduler_heartbeat(cpu_ready=cpu_ready, 
                                        gpu_ready=gpu_ready,
                                        cpu_running=cpu_running, 
                                        gpu_running=gpu_running,
                                        runtime_steps=runtime_steps)
                continue
            queued_count = process_completed_tasks(done=done, 
                                                   cpu_running=cpu_running, 
                                                   gpu_running=gpu_running,
                                                   runtime_steps=runtime_steps, 
                                                   cpu_ready=cpu_ready,
                                                   gpu_ready=gpu_ready, 
                                                   final_states=final_states,
                                                   progress=progress)
            if queued_count:
                total_tasks += queued_count
                progress.update(total=total_tasks)

    logger.info("Scheduler completed with %d terminal states", len(final_states))
    return final_states
