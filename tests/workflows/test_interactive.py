from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from queue import Queue
from threading import Event
from time import monotonic, sleep
from types import SimpleNamespace

import numpy as np
import pytest
import tifffile

from fits.environment.constant import ARTI_IMG, StepName
from fits.environment.progress import RunProgress, StageStatus, WorkflowStage
from fits.environment.state import ExperimentState
from fits.settings.models import DistanceProfileSettings, ExtractSettings
from fits.sessions.collection import MaskCollectionOutcome
from fits.tasks.reference_mask import ReferenceMaskSession
from fits.workflows.interactive import MaskInteraction, PipelineCancelled, run_interactive_workflow, _existing_outcome


def state(tmp_path, name):
    folder = tmp_path / name
    folder.mkdir()
    image = folder / 'fits_array.tif'
    tifffile.imwrite(image, np.arange(64, dtype=np.uint16).reshape(8, 8), imagej=True, metadata={'axes': 'YX'})
    session = ReferenceMaskSession(image)
    session.set_mask_plane(np.ones((8, 8), dtype=np.uint8))
    session.save('edge')
    return ExperimentState(workdir=folder, artifacts={ARTI_IMG: image})


def step(name, runner, settings=None):
    return SimpleNamespace(settings=settings, spec=SimpleNamespace(
        profile=SimpleNamespace(step_name=name), item_runner=runner))


def test_queue_grows_and_each_experiment_waits_for_its_own_masks(tmp_path, monkeypatch):
    states = [state(tmp_path, 'a'), state(tmp_path, 'b')]
    prepared, analysed = [], []
    analysis_done = Event()
    def prepare(settings, current, profile):
        prepared.append(current.workdir.name)
        return [current]
    def analyse(settings, current, profile):
        analysed.append(current.workdir.name)
        analysis_done.set()
        return [current]
    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [
        step(StepName.BG_SUB, prepare),
        step(StepName.DISTANCE_PROFILE, analyse, DistanceProfileSettings())])
    requests = Queue()
    input_done = Event()
    interaction = MaskInteraction(requests.put, input_done.set)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_interactive_workflow, {}, states, interaction)
        try:
            first = requests.get(timeout=5)
            second = requests.get(timeout=5)
            assert prepared == ['a', 'b']
            assert analysed == []
            assert input_done.wait(5)
            interaction.resolve(_existing_outcome(second))
            assert analysis_done.wait(5)
            assert analysed == ['b']
            interaction.resolve(_existing_outcome(first))
            assert len(future.result(timeout=5)) == 2
            assert analysed == ['b', 'a']
        finally:
            interaction.cancel()


def test_raw_files_in_same_folder_have_separate_progress_entries(tmp_path, monkeypatch):
    folder = tmp_path / 'condition'
    folder.mkdir()
    originals = []
    for name in ('first.nd2', 'second.nd2'):
        raw = folder / name
        raw.touch()
        originals.append(ExperimentState.init(folder, raw))

    def convert(settings, current, profile):
        output = current.workdir / f'{current.original_image.stem}_s1'
        output.mkdir()
        image = output / 'fits_array.tif'
        tifffile.imwrite(image, np.ones((8, 8), dtype=np.uint16), imagej=True,
                         metadata={'axes': 'YX'})
        converted = ExperimentState.init(output, current.original_image)
        return [converted.with_complete_step(
            step_name=StepName.CONVERT, artifact_kind=ARTI_IMG,
            artifact_path=image)]

    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [
        step(StepName.CONVERT, convert)])
    interaction = MaskInteraction(lambda request: interaction.resolve(_existing_outcome(request)))
    progress = RunProgress()

    run_interactive_workflow({}, originals, interaction, progress=progress)
    assert len(progress.snapshot()) == 2


def test_reference_skip_omits_profile_but_allows_extraction(tmp_path, monkeypatch):
    current = state(tmp_path, 'a')
    (current.workdir / 'fits_ref_edge.tif').unlink()
    ran = []
    def runner(settings, current, profile):
        ran.append(profile.step_name)
        return [current]
    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [
        step(StepName.DISTANCE_PROFILE, runner, DistanceProfileSettings()),
        step(StepName.EXTRACT, runner, ExtractSettings())])
    interaction = MaskInteraction(lambda request: interaction.resolve(_existing_outcome(request)))
    assert run_interactive_workflow({}, [current], interaction) == [current]
    assert ran == [StepName.EXTRACT]


