from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
import importlib

import numpy as np
import pytest

from fits.environment.constant import StepName
from fits.environment.state import ExperimentState
from fits.settings.models import ConvertSettings
from fits.tasks.convert import convert
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.errors import StepExecutionError


convert_module = importlib.import_module("fits.tasks.convert")


class DummySeriesReader:
    def __init__(self, output_path: Path) -> None:
        self.output_path = output_path
        self.prepare_calls: list[dict[str, Any]] = []
        self.save_calls: list[dict[str, Any]] = []

    def prepare_conversion(self, **kwargs: Any) -> SimpleNamespace:
        self.prepare_calls.append(kwargs)
        return SimpleNamespace(
            array=np.ones((4, 4), dtype=np.uint16),
            metadata=SimpleNamespace(),
            output_path=self.output_path,
        )

    def save_array(self, **kwargs: Any) -> Path:
        self.save_calls.append(kwargs)
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self.output_path.write_bytes(b"")
        return self.output_path


class DummySource:
    def __init__(self, series: list[DummySeriesReader]) -> None:
        self.series = series
        self.selection_calls: list[dict[str, Any]] = []
        self.selection = object()

    def resolve_channel_selection(self, **kwargs: Any) -> object:
        self.selection_calls.append(kwargs)
        return self.selection

    def split_series(self) -> list[DummySeriesReader]:
        return self.series


def test_convert_builds_each_series_branch(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "input.nd2"
    raw.write_bytes(b"")
    state = ExperimentState.init(tmp_path, raw)
    series = [
        DummySeriesReader(tmp_path / "series_1" / "fits_array.tif"),
        DummySeriesReader(tmp_path / "series_2" / "fits_array.tif"),
    ]
    source = DummySource(series)
    monkeypatch.setattr(convert_module, "decide_run", lambda *args: SimpleNamespace(is_complete=False))
    monkeypatch.setattr(convert_module.FitsIO, "from_path", lambda path: source)

    results = convert(
        ConvertSettings(channel_labels=["GFP", "RFP"], export_channels=["RFP"], z_projection="max"),
        state,
        REGISTRY[StepName.CONVERT].profile,
    )

    assert source.selection_calls == [{"channel_labels": ["GFP", "RFP"], "export_channels": ["RFP"]}]
    assert [result.artifact("image") for result in results] == [reader.output_path for reader in series]
    assert all(result.last_step == StepName.CONVERT for result in results)
    assert all(result.original_image == raw for result in results)
    assert all(reader.prepare_calls[0]["selection"] is source.selection for reader in series)
    assert all(reader.prepare_calls[0]["z_projection"] == "max" for reader in series)
    assert all(reader.save_calls[0]["compression"] == "zlib" for reader in series)


def test_convert_skips_completed_step(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "input.nd2"
    raw.write_bytes(b"")
    state = ExperimentState.init(tmp_path, raw)
    monkeypatch.setattr(convert_module, "decide_run", lambda *args: SimpleNamespace(is_complete=True))
    monkeypatch.setattr(
        convert_module.FitsIO,
        "from_path",
        lambda path: (_ for _ in ()).throw(AssertionError("reader should not be opened")),
    )

    assert convert(ConvertSettings(), state, REGISTRY[StepName.CONVERT].profile) == [state]


def test_convert_wraps_conversion_errors(monkeypatch, tmp_path: Path) -> None:
    raw = tmp_path / "input.nd2"
    raw.write_bytes(b"")
    state = ExperimentState.init(tmp_path, raw)
    monkeypatch.setattr(convert_module, "decide_run", lambda *args: SimpleNamespace(is_complete=False))
    monkeypatch.setattr(
        convert_module.FitsIO,
        "from_path",
        lambda path: (_ for _ in ()).throw(ValueError("unsupported image")),
    )

    with pytest.raises(StepExecutionError, match="unsupported image"):
        convert(ConvertSettings(), state, REGISTRY[StepName.CONVERT].profile)


@pytest.mark.parametrize("projection", ["None", "max", "mean", "sum", "std"])
def test_convert_real_z_stack(tmp_path: Path, projection: str) -> None:
    from tifffile import imwrite
    from fits_io import FitsIO
    from fits.gui.settings_adapter import SettingsAdapter

    raw = tmp_path / "input.tif"
    array = (np.arange(2 * 3 * 4 * 5).reshape(2, 3, 4, 5) + 40000).astype(np.uint16)
    imwrite(raw, array, imagej=True, metadata={"axes": "TZYX"})
    adapter = SettingsAdapter()
    adapter.set_field_value(StepName.CONVERT, "z_projection", projection)
    saved = adapter.save(tmp_path / "settings.toml")
    adapter.load(saved)
    settings = ConvertSettings.model_validate(adapter.as_mapping()["convert"]["params"])
    results = convert(settings, ExperimentState.init(tmp_path, raw), REGISTRY[StepName.CONVERT].profile)
    output = FitsIO.from_path(results[0].artifact("image"))
    actual = output.get_array().array
    if projection == "None":
        assert settings.z_projection is None
        assert output.reader.axes == "TZYX"
        assert actual.dtype == array.dtype
        np.testing.assert_array_equal(actual, array)
    else:
        assert output.reader.axes == "TYX"
        expected = getattr(np, projection)(array, axis=1)
        np.testing.assert_allclose(actual, expected, rtol=1e-6)
    assert output.reader.metadata.fits_io.z_projection == settings.z_projection
