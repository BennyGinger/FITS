from __future__ import annotations

from pathlib import Path

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
    states = [ExperimentState(original_image=Path("in.nd2"))]
    output_name = "fits_array"

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
    dummy_reader = DummyReader(save_paths=[Path("out_s1.tif"), Path("out_s2.tif")])

    def fake_from_path(p: Path, channel_labels=None):
        seen["from_path_arg"] = p
        return dummy_reader

    monkeypatch.setattr(
        "fits_io.FitsIO.from_path",
        fake_from_path,
    )

    # Act
    out = run_convert(settings, states, step_profile, output_name)

    # Assert: payload wiring
    assert seen["user_name"] == "ben"
    assert seen["output_name"] == "fits_array"
    assert seen["step_name"] == "convert"

    # Assert: reader called on original path
    assert seen["from_path_arg"] == Path("in.nd2")

    # Assert: convert called with the payload produced above
    # Note: expected_filenames is added by run_convert before calling convert_to_fits
    assert len(dummy_reader.convert_calls) == 1
    call_payload = dummy_reader.convert_calls[0]
    assert call_payload["p"] == 1
    assert "expected_filenames" in call_payload
    assert call_payload["expected_filenames"] == {"fits_array.tif", "fits_mask.tif"}

    # Assert: state updates (one input -> two outputs)
    assert [s.image for s in out] == [Path("out_s1.tif"), Path("out_s2.tif")]
    assert all(s.last_step == "convert" for s in out)
    assert all(s.original_image == Path("in.nd2") for s in out)


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

    readers = {
        Path("a.nd2"): DummyReader([Path("a_out.tif")]),
        Path("b.nd2"): DummyReader([Path("b_out.tif")]),
    }
    monkeypatch.setattr(
        "fits_io.FitsIO.from_path",
        lambda p, channel_labels=None: readers[p],
    )

    states = [
        ExperimentState(original_image=Path("a.nd2")),
        ExperimentState(original_image=Path("b.nd2")),
    ]

    out = run_convert(settings, states, step_profile, "fits_array")

    assert [s.image for s in out] == [Path("a_out.tif"), Path("b_out.tif")]
    assert all(s.last_step == "convert" for s in out)

def test_run_convert_raises_when_ctx_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "fits.workflows.tasks.convert.get_ctx",
        lambda: (_ for _ in ()).throw(RuntimeError("ExecutionContext is not set. Call with use_ctx(ctx): ...")),
    )

    with pytest.raises(RuntimeError):
        run_convert(ConvertSettings(), [ExperimentState(Path("in.nd2"))], StepProfile("io", "convert"), "fits_array")