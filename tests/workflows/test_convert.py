from __future__ import annotations

from pathlib import Path
import tempfile

import pytest

from fits.environment.state import ExperimentState
from fits.environment.runtime import get_ctx
from fits.workflows.engines.models import StepProfile
from fits.workflows.engines.run_decision import RunDecision
from fits.settings.models import ConvertSettings
from fits.tasks.convert import run_convert, run_convert


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
    settings = ConvertSettings(overwrite=False, execution="serial", channel_labels=["GFP"])
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

        def fake_build_step_project_metadata(*, existing_project_metadata, step_profile, user_name, step_metadata, channel_metadata):
            seen["existing_project_metadata"] = existing_project_metadata
            seen["user_name"] = user_name
            seen["step_metadata"] = step_metadata
            seen["step_name"] = step_profile.step_name
            seen["channel_metadata"] = channel_metadata
            return {"pipeline": {"distribution": "io"}, "steps": {"convert": {"k": 1}}}

        monkeypatch.setattr(
            "fits.workflows.convert.build_step_project_metadata",
            fake_build_step_project_metadata,
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

        out = run_convert(settings, state, step_profile, output_name)

        assert seen["existing_project_metadata"] is None
        assert seen["user_name"] == "ben"
        assert seen["step_name"] == "convert"
        assert seen["step_metadata"] is None
        assert seen["channel_metadata"] is None
        assert seen["from_path_arg"] == in_path
        assert seen["channel_labels"] == ["GFP"]
        assert len(dummy_reader.convert_calls) == 1
        assert dummy_reader.convert_calls[0]["channel_labels"] == ["GFP"]
        assert dummy_reader.convert_calls[0]["project_metadata"] == {"pipeline": {"distribution": "io"}, "steps": {"convert": {"k": 1}}}
        assert [s.image for s in out] == [run_dir / "out_s1.tif", run_dir / "out_s2.tif"]
        assert all(s.last_step == "convert" for s in out)
        assert all(s.original_image == in_path for s in out)


def test_convert_one_passes_step_metadata_only_when_custom_metadata_present(monkeypatch, DummyCtx_class) -> None:
    step_profile = StepProfile(distribution="io", step_name="convert")
    settings = ConvertSettings(
        overwrite=False,
        execution="serial",
        channel_labels=["GFP"],
        custom_metadata={"run_id": 42},
    )

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

        seen: dict[str, object] = {}

        def fake_build_step_project_metadata(*, existing_project_metadata, step_profile, user_name, step_metadata, channel_metadata):
            seen["step_metadata"] = step_metadata
            return {"pipeline": {"distribution": "io"}, "steps": {"convert": {"k": 1}}}

        monkeypatch.setattr(
            "fits.workflows.convert.build_step_project_metadata",
            fake_build_step_project_metadata,
        )

        dummy_reader = DummyReader(save_paths=[run_dir / "out_s1.tif"])
        monkeypatch.setattr("fits.workflows.convert.FitsIO.from_path", lambda p, channel_labels=None: dummy_reader)

        _ = run_convert(settings, state, step_profile, "fits_array.tif")

        assert seen["step_metadata"] == {"custom_metadata": {"run_id": 42}}


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