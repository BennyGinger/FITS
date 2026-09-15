from pathlib import Path
import importlib

import numpy as np
import pytest
from tifffile import imwrite
from fits_io import FitsIO

from fits.environment.constant import StepName
from fits.workflows.experiments import ExperimentState
from fits.settings.models import ConvertSettings, TrackSettings
from fits.tasks.convert import convert
from fits.tasks.tracking.track import track
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.runtime.errors import StepExecutionError


backend_module = importlib.import_module("fits.tasks.tracking.backend")
PROFILE = REGISTRY[StepName.TRACK].profile


def segmented_state(tmp_path: Path) -> ExperimentState:
    raw = tmp_path / "input.tif"
    images = np.empty((3, 3, 4, 5), dtype=np.uint16)
    for index in range(3):
        images[:, index] = (index + 1) * 100
    imwrite(raw, images, imagej=True, metadata={"axes": "TCYX"})
    state = convert(
        ConvertSettings(channel_labels=["GFP", "DAPI", "RFP"]),
        ExperimentState.init(tmp_path, raw),
        REGISTRY[StepName.CONVERT].profile,
    )[0]
    reader = FitsIO.from_path(state.artifact("image"))
    # Store a reordered subset to exercise source-channel identity, not merely
    # matching array positions between the image and segmentation artifacts.
    masks = np.empty((3, 2, 4, 5), dtype=np.uint16)
    masks[:, 0] = 3
    masks[:, 1] = 1
    path = reader.save_array(
        masks, output_name="fits_mask.tif",
        export_channels=["RFP", "GFP"], artifact_kind="segmentation")
    return state.with_complete_step(
        step_name=StepName.SEGMENT, artifact_kind="segmentation", artifact_path=path)


class Tracker:
    def __init__(self):
        self.calls = []
        self.fail_on = None

    def configure(self, settings):
        pass

    def track(self, image, mask):
        assert image.shape == mask.shape == (3, 4, 5)
        np.testing.assert_array_equal(image, mask * 100)
        self.calls.append(int(mask[0, 0, 0]))
        if self.calls[-1] == self.fail_on:
            raise ValueError("tracking failed")
        return mask + 10


@pytest.mark.parametrize("channels", [["GFP", "RFP"], ["RFP", "GFP"], ["RFP"]])
@pytest.mark.parametrize("postprocess", [False, True])
def test_tracking_channels_are_independent_and_keep_identity(
    monkeypatch, tmp_path, channels, postprocess,
):
    state = segmented_state(tmp_path)
    tracker = Tracker()
    monkeypatch.setattr(backend_module, "TrackModel", lambda **kwargs: tracker)
    result = track(
        TrackSettings(channel_to_track=channels,
                      postprocess={"enabled": postprocess, "minimum_appearances": 1}),
        state, PROFILE,
    )[0]
    expected_indices = [{"GFP": 0, "RFP": 2}[label] for label in channels]
    assert tracker.calls == [index + 1 for index in expected_indices]
    output = FitsIO.from_path(result.artifact("tracking"))
    assert output.channel_labels == channels
    assert output.artifact_channel_indices == expected_indices
    for label, index in zip(channels, expected_indices):
        np.testing.assert_array_equal(
            output.get_channel(label).array, np.full((3, 4, 5), index + 11))
    assert result.completed_channels(StepName.TRACK) == expected_indices


def test_tracking_only_adds_missing_channels_and_can_overwrite(monkeypatch, tmp_path):
    state = segmented_state(tmp_path)
    tracker = Tracker()
    monkeypatch.setattr(backend_module, "TrackModel", lambda **kwargs: tracker)
    first = track(TrackSettings(channel_to_track=["GFP"]), state, PROFILE)[0]
    result = track(TrackSettings(channel_to_track=["GFP", "RFP"]), first, PROFILE)[0]
    assert tracker.calls == [1, 3]
    output = FitsIO.from_path(result.artifact("tracking"))
    assert output.channel_labels == ["GFP", "RFP"]
    assert output.artifact_channel_indices == [0, 2]
    assert track(TrackSettings(channel_to_track=["GFP", "RFP"]), result, PROFILE) == [result]
    assert tracker.calls == [1, 3]
    track(TrackSettings(channel_to_track=["GFP", "RFP"], overwrite=True), result, PROFILE)
    assert tracker.calls == [1, 3, 1, 3]


def test_channel_failure_does_not_replace_existing_tracking(monkeypatch, tmp_path):
    state = segmented_state(tmp_path)
    tracker = Tracker()
    monkeypatch.setattr(backend_module, "TrackModel", lambda **kwargs: tracker)
    first = track(TrackSettings(channel_to_track=["GFP"]), state, PROFILE)[0]
    output_path = first.artifact("tracking")
    saved_output = output_path.read_bytes()
    state_path = first.workdir / "experiment_state.json"
    saved_state = state_path.read_bytes()
    tracker.fail_on = 3
    with pytest.raises(StepExecutionError, match="channel 'RFP'.*tracking failed"):
        track(TrackSettings(channel_to_track=["GFP", "RFP"], overwrite=True), first, PROFILE)
    assert output_path.read_bytes() == saved_output
    assert state_path.read_bytes() == saved_state
