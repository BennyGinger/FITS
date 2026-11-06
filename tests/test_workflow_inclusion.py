"""The CLI rejects invalid included workflows before changing experiment files."""

from pathlib import Path

import pytest

from fits.environment.constant import StepName, WORKFLOW_ORDER
from fits.gui.settings import SettingsAdapter
from fits.pipeline import start_pipeline
from fits.workflows.file_management.rebuild import ProcessingPlan, execution_config
from fits.workflows.definitions.inputs import configured_profile
from fits.workflows.definitions.registry import REGISTRY


def test_cli_rejects_quantification_without_mask_producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Fail before artifact decisions, logging setup, conversion or any pipeline worker.
    """
    root = tmp_path / "run"
    root.mkdir()
    adapter = SettingsAdapter()
    adapter.run_dir = str(root)
    adapter.user_name = "Test"
    for step in WORKFLOW_ORDER:
        adapter.set_step_enabled(step, step == StepName.EXTRACT)
    settings = adapter.save(tmp_path / "settings.toml")
    monkeypatch.setattr("fits.pipeline.inspect_run", lambda *args: pytest.fail("Invalid workflow reached artifact inspection"))
    with pytest.raises(ValueError, match="Quantification requires Segmentation or Tracking"):
        start_pipeline(settings, terminal_progress=False)
    assert list(root.iterdir()) == []


def test_quantification_rebuild_reuses_the_included_edited_source(tmp_path: Path) -> None:
    """
    Keep accepted edits selected while limiting actual recomputation to Quantification.
    """
    config = {str(step): {"enabled": step in (StepName.SEGMENT, StepName.TRACK, StepName.EDIT_TRACK, StepName.EXTRACT),
                         "params": {"overwrite": False}} for step in WORKFLOW_ORDER}
    plan = ProcessingPlan(tmp_path, "update", {tmp_path: (str(StepName.EXTRACT),)}, ())
    effective = execution_config(config, plan)
    profile = configured_profile(REGISTRY[StepName.EXTRACT].profile, effective)
    assert profile.additional_artifacts == ("tracking",)
    assert profile.use_tracking_edits
    assert not effective[StepName.TRACK]["params"]["overwrite"]
    assert not effective[StepName.EDIT_TRACK]["params"]["overwrite"]
    assert effective[StepName.EXTRACT]["params"]["overwrite"]
