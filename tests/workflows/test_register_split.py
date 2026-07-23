from __future__ import annotations

from pathlib import Path
from typing import Any
import tempfile

import numpy as np

import fits.environment.constant as cst
from fits.environment.state import ExperimentState
from fits.settings.models import RegisterChannelSettings, RegisterTimeSettings
from fits.workflows.engines.registry import REGISTRY
from fits.workflows.engines.run_decision import RunDecision
from fits.workflows.engines.models import StepProfile
from fits.tasks.registration.register_channel import register_channel_one
from fits.tasks.registration.register_time import register_time_one


class DummyReader:
    def __init__(self, *, channel_labels: list[str] | None = None, fits_metadata: dict[str, Any] | None = None) -> None:
        self.channel_labels = channel_labels
        self.fits_metadata = fits_metadata or {}
        self.save_calls: list[dict[str, Any]] = []

    def save_array(self, array: np.ndarray, **kwargs: Any) -> Path:
        payload = {"array": array}
        payload.update(kwargs)
        self.save_calls.append(payload)
        return Path("/tmp/fits_array.tif")


class DummyRegisterModel:
    def __init__(self, backend: str) -> None:
        self.backend = backend
        self.fit_time_calls: list[dict[str, Any]] = []
        self.fit_channel_calls: list[dict[str, Any]] = []
        self.apply_calls: list[dict[str, Any]] = []

    def fit_time(self, **kwargs: Any) -> DummyRegisterModel:
        self.fit_time_calls.append(dict(kwargs))
        return self

    def fit_channel(self, **kwargs: Any) -> DummyRegisterModel:
        self.fit_channel_calls.append(dict(kwargs))
        return self

    def apply(self, **kwargs: Any) -> np.ndarray:
        self.apply_calls.append(dict(kwargs))
        return kwargs["array"]


def test_register_time_settings_rejects_channel_context() -> None:
    try:
        RegisterTimeSettings(context="channel_shift")
        assert False, "Expected context validation error"
    except Exception as e:
        assert "not a time-wise" in str(e)


def test_register_channel_settings_rejects_time_context() -> None:
    try:
        RegisterChannelSettings(context="linear_drift")
        assert False, "Expected context validation error"
    except Exception as e:
        assert "not a channel-wise" in str(e)


