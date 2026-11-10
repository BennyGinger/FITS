from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from fisch.environment.constant import StepName
from fisch.workflows.experiments import ExperimentState
from fisch.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fisch.tasks.registration.register_channel import register_channel
from fisch.tasks.registration.register_time import register_time
from fisch.workflows.definitions.registry import REGISTRY
from fisch.workflows.definitions.inputs import configured_profile


class DummyReader:
    def __init__(self, array: np.ndarray, axes: str, output_path: Path) -> None:
        self.array = array
        self.axes = axes
        self.output_path = output_path
        self.channel_labels = ["GFP", "RFP"] if "C" in axes else None
        self.save_calls: list[dict[str, Any]] = []

    def get_array(self) -> SimpleNamespace:
        return SimpleNamespace(array=self.array, axes=self.axes)

    def resolve_channel_positions(self, channel: int | str) -> list[int]:
        if isinstance(channel, int):
            return [channel]
        assert self.channel_labels is not None
        return [self.channel_labels.index(channel)]

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        self.save_calls.append({"array": array, **kwargs})
        self.output_path.write_bytes(b"")
        return self.output_path


class DummyRegisterModel:
    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.fit_time_calls: list[dict[str, Any]] = []
        self.fit_channel_calls: list[dict[str, Any]] = []
        self.apply_calls: list[dict[str, Any]] = []

    def fit_time(self, **kwargs: Any) -> None:
        self.fit_time_calls.append(kwargs)

    def fit_channel(self, **kwargs: Any) -> None:
        self.fit_channel_calls.append(kwargs)

    def apply(self, **kwargs: Any) -> np.ndarray:
        self.apply_calls.append(kwargs)
        return kwargs["array"] + 1


def _image_state(tmp_path: Path) -> ExperimentState:
    raw = tmp_path / "raw.nd2"
    image = tmp_path / "proc_array.tif"
    raw.write_bytes(b"")
    image.write_bytes(b"")
    return ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT,
        artifact_kind="image_raw",
        artifact_path=image,
    )


def test_register_time_settings_rejects_channel_context() -> None:
    with pytest.raises(Exception, match="linear_drift"):
        RegisterTimeSettings(context="channel_shift")


def test_register_channel_settings_rejects_time_context() -> None:
    with pytest.raises(Exception, match="channel_shift"):
        RegisterChannelSettings(context="linear_drift")


def test_register_time_resolves_fit_channel_and_saves(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(np.ones((3, 2, 4, 4), dtype=np.uint16), "TCYX", tmp_path / "proc_array.tif")
    model = DummyRegisterModel("pystackreg")
    monkeypatch.setattr("fisch.tasks.common.preparation.ScopeIO.from_path", lambda path: reader)
    monkeypatch.setattr("fisch.tasks.common.preparation.decide_run", lambda *args: SimpleNamespace(is_complete=False))
    monkeypatch.setattr("fisch.tasks.registration.register_time.RegisterModel", lambda backend: model)

    results = register_time(
        RegisterTimeSettings(context="linear_drift", fit_channel="RFP"),
        _image_state(tmp_path),
        configured_profile(REGISTRY[StepName.REGISTER_TIME].profile, {"convert": {"enabled": True}}),
    )

    assert results[0].last_step == StepName.REGISTER_TIME
    assert model.backend == "pystackreg"
    assert model.fit_time_calls[0]["fit_channel"] == 1
    assert model.fit_time_calls[0]["axes"] == "TCYX"
    assert np.all(reader.save_calls[0]["array"] == 2)


def test_register_channel_resolves_reference_and_saves(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(np.ones((2, 4, 4), dtype=np.uint16), "CYX", tmp_path / "proc_array.tif")
    model = DummyRegisterModel("cv2")
    monkeypatch.setattr("fisch.tasks.common.preparation.ScopeIO.from_path", lambda path: reader)
    monkeypatch.setattr("fisch.tasks.common.preparation.decide_run", lambda *args: SimpleNamespace(is_complete=False))
    monkeypatch.setattr("fisch.tasks.registration.register_channel.RegisterModel", lambda backend: model)

    results = register_channel(
        RegisterChannelSettings(context="channel_shift", reference_channel="RFP"),
        _image_state(tmp_path),
        configured_profile(REGISTRY[StepName.REGISTER_CHANNEL].profile, {"convert": {"enabled": True}}),
    )

    assert results[0].last_step == StepName.REGISTER_CHANNEL
    assert model.backend == "cv2"
    assert model.fit_channel_calls[0]["reference_channel"] == 1
    assert model.fit_channel_calls[0]["axes"] == "CYX"
    assert np.all(reader.save_calls[0]["array"] == 2)


def test_registration_steps_skip_when_complete(monkeypatch, tmp_path: Path) -> None:
    state = _image_state(tmp_path)
    reader = DummyReader(np.ones((4, 4), dtype=np.uint16), "YX", tmp_path / "proc_array.tif")
    monkeypatch.setattr("fisch.tasks.common.preparation.ScopeIO.from_path", lambda path: reader)
    monkeypatch.setattr("fisch.tasks.common.preparation.decide_run", lambda *args: SimpleNamespace(is_complete=True))

    assert register_channel(
        RegisterChannelSettings(), state, configured_profile(REGISTRY[StepName.REGISTER_CHANNEL].profile, {"convert": {"enabled": True}})
    ) == [state]
    assert reader.save_calls == []


def test_registry_exposes_distinct_registration_steps() -> None:
    time_spec = REGISTRY[StepName.REGISTER_TIME]
    channel_spec = REGISTRY[StepName.REGISTER_CHANNEL]

    assert time_spec.profile.step_name == StepName.REGISTER_TIME
    assert channel_spec.profile.step_name == StepName.REGISTER_CHANNEL
    assert time_spec.item_runner is register_time
    assert channel_spec.item_runner is register_channel


@pytest.fixture(autouse=True)
def isolate_revision_payload_for_fake_readers(monkeypatch):
    from scope_io.metadata.models import ImageMetadata
    from fisch.workflows.artifacts.provenance import revision_payload
    def payload(reader, state, profile, *, export_channels):
        if hasattr(reader, 'build_payload'):
            return revision_payload(reader, state, profile, export_channels=export_channels)
        return ImageMetadata().with_artifact(
            artifact_type=profile.output_artifact, channel_labels=list(export_channels)
        ).with_custom_metadata(state.metadata_dump).new_revision()
    monkeypatch.setattr('fisch.tasks.common.artifact_results.revision_payload', payload)
