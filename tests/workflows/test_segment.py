from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import importlib

import numpy as np
import pytest

from fits.environment.constant import StepName
from fits.environment.state import ExperimentState
from fits.settings.models import SegmentChannelSettings, SegmentSettings
from fits.tasks.segmentation.segment import segment
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.errors import StepExecutionError


segment_module = importlib.import_module("fits.tasks.segmentation.segment")


class DummyReader:
    channel_labels = ["GFP", "RFP", "DAPI"]
    axes = "CYX"

    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.save_calls: list[dict[str, Any]] = []
        self.get_channel_calls: list[list[str]] = []

    def labels_to_indices(self, labels: list[str]) -> list[int]:
        return [self.channel_labels.index(label) for label in labels]

    def indices_to_labels(self, indices: list[int]) -> list[str]:
        return [self.channel_labels[index] for index in indices]

    def get_channel(self, labels: list[str]) -> SimpleNamespace:
        self.get_channel_calls.append(labels)
        return SimpleNamespace(array=np.ones((len(labels), 4, 4), dtype=np.uint16), axes="CYX")

    def merge_channels(self, **kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(array=kwargs["new_array"], axes=kwargs["new_axes"], channel_indices=kwargs["new_channel_indices"])

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        self.save_calls.append({"array": array, **kwargs})
        self.output_path.write_bytes(b"")
        return self.output_path


class DummyWrapper:
    output_axis_order = "CYX"

    def __init__(self) -> None:
        self.setup_called = False
        self.run_calls: list[tuple[np.ndarray, str]] = []

    def setup(self) -> None:
        self.setup_called = True

    def run(self, array: np.ndarray, axes: str) -> np.ndarray:
        self.run_calls.append((array, axes))
        return np.full((1, 4, 4), 7, dtype=np.uint16)


def _image_state(tmp_path: Path) -> ExperimentState:
    raw = tmp_path / "raw.nd2"
    image = tmp_path / "fits_array.tif"
    raw.write_bytes(b"")
    image.write_bytes(b"")
    return ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image",
        artifact_path=image,
    )


def test_segment_requires_image_artifact(tmp_path: Path) -> None:
    raw = tmp_path / "raw.nd2"
    raw.write_bytes(b"")
    state = ExperimentState.init(tmp_path, raw)

    with pytest.raises(StepExecutionError, match="missing 'image' input"):
        segment(
            SegmentSettings(channels=[SegmentChannelSettings(channel="RFP")]),
            state,
            REGISTRY[StepName.SEGMENT].profile,
        )


def test_segment_requires_a_configured_channel(tmp_path: Path) -> None:
    with pytest.raises(StepExecutionError, match="At least one segmentation channel"):
        segment(
            SegmentSettings(),
            _image_state(tmp_path),
            REGISTRY[StepName.SEGMENT].profile,
        )


def test_segment_processes_pending_channels_and_saves(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(tmp_path / "fits_mask.tif")
    wrapper = DummyWrapper()
    monkeypatch.setattr(segment_module.FitsIO, "from_path", lambda path: reader)
    monkeypatch.setattr(
        segment_module,
        "decide_run",
        lambda *args: SimpleNamespace(is_complete=False, pending_items=[1]),
    )
    monkeypatch.setattr(
        segment_module.CellposeWrapper,
        "from_dict",
        lambda payload: wrapper,
    )

    results = segment(
        SegmentSettings(channels=[
            SegmentChannelSettings(channel="GFP", nuclear_channel="DAPI"),
            SegmentChannelSettings(channel="RFP", nuclear_channel="DAPI"),
        ]),
        _image_state(tmp_path),
        REGISTRY[StepName.SEGMENT].profile,
    )

    assert results[0].last_step == StepName.SEGMENT
    assert results[0].artifact("segmentation") == tmp_path / "fits_mask.tif"
    assert reader.get_channel_calls == [["RFP", "DAPI"]]
    assert wrapper.setup_called
    assert wrapper.run_calls[0][1] == "CYX"
    assert reader.save_calls[0]["export_channels"] == ["RFP"]
    assert reader.save_calls[0]["artifact_kind"] == "segmentation"


def test_segment_skips_when_requested_channels_are_complete(monkeypatch, tmp_path: Path) -> None:
    state = _image_state(tmp_path)
    reader = DummyReader(tmp_path / "fits_mask.tif")
    monkeypatch.setattr(segment_module.FitsIO, "from_path", lambda path: reader)
    monkeypatch.setattr(
        segment_module,
        "decide_run",
        lambda *args: SimpleNamespace(is_complete=True),
    )
    monkeypatch.setattr(
        segment_module.CellposeWrapper,
        "from_dict",
        lambda payload: (_ for _ in ()).throw(AssertionError("wrapper should not be created")),
    )

    assert segment(
        SegmentSettings(channels=[SegmentChannelSettings(channel="GFP")]),
        state,
        REGISTRY[StepName.SEGMENT].profile,
    ) == [state]
    assert reader.save_calls == []


def test_segment_uses_independent_settings_and_saves_once(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(tmp_path / "fits_mask.tif")
    wrappers = [DummyWrapper(), DummyWrapper()]
    payloads: list[dict[str, Any]] = []
    monkeypatch.setattr(segment_module.FitsIO, "from_path", lambda path: reader)
    monkeypatch.setattr(
        segment_module,
        "decide_run",
        lambda *args: SimpleNamespace(is_complete=False, pending_items=[0, 2]),
    )

    def wrapper_from_dict(payload: dict[str, Any]) -> DummyWrapper:
        payloads.append(payload)
        return wrappers[len(payloads) - 1]

    monkeypatch.setattr(segment_module.CellposeWrapper, "from_dict", wrapper_from_dict)

    segment(
        SegmentSettings.model_validate({
            "channels": [
                {"channel": "GFP", "user_settings": {"model_type": "cyto2"}},
                {"channel": "DAPI", "do_denoise": False,
                 "user_settings": {"model_type": "nuclei"}},
            ],
        }),
        _image_state(tmp_path),
        REGISTRY[StepName.SEGMENT].profile,
    )

    assert [payload["user_settings"]["model_type"] for payload in payloads] == ["cyto2", "nuclei"]
    assert payloads[1]["do_denoise"] is False
    assert reader.get_channel_calls == [["GFP"], ["DAPI"]]
    assert len(reader.save_calls) == 1
    assert reader.save_calls[0]["export_channels"] == ["GFP", "DAPI"]


def test_segment_failure_does_not_save_partial_output(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(tmp_path / "fits_mask.tif")
    first = DummyWrapper()
    monkeypatch.setattr(segment_module.FitsIO, "from_path", lambda path: reader)
    monkeypatch.setattr(
        segment_module,
        "decide_run",
        lambda *args: SimpleNamespace(is_complete=False, pending_items=[0, 2]),
    )

    calls = 0

    def wrapper_from_dict(payload: dict[str, Any]) -> DummyWrapper:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("model unavailable")
        return first

    monkeypatch.setattr(segment_module.CellposeWrapper, "from_dict", wrapper_from_dict)

    with pytest.raises(StepExecutionError, match="channel 'DAPI'.*model unavailable"):
        segment(
            SegmentSettings.model_validate({
                "channels": [{"channel": "GFP"}, {"channel": "DAPI"}],
            }),
            _image_state(tmp_path),
            REGISTRY[StepName.SEGMENT].profile,
        )

    assert reader.save_calls == []
