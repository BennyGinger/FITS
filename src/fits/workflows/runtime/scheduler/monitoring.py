import logging
from collections import deque

from fits.workflows.runtime.scheduler.dispatch import RunningTasks, Task
from fits.workflows.runtime.scheduler.planning import RuntimeStep


logger = logging.getLogger(__name__)
WAIT_HEARTBEAT_SECONDS = 60.0


def log_scheduler_heartbeat(*, cpu_ready: deque[Task], gpu_ready: deque[Task],
                            cpu_running: RunningTasks,
                            gpu_running: RunningTasks,
                            runtime_steps: list[RuntimeStep]) -> None:
    """
    Log queued and active work after a period without completion.
    """
    running_labels = [(str(runtime_steps[task.step_index].spec.profile.step_name),
                    task.state.experiment_id)
                    for task in (*cpu_running.values(), *gpu_running.values())]
    logger.warning("Scheduler heartbeat: no completion for %.1fs | "
                    "running=%d ready_cpu=%d ready_gpu=%d in_flight=%s",
                    WAIT_HEARTBEAT_SECONDS,
                    len(cpu_running) + len(gpu_running),
                    len(cpu_ready), len(gpu_ready), running_labels)
