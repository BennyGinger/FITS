from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx
from fits.workflows.engines.provenance import StepProfile
from fits.workflows.engines.run_decision import RunDecision
from fits.settings.models import ConvertSettings
from fits.workflows.convert import convert_one, run_convert


class DummyReader:
    def __init__(self, save_paths: list[Path]):
        self._save_paths = save_paths
        self.convert_calls: list[dict] = []

    def convert_to_fits(self, **payload: dict) -> list[Path]:
        self.convert_calls.append(payload)
        return self._save_paths


class DummyPbar:
    def __enter__(self) -> DummyPbar:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def advance(self) -> None:
        return None


def test_convert_one_builds_payload_and_branches(monkeypatch, DummyCtx_class) -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings(overwrite=False, execution="serial")
    output_name = "fits_array.tif"

    with tempfile.TemporaryDirectory() as tmpdir:
        run_dir = Path(tmpdir)
        in_path = run_dir / "in.nd2"
        state = ExperimentState.init(run_dir, in_path)

        monkeypatch.setattr(
            "fits.workflows.convert.decide_run",
            lambda *args, **kwargs: RunDecision(["convert"], [], ["convert"]),
        )
        monkeypatch.setattr(
            "fits.workflows.convert.get_ctx",
            lambda: DummyCtx_class(user_name="ben"),
        )

        seen = {}

        def fake_provenance_payload(step_profile, **kwargs):
            seen["user_name"] = kwargs["user_name"]
            seen["output_name"] = kwargs["output_name"]
            seen["step_name"] = step_profile.step_name
            return {"p": 1, "channel_labels": ["GFP"]}

        monkeypatch.setattr(
            "fits.workflows.convert.provenance_payload",
            fake_provenance_payload,
        )

        dummy_reader = DummyReader(save_paths=[run_dir / "out_s1.tif", run_dir / "out_s2.tif"])

        def fake_from_path(p: Path, channel_labels=None):
            seen["from_path_arg"] = p
            seen["channel_labels"] = channel_labels
            return dummy_reader

        monkeypatch.setattr(
            "fits.workflows.convert.FitsIO.from_path",
            fake_from_path,
        )

        out = convert_one(settings, state, step_profile, output_name)

        assert seen["user_name"] == "ben"
        assert seen["output_name"] == "fits_array.tif"
        assert seen["step_name"] == "convert"
        assert seen["from_path_arg"] == in_path
        assert seen["channel_labels"] == ["GFP"]
        assert len(dummy_reader.convert_calls) == 1
        assert dummy_reader.convert_calls[0] == {"p": 1, "channel_labels": ["GFP"]}
        assert [s.image for s in out] == [run_dir / "out_s1.tif", run_dir / "out_s2.tif"]
        assert all(s.last_step == "convert" for s in out)
        assert all(s.original_image == in_path for s in out)


def test_run_convert_uses_executor_and_worker_context(monkeypatch, DummyCtx_class) -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings(execution="serial", workers=3, ordered_execution=True)
    states = [ExperimentState.init(Path("/tmp"), Path("/tmp/a.nd2"))]
    seen: dict[str, object] = {}

    monkeypatch.setattr(
        "fits.workflows.convert.get_ctx",
        lambda: DummyCtx_class(user_name="ben"),
    )

    monkeypatch.setattr(
        "fits.workflows.convert.pbar",
        lambda **kwargs: DummyPbar(),
    )

    def fake_convert_one(settings, exp_state, step_profile, output_name):
        seen["worker_user"] = get_ctx().user_name
        seen["output_name"] = output_name
        return [exp_state.with_completed_step(step_profile.step_name)]

    monkeypatch.setattr("fits.workflows.convert.convert_one", fake_convert_one)

    def fake_execute(items, worker, *, mode, workers, ordered):
        seen["mode"] = mode
        seen["workers"] = workers
        seen["ordered"] = ordered
        for item in items:
            yield worker(item)

    monkeypatch.setattr("fits.workflows.convert.execute", fake_execute)

    out = run_convert(settings, states, step_profile, "fits_array.tif")

    assert seen == {
        "mode": "serial",
        "workers": 3,
        "ordered": True,
        "worker_user": "ben",
        "output_name": "fits_array.tif",
    }
    assert [state.last_step for state in out] == ["convert"]


def test_run_convert_raises_when_ctx_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "fits.workflows.convert.get_ctx",
        lambda: (_ for _ in ()).throw(RuntimeError("ExecutionContext is not set. Call with use_ctx(ctx): ...")),
    )

    with pytest.raises(RuntimeError):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            run_convert(ConvertSettings(), [ExperimentState.init(run_dir, run_dir / "in.nd2")], StepProfile("io", "convert"), "fits_array.tif")