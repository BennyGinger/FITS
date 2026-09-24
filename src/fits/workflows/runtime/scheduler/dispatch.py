import logging
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass

from progress_bar.api import ProgressBar

from fits.workflows.experiments import ExperimentState
from fits.workflows.definitions.models import item_runner_for
from fits.workflows.runtime.progress.reporting import WorkflowReporter
from fits.workflows.runtime.scheduler.planning import RuntimeStep


logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class Task:
    """
    Identify an experiment state and the next runtime step it must execute.
    """
    step_index: int
    state: ExperimentState


FutureResult = Future[list[ExperimentState]]
RunningTasks = dict[FutureResult, Task]


def submit_ready_tasks(*, ready: deque[Task], running: RunningTasks,
                       max_running: int, executor: ThreadPoolExecutor,
                       runtime_steps: list[RuntimeStep],
                       reporter: WorkflowReporter | None = None) -> None:
    """
    Submit eligible queued tasks until the executor reaches its capacity.
    """
    while ready and len(running) < max_running:
        task = _pop_eligible_task(ready=ready, running=running, runtime_steps=runtime_steps)
        if task is None:
            return
        
        runtime_step = runtime_steps[task.step_index]
        profile = runtime_step.spec.profile
        item_runner = item_runner_for(runtime_step.spec)
        logger.debug("Submitting %s for %s", profile.step_name, task.state.experiment_id)
        
        if reporter is not None:
            future = executor.submit(reporter.run, 
                                     item_runner,
                                     runtime_step.settings, 
                                     task.state, 
                                     profile)
        else:
            future = executor.submit(item_runner, runtime_step.settings, task.state, profile)
        running[future] = task


def _pop_eligible_task(*, 
                       ready: deque[Task], 
                       running: RunningTasks,
                       runtime_steps: list[RuntimeStep]
                       ) -> Task | None:
    """
    Return the next task that does not exceed its step concurrency cap.
    """
    for _ in range(len(ready)):
        task = ready[0]
        if _within_step_cap(task=task, running=running, runtime_steps=runtime_steps):
            return ready.popleft()
        ready.rotate(-1)
    return None


def _within_step_cap(*, 
                     task: Task, 
                     running: RunningTasks,
                     runtime_steps: list[RuntimeStep]
                     ) -> bool:
    """
    Return whether another task may run under its step concurrency limit.
    """
    cap = runtime_steps[task.step_index].spec.max_concurrency
    if cap is None:
        return True
    running_for_step = sum(running_task.step_index == task.step_index
                            for running_task in running.values())
    return running_for_step < cap


def process_completed_tasks(*, 
                            done: set[FutureResult],
                            cpu_running: RunningTasks,
                            gpu_running: RunningTasks,
                            runtime_steps: list[RuntimeStep],
                            cpu_ready: deque[Task], gpu_ready: deque[Task],
                            final_states: list[ExperimentState],
                            progress: ProgressBar
                            ) -> int:
    """
    Collect finished tasks and queue their output states for the next step.
    """
    queued_count = 0
    for future in done:
        task = cpu_running.pop(future, None)
        if task is None:
            task = gpu_running.pop(future)
        
        runtime_step = runtime_steps[task.step_index]
        produced_states = future.result()
        progress.advance()
        logger.debug("Completed %s for %s; produced %d state(s)",
                    runtime_step.spec.profile.step_name, task.state.experiment_id,
                    len(produced_states))
        next_step_index = task.step_index + 1
        
        for state in produced_states:
            if next_step_index >= len(runtime_steps):
                final_states.append(state)
                continue
            _enqueue_task(Task(step_index=next_step_index, state=state),
                        runtime_steps=runtime_steps,
                        cpu_ready=cpu_ready,
                        gpu_ready=gpu_ready)
            queued_count += 1
    return queued_count


def _enqueue_task(task: Task, 
                  *, 
                  runtime_steps: list[RuntimeStep],
                  cpu_ready: deque[Task], 
                  gpu_ready: deque[Task]
                  ) -> None:
    """
    Place a task in the queue selected by its next step's execution pool.
    """
    pool = runtime_steps[task.step_index].spec.pool
    if pool == "cpu":
        cpu_ready.append(task)
    elif pool == "gpu":
        gpu_ready.append(task)
    else:
        step_name = runtime_steps[task.step_index].spec.profile.step_name
        raise ValueError(f"Unsupported pool {pool!r} for step {str(step_name)!r}.")
