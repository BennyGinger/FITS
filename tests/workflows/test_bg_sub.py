from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from fits.environment.constant import StepName
from fits.environment.state import ExperimentState
from fits.settings.models import BGSubSettings
from fits.tasks.bg_sub import remove_bg
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.errors import StepExecutionError


class _CallableWithoutName:
    def __call__(self, *args: Any, **kwargs: Any) -> np.ndarray:
        return np.array([])


class DummySelection:
    def __init__(self, array: np.ndarray, processed_indices: tuple[int, ...], original: np.ndarray) -> None:
        self.array = array
        self.processed_indices = processed_indices
        self._original = original

    def rebuild(self, processed: np.ndarray) -> np.ndarray:
        rebuilt = self._original.copy()
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
    settings = BGSubSettings(statistic="median")
    assert settings.serialize_statistic_name() == "median"


def test_bg_sub_settings_serialize_statistic_name_falls_back_to_str() -> None:
    settings = BGSubSettings(statistic=_CallableWithoutName())
    assert isinstance(settings.serialize_statistic_name(), str)


@pytest.mark.parametrize(("value", "expected"), [("RFP", ["RFP"]), ("None", None)])
def test_bg_sub_settings_parse_exclude_channel(value: str, expected: list[str] | None) -> None:
    assert BGSubSettings(exclude_channel=value).exclude_channel == expected


def test_remove_bg_processes_only_included_channels(monkeypatch, tmp_path: Path) -> None:
    input_array = np.stack(
        [np.full((4, 4), 1, dtype=np.uint16), np.full((4, 4), 5, dtype=np.uint16)]
    )
    reader = DummyReader(input_array, tmp_path / "fits_array.tif")
    seen: dict[str, Any] = {}

    def fake_bg_sub(array: np.ndarray, **kwargs: Any) -> np.ndarray:
        seen.update(kwargs)
        return array + 2

    monkeypatch.setattr("fits.tasks.bg_sub.FitsIO.from_path", lambda path: reader)
    monkeypatch.setattr("fits.tasks.bg_sub.decide_run", lambda *args: SimpleNamespace(is_complete=False))
    monkeypatch.setattr("fits.tasks.bg_sub.bg_sub", fake_bg_sub)

    result = remove_bg(
        BGSubSettings(exclude_channel="RFP", statistic="median", bg_execution="sequential"),
        _image_state(tmp_path),
        REGISTRY[StepName.BG_SUB].profile,
    )

    assert len(result) == 1
    assert result[0].last_step == StepName.BG_SUB
    saved = reader.save_calls[0]["array"]
    assert np.all(saved[0] == 3)
    assert np.all(saved[1] == 5)
    assert seen["statistic"] is np.median
    channel_meta = reader.save_calls[0]["custom_metadata"]["steps"]["bg_sub"]["channels"]["0"]
    assert channel_meta["statistic"] == "median"


def test_remove_bg_skips_completed_step(monkeypatch, tmp_path: Path) -> None:
    state = _image_state(tmp_path)
    reader = DummyReader(np.ones((2, 4, 4), dtype=np.uint16), tmp_path / "fits_array.tif")
    monkeypatch.setattr("fits.tasks.bg_sub.FitsIO.from_path", lambda path: reader)
    monkeypatch.setattr("fits.tasks.bg_sub.decide_run", lambda *args: SimpleNamespace(is_complete=True))
    monkeypatch.setattr(
        "fits.tasks.bg_sub.bg_sub",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("background subtraction should not run")),
    )

    assert remove_bg(BGSubSettings(), state, REGISTRY[StepName.BG_SUB].profile) == [state]
    assert reader.save_calls == []


def test_remove_bg_wraps_reader_errors(monkeypatch, tmp_path: Path) -> None:
    reader = DummyReader(np.ones((2, 4, 4), dtype=np.uint16), tmp_path / "fits_array.tif")
    monkeypatch.setattr("fits.tasks.bg_sub.FitsIO.from_path", lambda path: reader)
    monkeypatch.setattr("fits.tasks.bg_sub.decide_run", lambda *args: SimpleNamespace(is_complete=False))

    with pytest.raises(StepExecutionError, match="Unknown exclude_channel"):
        remove_bg(
            BGSubSettings(exclude_channel="DAPI"),
            _image_state(tmp_path),
            REGISTRY[StepName.BG_SUB].profile,
        )
