from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from fits.workflows.tasks.convert import run_convert
from fits.environment.state import ExperimentState
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings


class DummyReader:
    def __init__(self, save_paths: list[Path]):
        self._save_paths = save_paths
        self.convert_calls: list[dict] = []

    def convert_to_fits(self, **payload: dict) -> list[Path]:
        self.convert_calls.append(payload)
        return self._save_paths


def test_run_convert_wires_everything(monkeypatch, DummyCtx_class) -> None:
    # Arrange
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings(overwrite=False)
    output_name = "fits_array.tif"
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        in_path = run_dir / "in.nd2"
        states = [ExperimentState.init(run_dir, in_path)]

        # fake runtime ctx
        monkeypatch.setattr(
            "fits.workflows.tasks.convert.get_ctx",
            lambda: DummyCtx_class(user_name="ben"),
        )

        # fake payload builder (and capture args)
        seen = {}
        def fake_build_payload(settings, step_profile, user_name, output_name):
            seen["user_name"] = user_name
            seen["output_name"] = output_name
            seen["step_name"] = step_profile.step_name
            return {"p": 1}

        monkeypatch.setattr(
            "fits.workflows.tasks.convert.build_payload",
            fake_build_payload,
        )

        # fake FitsIO.from_path -> returns dummy reader
        dummy_reader = DummyReader(save_paths=[run_dir / "out_s1.tif", run_dir / "out_s2.tif"])

        def fake_from_path(p: Path, channel_labels=None):
            seen["from_path_arg"] = p
            return dummy_reader

        monkeypatch.setattr(
            "fits.workflows.tasks.convert.FitsIO.from_path",
            fake_from_path,
        )

        # Act
        out = run_convert(settings, states, step_profile, output_name)

        # Assert: payload wiring
        assert seen["user_name"] == "ben"
        assert seen["output_name"] == "fits_array.tif"
        assert seen["step_name"] == "convert"

        # Assert: reader called on original path
        assert seen["from_path_arg"] == in_path

        # Assert: convert called with the payload produced above
        assert len(dummy_reader.convert_calls) == 1
        call_payload = dummy_reader.convert_calls[0]
        assert call_payload == {"p": 1}

        # Assert: state updates (one input -> two outputs)
        assert [s.image for s in out] == [run_dir / "out_s1.tif", run_dir / "out_s2.tif"]
        assert all(s.last_step == "convert" for s in out)
        assert all(s.original_image == in_path for s in out)


def test_run_convert_multiple_inputs(monkeypatch, DummyCtx_class) -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings()

    monkeypatch.setattr(
        "fits.workflows.tasks.convert.get_ctx",
        lambda: DummyCtx_class(user_name="ben"),
    )
    monkeypatch.setattr(
        "fits.workflows.tasks.convert.build_payload",
        lambda *args, **kwargs: {"p": 1},
    )
    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        a_in = run_dir / "a.nd2"
        b_in = run_dir / "b.nd2"

        readers = {
            a_in: DummyReader([run_dir / "a_out.tif"]),
            b_in: DummyReader([run_dir / "b_out.tif"]),
        }
        monkeypatch.setattr(
            "fits.workflows.tasks.convert.FitsIO.from_path",
            lambda p, channel_labels=None: readers[p],
        )

        states = [
            ExperimentState.init(run_dir, a_in),
            ExperimentState.init(run_dir, b_in),
        ]

        out = run_convert(settings, states, step_profile, "fits_array.tif")

        assert [s.image for s in out] == [run_dir / "a_out.tif", run_dir / "b_out.tif"]
        assert all(s.last_step == "convert" for s in out)

def test_run_convert_raises_when_ctx_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "fits.workflows.tasks.convert.get_ctx",
        lambda: (_ for _ in ()).throw(RuntimeError("ExecutionContext is not set. Call with use_ctx(ctx): ...")),
    )

    with pytest.raises(RuntimeError):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            run_convert(ConvertSettings(), [ExperimentState.init(run_dir, run_dir / "in.nd2")], StepProfile("io", "convert"), "fits_array.tif")