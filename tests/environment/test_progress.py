from fits.environment.progress import (
    RunProgress,
    StageStatus,
    WorkflowStage,
)


def test_run_progress_tracks_stages_and_conversion_branches() -> None:
    changes = []
    progress = RunProgress(changes.append)
    progress.add("raw", {WorkflowStage.CONVERT, WorkflowStage.DRAWING})

    assert progress.experiment("raw").stage(
        WorkflowStage.CONVERT).status == StageStatus.PENDING
    assert progress.experiment("raw").stage(WorkflowStage.PROCESS) is None

    progress.update("raw", WorkflowStage.CONVERT, StageStatus.ACTIVE)
    progress.update("raw", WorkflowStage.CONVERT, StageStatus.COMPLETED)
    progress.replace_experiment("raw", ("series_0", "series_1"))

    assert {item.experiment_id for item in progress.snapshot()} == {
        "series_0", "series_1"}
    assert progress.experiment("series_0").stage(
        WorkflowStage.CONVERT).status == StageStatus.COMPLETED
    assert changes[-1].experiment_id == "series_1"


def test_stage_progress_keeps_failure_detail() -> None:
    progress = RunProgress()
    progress.add("experiment", WorkflowStage)
    progress.update("experiment", WorkflowStage.DRAWING, StageStatus.COMPLETED)
    progress.update("experiment", WorkflowStage.ANALYSIS, StageStatus.FAILED,
                    error="broken extraction")

    drawing = progress.experiment("experiment").stage(WorkflowStage.DRAWING)
    analysis = progress.experiment("experiment").stage(WorkflowStage.ANALYSIS)
    assert drawing.status == StageStatus.COMPLETED
    assert analysis.error == "broken extraction"


def test_skip_unfinished_preserves_terminal_stages() -> None:
    progress = RunProgress()
    progress.add("experiment", WorkflowStage)
    progress.update("experiment", WorkflowStage.CONVERT, StageStatus.COMPLETED)
    progress.update("experiment", WorkflowStage.DRAWING, StageStatus.ACTIVE)

    progress.skip_unfinished()

    result = progress.experiment("experiment")
    assert result.stage(WorkflowStage.CONVERT).status == StageStatus.COMPLETED
    assert result.stage(WorkflowStage.DRAWING).status == StageStatus.SKIPPED
    assert result.stage(WorkflowStage.ANALYSIS).status == StageStatus.SKIPPED
