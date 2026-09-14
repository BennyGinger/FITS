"""Record ordinary workflow execution using the same stages as the GUI."""
from fits.environment.progress import RunProgress, StageStatus, WorkflowStage


STEP_STAGES = {
    "convert": WorkflowStage.CONVERT,
    "register_time": WorkflowStage.PREPROCESS,
    "register_channel": WorkflowStage.PREPROCESS,
    "bg_sub": WorkflowStage.PREPROCESS,
    "segment": WorkflowStage.PROCESS,
    "track": WorkflowStage.PROCESS,
    "extract": WorkflowStage.ANALYSIS,
    "distance_profile": WorkflowStage.ANALYSIS,
}


class WorkflowReporter:
    def __init__(self, progress: RunProgress, steps, states):
        self.progress = progress
        self.last_steps = {STEP_STAGES[step]: step for step in steps}
        for state in states:
            progress.add(self.key(state), self.last_steps)

    @staticmethod
    def key(state):
        if state.artifact("image") is None:
            return state.original_image.as_posix()
        return state.experiment_id

    def started(self, step, state):
        self.progress.update(self.key(state), STEP_STAGES[step], StageStatus.ACTIVE)

    def completed(self, step, state, outputs):
        key = self.key(state)
        stage = STEP_STAGES[step]
        if not outputs:
            self.progress.update(key, stage, StageStatus.SKIPPED,
                                 detail="Step produced no output experiments.")
            self.progress.skip_pending(key, detail="No output from the preceding step.")
            return
        if self.last_steps[stage] == step:
            self.progress.update(key, stage, StageStatus.COMPLETED)
        self.progress.replace_experiment(key, [self.key(output) for output in outputs])

    def failed(self, step, state, error):
        key = self.key(state)
        self.progress.update(key, STEP_STAGES[step], StageStatus.FAILED, error=str(error))
        self.progress.skip_pending(key, detail=f"Not run because {step} failed.")

    def run(self, runner, settings, state, profile):
        """Finish recording before the future resolves, including on failure."""
        self.started(profile.step_name, state)
        try:
            outputs = runner(settings, state, profile)
        except Exception as error:
            self.failed(profile.step_name, state, error)
            raise
        self.completed(profile.step_name, state, outputs)
        return outputs
