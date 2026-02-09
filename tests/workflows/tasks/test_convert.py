from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

# import your function under test
from fits.workflows.tasks.convert import run_convert
from fits.environment.state import ExperimentState
from fits.workflows.provenance import StepProfile
from fits.settings.models import ConvertSettings


@dataclass
class DummyCtx:
    user_name: str


class DummyReader:
    def __init__(self, save_paths: list[Path]):
        self._save_paths = save_paths
        self.convert_calls: list[dict] = []

    def convert_to_fits(self, **payload):
        self.convert_calls.append(payload)
        return self._save_paths


def test_run_convert_wires_everything(monkeypatch) -> None:
    # Arrange
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings(enabled=True, overwrite=False)
    states = [ExperimentState(original_image=Path("in.nd2"))]
    output_name = "fits_array"

    # fake runtime ctx
    monkeypatch.setattr(
        "fits.workflows.tasks.convert.get_ctx",
        lambda: DummyCtx(user_name="ben"),
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

    def fake_from_path(p: Path):
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
    assert dummy_reader.convert_calls == [{"p": 1}]

    # Assert: state updates (one input -> two outputs)
    assert [s.image for s in out] == [Path("out_s1.tif"), Path("out_s2.tif")]
    assert all(s.last_step == "convert" for s in out)
    assert all(s.original_image == Path("in.nd2") for s in out)


def test_run_convert_multiple_inputs(monkeypatch) -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings(enabled=True)

    monkeypatch.setattr(
        "fits.workflows.tasks.convert.get_ctx",
        lambda: DummyCtx(user_name="ben"),
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
        lambda p: readers[p],
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
        run_convert(ConvertSettings(enabled=True), [ExperimentState(Path("in.nd2"))], StepProfile("io", "convert"), "fits_array")