def test_register_time_requires_fit_channel_on_multichannel(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / "fits_array.tif"
        image_path.write_bytes(b"")
        state = ExperimentState.init(run_dir, run_dir / "raw.nd2").with_image(image_path)
        reader = DummyReader(channel_labels=["GFP", "RFP"])
        model = DummyRegisterModel("scikit")

        monkeypatch.setattr("fits.workflows.register_time.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.register_time.FitsIO.from_path", lambda path: reader)
        monkeypatch.setattr("fits.workflows.register_time.decide_run", lambda *args, **kwargs: RunDecision(["register_time"], [], ["register_time"]))
        monkeypatch.setattr("fits.workflows.register_time.get_array", lambda *_: (np.ones((2, 2, 4, 4), dtype=np.uint16), "TCYX"))
        monkeypatch.setattr("fits.workflows.register_time.RegisterModel", lambda backend: model)
        monkeypatch.setattr("fits.workflows.register_time.load_project_metadata_from_reader", lambda _reader: None)

        out = register_time_one(
            RegisterTimeSettings(context="linear_drift", fit_channel=None, execution="serial"),
            state,
            StepProfile(distribution="stackalign", step_name="register_time"),
            "fits_array.tif",
        )

        assert out.last_error is not None
        assert out.last_error[0] == "register_time"
        assert "fit_channel" in out.last_error[1]


def test_register_channel_excludes_before_fit_and_resolves_reference_locally(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / "fits_array.tif"
        image_path.write_bytes(b"")
        state = ExperimentState.init(run_dir, run_dir / "raw.nd2").with_image(image_path)
        reader = DummyReader(channel_labels=["GFP", "RFP", "BF"])
        input_array = np.stack(
            [
                np.full((4, 4), 1, dtype=np.uint16),
                np.full((4, 4), 5, dtype=np.uint16),
                np.full((4, 4), 9, dtype=np.uint16),
            ],
            axis=0,
        )

        class AddTenModel(DummyRegisterModel):
            def apply(self, **kwargs: Any) -> np.ndarray:
                self.apply_calls.append(dict(kwargs))
                return kwargs["array"] + 10

        model = AddTenModel("cv2")

        monkeypatch.setattr("fits.workflows.register_channel.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.register_channel.FitsIO.from_path", lambda path: reader)
        monkeypatch.setattr("fits.workflows.register_channel.decide_run", lambda *args, **kwargs: RunDecision(["register_channel"], [], ["register_channel"]))
        monkeypatch.setattr("fits.workflows.register_channel.get_array", lambda *_: (input_array, "CYX"))
        monkeypatch.setattr("fits.workflows.register_channel.RegisterModel", lambda backend: model)
        monkeypatch.setattr("fits.workflows.register_channel.load_project_metadata_from_reader", lambda _reader: None)

        out = register_channel_one(
            RegisterChannelSettings(context="channel_shift", reference_channel="RFP", exclude_channel=["BF"], execution="serial"),
            state,
            StepProfile(distribution="stackalign", step_name="register_channel"),
            "fits_array.tif",
        )

        assert out.last_step == "register_channel"
        assert len(model.fit_channel_calls) == 1
        # Fit happens on included subset only: GFP + RFP
        assert model.fit_channel_calls[0]["array"].shape[0] == 2
        # Local index in included labels ["GFP", "RFP"]
        assert model.fit_channel_calls[0]["reference_channel"] == 1

        saved = reader.save_calls[0]["array"]
        # Included channels transformed
        assert np.all(saved[0] == 11)
        assert np.all(saved[1] == 15)
        # Excluded BF unchanged
        assert np.all(saved[2] == 9)

        meta = reader.save_calls[0]["project_metadata"]["steps"]["register_channel"]
        assert meta["resolved_reference_channel"] == 1
        assert meta["included_channel_indices"] == [0, 1]
        assert meta["included_channel_labels"] == ["GFP", "RFP"]


def test_register_time_and_channel_use_distinct_step_names_and_metadata_blocks(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        image_path = run_dir / "fits_array.tif"
        image_path.write_bytes(b"")
        state = ExperimentState.init(run_dir, run_dir / "raw.nd2").with_image(image_path)

        # register_time
        time_reader = DummyReader(channel_labels=["GFP", "RFP"])
        time_model = DummyRegisterModel("scikit")
        monkeypatch.setattr("fits.workflows.register_time.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.register_time.FitsIO.from_path", lambda path: time_reader)
        monkeypatch.setattr("fits.workflows.register_time.decide_run", lambda *args, **kwargs: RunDecision(["register_time"], [], ["register_time"]))
        monkeypatch.setattr("fits.workflows.register_time.get_array", lambda *_: (np.ones((2, 2, 4, 4), dtype=np.uint16), "TCYX"))
        monkeypatch.setattr("fits.workflows.register_time.RegisterModel", lambda backend: time_model)
        monkeypatch.setattr("fits.workflows.register_time.load_project_metadata_from_reader", lambda _reader: None)

        out_time = register_time_one(
            RegisterTimeSettings(context="linear_drift", fit_channel="GFP", execution="serial"),
            state,
            StepProfile(distribution="stackalign", step_name="register_time"),
            "fits_array.tif",
        )

        assert out_time.last_step == "register_time"
        assert "register_time" in time_reader.save_calls[0]["project_metadata"]["steps"]

        # register_channel
        ch_reader = DummyReader(channel_labels=["GFP", "RFP"])
        ch_model = DummyRegisterModel("cv2")
        monkeypatch.setattr("fits.workflows.register_channel.get_ctx", lambda: type("Ctx", (), {"user_name": "ben", "run_dir": run_dir})())
        monkeypatch.setattr("fits.workflows.register_channel.FitsIO.from_path", lambda path: ch_reader)
        monkeypatch.setattr("fits.workflows.register_channel.decide_run", lambda *args, **kwargs: RunDecision(["register_channel"], [], ["register_channel"]))
        monkeypatch.setattr("fits.workflows.register_channel.get_array", lambda *_: (np.ones((2, 4, 4), dtype=np.uint16), "CYX"))
        monkeypatch.setattr("fits.workflows.register_channel.RegisterModel", lambda backend: ch_model)
        monkeypatch.setattr("fits.workflows.register_channel.load_project_metadata_from_reader", lambda _reader: None)

        out_channel = register_channel_one(
            RegisterChannelSettings(context="channel_shift", reference_channel="GFP", execution="serial"),
            state,
            StepProfile(distribution="stackalign", step_name="register_channel"),
            "fits_array.tif",
        )

        assert out_channel.last_step == "register_channel"
        assert "register_channel" in ch_reader.save_calls[0]["project_metadata"]["steps"]


def test_registry_exposes_register_time_and_register_channel_steps() -> None:
    assert cst.STEP_REGISTER_TIME in REGISTRY
    assert cst.STEP_REGISTER_CHANNEL in REGISTRY
    assert REGISTRY[cst.STEP_REGISTER_TIME].name == cst.STEP_REGISTER_TIME
    assert REGISTRY[cst.STEP_REGISTER_CHANNEL].name == cst.STEP_REGISTER_CHANNEL
