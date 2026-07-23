from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile

import numpy as np

from fits.environment.state import ExperimentState
from fits.settings.models import BGSubSettings
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import RunDecision
from fits.tasks.bg_sub import bg_sub_one


class DummyReader:
    def __init__(self, *, channel_labels: list[str] | None = None, fits_metadata: dict[str, object] | None = None) -> None:
        self.channel_labels = channel_labels
        self.fits_metadata = fits_metadata or {}
        self.save_calls: list[dict[str, Any]] = []

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        payload = {"array": array}
        payload.update(kwargs)
        self.save_calls.append(payload)
        return Path("/tmp/fits_array.tif")


class DummyBatch:
    def __init__(self, frames: list[np.ndarray]) -> None:
        self.frames = frames

    def rebuild(self, frames: list[np.ndarray]) -> np.ndarray:
        return np.stack(frames, axis=0)


class _CallableWithoutName:
    def __call__(self, *args: Any, **kwargs: Any) -> np.ndarray:
        return np.array([])


def test_bg_sub_settings_serialize_statistic_name_uses_callable_name() -> None:
    settings = BGSubSettings(statistic="median", execution="serial")  # type: ignore[arg-type]

    assert settings.serialize_statistic_name() == "median"


def test_bg_sub_settings_serialize_statistic_name_falls_back_to_str() -> None:
    settings = BGSubSettings(statistic=_CallableWithoutName(), execution="serial")

    # Callable instance has no __name__; serializer should still return a JSON-safe string.
    assert isinstance(settings.serialize_statistic_name(), str)


def test_bg_sub_settings_parse_exclude_channel_from_str() -> None:
    settings = BGSubSettings(exclude_channel="RFP", execution="serial")  # type: ignore[arg-type]

    assert settings.exclude_channel == ["RFP"]


def test_bg_sub_settings_parse_exclude_channel_none_string() -> None:
    settings = BGSubSettings(exclude_channel="None", execution="serial")  # type: ignore[arg-type]

    assert settings.exclude_channel is None


def test_bg_sub_one_writes_json_safe_statistic_in_project_metadata(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / "fits_array.tif"
        image_path.write_bytes(b"")
        state = ExperimentState.init(run_dir, run_dir / "raw.nd2").with_image(image_path)
        reader = DummyReader(channel_labels=["GFP", "RFP"])

        monkeypatch.setattr("fits.workflows.bg_sub.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.bg_sub.FitsIO.from_path", lambda path: reader)
        monkeypatch.setattr("fits.workflows.bg_sub.decide_run", lambda *args, **kwargs: RunDecision(["bg_sub"], [], ["bg_sub"]))
        monkeypatch.setattr("fits.workflows.bg_sub.get_array", lambda *_: (np.ones((2, 4, 4), dtype=np.uint16), "CYX"))
        monkeypatch.setattr(
            "fits.workflows.bg_sub.flatten_to_frames",
            lambda array, axis: DummyBatch([np.ones((4, 4), dtype=np.uint16), np.ones((4, 4), dtype=np.uint16)]),
        )
        monkeypatch.setattr("fits.workflows.bg_sub.bg_sub", lambda frames, **kwargs: frames)
        monkeypatch.setattr("fits.workflows.bg_sub.load_project_metadata_from_reader", lambda _reader: None)

        out = bg_sub_one(
            BGSubSettings(sigma=2.0, size=3, threshold=0.05, statistic="median", execution="serial"),  # type: ignore[arg-type]
            state,
            StepProfile(distribution="fits", step_name="bg_sub"),
            "fits_array.tif",
        )

        assert out.last_step == "bg_sub"
        assert len(reader.save_calls) == 1
        project_metadata = reader.save_calls[0]["project_metadata"]
        assert project_metadata["steps"]["bg_sub"]["statistic"] == "median"


def test_bg_sub_one_excludes_selected_channel(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / "fits_array.tif"
        image_path.write_bytes(b"")
        state = ExperimentState.init(run_dir, run_dir / "raw.nd2").with_image(image_path)
        reader = DummyReader(channel_labels=["GFP", "RFP"])

        input_array = np.stack(
            [
                np.full((4, 4), 1, dtype=np.uint16),
                np.full((4, 4), 5, dtype=np.uint16),
            ],
            axis=0,
        )

        seen: dict[str, int] = {}

        def fake_bg_sub(frames: list[np.ndarray], **kwargs: Any) -> list[np.ndarray]:
            seen["frames_count"] = len(frames)
            return [frame + 2 for frame in frames]

        monkeypatch.setattr("fits.workflows.bg_sub.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.bg_sub.FitsIO.from_path", lambda path: reader)
        monkeypatch.setattr("fits.workflows.bg_sub.decide_run", lambda *args, **kwargs: RunDecision(["bg_sub"], [], ["bg_sub"]))
        monkeypatch.setattr("fits.workflows.bg_sub.get_array", lambda *_: (input_array, "CYX"))
        monkeypatch.setattr("fits.workflows.bg_sub.bg_sub", fake_bg_sub)
        monkeypatch.setattr("fits.workflows.bg_sub.load_project_metadata_from_reader", lambda _reader: None)

        out = bg_sub_one(
            BGSubSettings(sigma=2.0, size=3, threshold=0.05, statistic="median", exclude_channel="RFP", execution="serial"),  # type: ignore[arg-type]
            state,
            StepProfile(distribution="fits", step_name="bg_sub"),
            "fits_array.tif",
        )

        assert out.last_step == "bg_sub"
        assert seen["frames_count"] == 1
        saved = reader.save_calls[0]["array"]
        assert np.all(saved[0] == 3)
        assert np.all(saved[1] == 5)
        assert reader.save_calls[0]["project_metadata"]["steps"]["bg_sub"]["exclude_channel"] == ["RFP"]


def test_bg_sub_one_errors_on_unknown_excluded_channel(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / "fits_array.tif"
        image_path.write_bytes(b"")
        state = ExperimentState.init(run_dir, run_dir / "raw.nd2").with_image(image_path)
        reader = DummyReader(channel_labels=["GFP", "RFP"])

        monkeypatch.setattr("fits.workflows.bg_sub.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.bg_sub.FitsIO.from_path", lambda path: reader)
        monkeypatch.setattr("fits.workflows.bg_sub.decide_run", lambda *args, **kwargs: RunDecision(["bg_sub"], [], ["bg_sub"]))
        monkeypatch.setattr("fits.workflows.bg_sub.get_array", lambda *_: (np.ones((2, 4, 4), dtype=np.uint16), "CYX"))

        out = bg_sub_one(
            BGSubSettings(exclude_channel="DAPI", execution="serial"),  # type: ignore[arg-type]
            state,
            StepProfile(distribution="fits", step_name="bg_sub"),
            "fits_array.tif",
        )

        assert out.last_error is not None
        assert out.last_error[0] == "bg_sub"
        assert "Unknown exclude_channel" in out.last_error[1]