def test_finish_drawing_handles_later_arrivals_without_reopening_gui(tmp_path, monkeypatch):
    states = [state(tmp_path, 'a'), state(tmp_path, 'b')]
    calls = []
    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [
        step(StepName.DISTANCE_PROFILE, lambda settings, current, profile: [current], DistanceProfileSettings())])
    def request_mask(request):
        calls.append(request)
        interaction.finish()
    interaction = MaskInteraction(request_mask)
    assert len(run_interactive_workflow({}, states, interaction)) == 2
    assert len(calls) == 1


def test_cancel_interrupts_long_demo_pause(tmp_path, monkeypatch):
    current = state(tmp_path, 'a')
    started = Event()
    def prepare(settings, current, profile):
        started.set()
        return [current]
    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [step(StepName.BG_SUB, prepare)])
    interaction = MaskInteraction(lambda request: pytest.fail('Cancelled request must not open'))
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(run_interactive_workflow, {}, [current], interaction, step_delay_seconds=30)
        assert started.wait(5)
        interaction.cancel()
        with pytest.raises(PipelineCancelled):
            future.result(timeout=3)


def test_preparation_error_propagates_without_waiting_for_user(tmp_path, monkeypatch):
    current = state(tmp_path, 'a')
    def fail(*args):
        raise ValueError('broken preparation')
    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [step(StepName.BG_SUB, fail)])
    interaction = MaskInteraction(lambda request: None)
    with pytest.raises(ValueError, match='broken preparation'):
        run_interactive_workflow({}, [current], interaction)


def test_changed_mask_manifest_stops_analysis(tmp_path, monkeypatch):
    current = state(tmp_path, 'a')
    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [
        step(StepName.DISTANCE_PROFILE, lambda *args: pytest.fail('Must not run analysis'), DistanceProfileSettings())])
    def request_masks(request):
        outcome = _existing_outcome(request)
        outcome.reference_paths[0].unlink()
        interaction.resolve(outcome)
    interaction = MaskInteraction(request_masks)
    with pytest.raises(ValueError, match='changed after finalization'):
        run_interactive_workflow({}, [current], interaction)


def test_progress_records_parallel_process_and_drawing_join(tmp_path, monkeypatch):
    current = state(tmp_path, 'a')
    requests = Queue()
    analysed = Event()
    progress = RunProgress()

    def runner(settings, state, profile):
        if profile.step_name == StepName.DISTANCE_PROFILE:
            analysed.set()
        return [state]

    monkeypatch.setattr('fits.workflows.interactive._resolve_runtime_steps', lambda cfg: [
        step(StepName.BG_SUB, runner),
        step(StepName.SEGMENT, runner),
        step(StepName.DISTANCE_PROFILE, runner, DistanceProfileSettings()),
    ])
    interaction = MaskInteraction(requests.put)
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            run_interactive_workflow, {}, [current], interaction,
            progress=progress)
        request = requests.get(timeout=5)
        deadline = monotonic() + 5
        while (progress.experiment(current.experiment_id).stage(
                WorkflowStage.PROCESS).status != StageStatus.COMPLETED
                and monotonic() < deadline):
            sleep(.01)

        before_drawing = progress.experiment(current.experiment_id)
        assert before_drawing.stage(WorkflowStage.PREPROCESS).status == StageStatus.COMPLETED
        assert before_drawing.stage(WorkflowStage.PROCESS).status == StageStatus.COMPLETED
        assert before_drawing.stage(WorkflowStage.DRAWING).status == StageStatus.ACTIVE
        assert before_drawing.stage(WorkflowStage.ANALYSIS).status == StageStatus.PENDING
        assert not analysed.is_set()

        interaction.resolve(_existing_outcome(request))
        assert future.result(timeout=5) == [current]

    finished = progress.experiment(current.experiment_id)
    assert finished.stage(WorkflowStage.DRAWING).status == StageStatus.COMPLETED
    assert finished.stage(WorkflowStage.ANALYSIS).status == StageStatus.COMPLETED
