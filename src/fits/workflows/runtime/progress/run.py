"""Thread-safe progress coordination for an active workflow run."""

from collections.abc import Callable, Iterable
from dataclasses import replace
from threading import RLock

from fits.workflows.runtime.progress.models import ExperimentProgress, StageProgress, StageStatus, WorkflowStage


class RunProgress:
    """
    Track workflow-stage progress for every experiment in one run.
    """
    def __init__(self, on_change: Callable[[ExperimentProgress], None] | None = None,) -> None:
        self._experiments: dict[str, ExperimentProgress] = {}
        self._lock = RLock()
        self._on_change = on_change

    def add(self, experiment_id: str, required: Iterable[WorkflowStage],) -> ExperimentProgress:
        """
        Add an experiment with its required stages pending.
        """
        stages = {stage: StageProgress() for stage in set(required)}
        with self._lock:
            progress = ExperimentProgress(experiment_id, stages)
            self._experiments[experiment_id] = progress
        self._notify(progress)
        return progress

    def replace_experiment(self, source_id: str, output_ids: Iterable[str],) -> None:
        """
        Replace a pre-conversion input with its materialized branches.
        """
        output_ids = tuple(dict.fromkeys(output_ids))
        with self._lock:
            source = self._experiments[source_id]
            if output_ids == (source_id,):
                return
            del self._experiments[source_id]
            created = []
            for output_id in output_ids:
                progress = ExperimentProgress(output_id, dict(source.stages))
                self._experiments[output_id] = progress
                created.append(progress)
        for progress in created:
            self._notify(progress)

    def update(self,
                experiment_id: str,
                stage: WorkflowStage,
                status: StageStatus,
                *,
                error: str | None = None,
                detail: str | None = None,
                ) -> ExperimentProgress:
        """
        Update one experiment stage.
        """
        with self._lock:
            current = self._experiments[experiment_id]
            stages = dict(current.stages)
            stages[stage] = StageProgress(status=status, error=error, detail=detail)
            updated = ExperimentProgress(experiment_id, stages)
            self._experiments[experiment_id] = updated
        self._notify(updated)
        return updated

    def experiment(self, experiment_id: str) -> ExperimentProgress:
        """
        Return a defensive copy of one experiment's current progress.
        """
        with self._lock:
            current = self._experiments[experiment_id]
            return ExperimentProgress(current.experiment_id, dict(current.stages))

    def snapshot(self) -> tuple[ExperimentProgress, ...]:
        """
        Return a defensive snapshot of all experiment progress.
        """
        with self._lock:
            return tuple(ExperimentProgress(item.experiment_id, dict(item.stages))
                        for item in self._experiments.values())

    def skip_unfinished(self) -> None:
        """
        Mark every pending or active stage skipped when a run stops.
        """
        unfinished = {StageStatus.PENDING, StageStatus.ACTIVE}
        with self._lock:
            changed = []
            for experiment_id, current in self._experiments.items():
                stages = {stage: replace(value, status=StageStatus.SKIPPED)
                            if value.status in unfinished else value
                            for stage, value in current.stages.items()}
                updated = ExperimentProgress(experiment_id, stages)
                self._experiments[experiment_id] = updated
                changed.append(updated)
        for progress in changed:
            self._notify(progress)

    def skip_pending(self, experiment_id: str, *, detail: str | None = None,) -> ExperimentProgress:
        """
        Skip downstream stages that did not start after a failure.
        """
        with self._lock:
            current = self._experiments[experiment_id]
            stages = {stage: replace(value, status=StageStatus.SKIPPED, 
                                     detail=detail)
                        if value.status == StageStatus.PENDING else value
                        for stage, value in current.stages.items()}
            updated = ExperimentProgress(experiment_id, stages)
            self._experiments[experiment_id] = updated
        self._notify(updated)
        return updated

    def _notify(self, progress: ExperimentProgress) -> None:
        """
        Send a defensive progress snapshot to the registered callback.
        """
        if self._on_change is not None:
            self._on_change(ExperimentProgress(
                progress.experiment_id, dict(progress.stages)))
