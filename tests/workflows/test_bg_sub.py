from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO

from fits.environment.constant import StepName
from fits.workflows.experiments import ExperimentState
from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub import remove_bg
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.runtime.errors import StepExecutionError


class _CallableWithoutName:
    def __call__(self, *args: Any, **kwargs: Any) -> np.ndarray:
        return np.array([])


class DummySelection:
    def __init__(self, array: np.ndarray, processed_indices: tuple[int, ...], original: np.ndarray) -> None:
        self.array = array
        self.processed_indices = processed_indices
        self._original = original

    def rebuild(self, processed: np.ndarray, *, dtype=None) -> np.ndarray:
        """Mimic explicit output dtype selection when restoring excluded channels."""
        rebuilt = self._original.copy() if dtype is None else self._original.astype(dtype)
        rebuilt[list(self.processed_indices)] = processed
        return rebuilt


class DummyReader:
    def __init__(self, array: np.ndarray, output_path: Path) -> None:
        self.array = array
        self.output_path = output_path
        self.channel_labels = ["GFP", "RFP"]
        self.save_calls: list[dict[str, Any]] = []

    def select_included_channels(self, excluded_labels: list[str] | None) -> DummySelection:
        excluded = set(excluded_labels or [])
        unknown = excluded.difference(self.channel_labels)
        if unknown:
            raise ValueError(f"Unknown exclude_channel: {sorted(unknown)}")
        positions = tuple(i for i, label in enumerate(self.channel_labels) if label not in excluded)
        return DummySelection(self.array[list(positions)], positions, self.array)

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        self.save_calls.append({"array": array, **kwargs})
        self.output_path.write_bytes(b"")
        return self.output_path


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


def test_bg_sub_settings_serialize_statistic_name_uses_callable_name() -> None:
    settings = BGSubSettings.model_validate({"statistic": "median"})
    assert settings.serialize_statistic_name() == "median"


def test_bg_sub_settings_serialize_statistic_name_falls_back_to_str() -> None:
    settings = BGSubSettings(statistic=_CallableWithoutName())
    assert isinstance(settings.serialize_statistic_name(), str)


@pytest.mark.parametrize(("value", "expected"), [("RFP", ["RFP"]), ("None", None)])
def test_bg_sub_settings_parse_exclude_channel(value: str, expected: list[str] | None) -> None:
    assert BGSubSettings.model_validate({"exclude_channel": value}).exclude_channel == expected


def test_remove_bg_processes_only_included_channels(monkeypatch, tmp_path: Path) -> None:
    input_array = np.stack(
        [np.full((4, 4), 1, dtype=np.uint16), np.full((4, 4), 5, dtype=np.uint16)]
    )
    reader = DummyReader(input_array, tmp_path / "fits_array.tif")
    seen: dict[str, Any] = {}

    def fake_bg_sub(array: np.ndarray, **kwargs: Any) -> np.ndarray:
        seen.update(kwargs)
        return array + 2

    monkeypatch.setattr("fits.tasks.common.preparation.FitsIO.from_path", lambda path: reader)
    monkeypatch.setattr("fits.tasks.common.preparation.decide_run", lambda *args: SimpleNamespace(is_complete=False))
    monkeypatch.setattr("fits.tasks.bg_sub.bg_sub", fake_bg_sub)

    result = remove_bg(
        BGSubSettings.model_validate({"exclude_channel": "RFP", "statistic": "median", "bg_execution": "sequential"}),
        _image_state(tmp_path),
        REGISTRY[StepName.BG_SUB].profile,
    )

    assert len(result) == 1
    assert result[0].last_step == StepName.BG_SUB
    saved = reader.save_calls[0]["array"]
    assert saved.dtype == np.float32
    assert np.all(saved[0] == 3)
    assert np.all(saved[1] == 5)
    assert seen["statistic"] is np.median
    channel_meta = reader.save_calls[0]["custom_metadata"]["steps"]["bg_sub"]["channels"]["0"]
    assert channel_meta["statistic"] == "median"


@pytest.mark.parametrize("exclude", [None, ["RFP"]])
def test_remove_bg_saves_signed_float32_and_restores_excluded_channels(monkeypatch, tmp_path, exclude):
    """Retain negative fractional pixels through channel rebuilding and actual TIFF saving."""
    image = np.arange(64, dtype=np.uint16).reshape(8, 8) + 100
    original = np.stack([image, image + 30])
    input_path = tmp_path / "input.tif"
    tifffile.imwrite(input_path, original, imagej=True, metadata={"axes": "CYX"})
    source = FitsIO.from_path(input_path).save_array(
        original, channel_labels=("GFP", "RFP"), output_path=tmp_path / "fits_array.tif")
    raw = tmp_path / "raw.nd2"
    raw.write_bytes(b"raw")
    state = ExperimentState.init(tmp_path, raw).with_complete_step(
        step_name=StepName.CONVERT, artifact_kind="image", artifact_path=source)

    def subtract(array, **kwargs):
        """Supply known signed fractional results independently of background estimation."""
        return array.astype(np.float32) - 106.5

    monkeypatch.setattr("fits.tasks.bg_sub.bg_sub", subtract)
    remove_bg(BGSubSettings(exclude_channel=exclude), state, REGISTRY[StepName.BG_SUB].profile)
    saved = FitsIO.from_path(source).get_array().array
    assert saved.dtype == np.float32
    np.testing.assert_array_equal(saved[0], original[0].astype(np.float32) - 106.5)
    expected_second = original[1] if exclude else original[1].astype(np.float32) - 106.5
    np.testing.assert_array_equal(saved[1], expected_second)
    assert saved[0, 0, 0] == -6.5


def test_remove_bg_skips_completed_step(monkeypatch, tmp_path: Path) -> None:
    state = _image_state(tmp_path)
    reader = DummyReader(np.ones((2, 4, 4), dtype=np.uint16), tmp_path / "fits_array.tif")
    monkeypatch.setattr("fits.tasks.common.preparation.FitsIO.from_path", lambda path: reader)
    monkeypatch.setattr("fits.tasks.common.preparation.decide_run", lambda *args: SimpleNamespace(is_complete=True))
    monkeypatch.setattr(
        "fits.tasks.bg_sub.bg_sub",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("background subtraction should not run")),
    )

    assert remove_bg(BGSubSettings(), state, REGISTRY[StepName.BG_SUB].profile) == [state]
    assert reader.save_calls == []


def test_remove_bg_wraps_reader_errors(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(np.ones((2, 4, 4), dtype=np.uint16), tmp_path / "fits_array.tif")
    monkeypatch.setattr("fits.tasks.common.preparation.FitsIO.from_path", lambda path: reader)
    monkeypatch.setattr("fits.tasks.common.preparation.decide_run", lambda *args: SimpleNamespace(is_complete=False))

    with pytest.raises(StepExecutionError, match="Unknown exclude_channel"):
        remove_bg(
            BGSubSettings.model_validate({"exclude_channel": "DAPI"}),
            _image_state(tmp_path),
            REGISTRY[StepName.BG_SUB].profile,
        )
