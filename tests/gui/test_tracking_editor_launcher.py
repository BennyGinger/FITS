"""The main GUI opens tracking editing separately from pipeline execution."""

from collections.abc import Iterator
from pathlib import Path

import numpy as np
import pytest
import tifffile
from scope_io import ScopeIO
from PySide6.QtWidgets import QApplication, QWidget

from fisch.environment import constant as cst
from fisch.gui.main_window import FischMainWindow
from fisch.gui.settings import SettingsAdapter


@pytest.fixture
def main_window(tmp_path: Path) -> Iterator[FischMainWindow]:
    """
    Start with a saved setting that previously included the interactive pipeline step.
    """
    app = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.user_name = "Test"
    adapter.set_step_enabled(cst.StepName.EDIT_TRACK, True)
    window = FischMainWindow(adapter)
    app.processEvents()
    yield window
    window.close()
    app.processEvents()


def _write_artifact(root: Path, folder: str, name: str, kind: cst.ArtifactType) -> Path:
    """
    Write a current FIScH artifact so eligibility uses real run inventory metadata.
    """
    directory = root / folder
    directory.mkdir(parents=True, exist_ok=True)
    raw = directory / "source.tif"
    array = np.ones((4, 4), dtype=np.uint16)
    tifffile.imwrite(raw, array, photometric="minisblack")
    reader = ScopeIO.from_path(raw)
    payload = reader.build_payload(export_channels="all", artifact_type=kind,
                                   custom_metadata={"pipeline_meta": {"version": "5.0.0"}}).new_revision([])
    return reader.save_array(array, metadata=payload, output_path=directory / name)


def test_editing_is_absent_from_pipeline_and_requires_tracking(main_window: FischMainWindow, tmp_path: Path) -> None:
    """
    Hide the step and keep image/segmentation-only or internal-history runs ineligible.
    """
    assert cst.StepName.EDIT_TRACK not in main_window._editors
    assert not main_window.adapter.step_enabled(cst.StepName.EDIT_TRACK)
    assert not main_window.tracking_edit_button.isEnabled()
    _write_artifact(tmp_path, "experiment", cst.MASK_SEG, cst.ARTI_SEG)
    _write_artifact(tmp_path, ".pipeline/backup", cst.MASK_TRACK, cst.ARTI_TRACK)
    main_window._refresh_run_inventory()
    assert not main_window.tracking_edit_button.isEnabled()
    tracking = _write_artifact(tmp_path, "experiment", cst.MASK_TRACK, cst.ARTI_TRACK)
    main_window._refresh_run_inventory()
    assert main_window.tracking_edit_button.isEnabled()
    assert main_window._tracking_edit_sources() == [tracking]
    tools = main_window.extra_tools.layout()
    assert tools is not None
    assert tools.indexOf(main_window.tracking_edit_button) == tools.indexOf(main_window.tracking_viewer_button) + 1
    main_window._running = True
    main_window._refresh_tracking_viewer_button()
    assert not main_window.tracking_edit_button.isEnabled()
    main_window._running = False


def test_edit_button_opens_selected_tracking_with_existing_editor_api(main_window: FischMainWindow,
                                                                     tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch,
                                                                     ) -> None:
    """
    Pass editing mode and the chosen saved track without involving viewer implementation.
    """
    first = _write_artifact(tmp_path, "first", cst.MASK_TRACK, cst.ARTI_TRACK)
    selected = _write_artifact(tmp_path, "selected", cst.MASK_TRACK, cst.ARTI_TRACK)
    opened: list[Path] = []

    class Editor(QWidget):
        def __init__(self, *, experiments_dir: str, tracking_path: Path, editing_enabled: bool,
                     parent: QWidget | None = None) -> None:
            """
            Record only the supported public constructor arguments.
            """
            super().__init__(parent)
            assert experiments_dir == str(tmp_path)
            assert editing_enabled
            opened.append(tracking_path)

    monkeypatch.setattr("fisch.gui.viewer.tracking.TrackingViewerWindow", Editor)
    main_window._refresh_run_inventory()
    assert main_window.run_browser.select_path(selected.parent)
    main_window.tracking_edit_button.click()
    main_window.tracking_edit_button.click()
    assert opened == [selected]
    assert main_window.run_browser.select_path(tmp_path)
    assert main_window._manual_tracking_editor is not None
    main_window._manual_tracking_editor.close()
    main_window._manual_tracking_editor = None
    main_window.tracking_edit_button.click()
    assert opened == [selected, first]


def test_gui_cannot_restore_hidden_editing_as_a_pipeline_step(main_window: FischMainWindow,
                                                            tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch,
                                                            ) -> None:
    """
    Prevent saved flags and reviewed maintenance scopes from reopening pipeline editing.
    """
    from fisch.workflows.file_management.rebuild import ProcessingPlan

    main_window.adapter.set_step_enabled(cst.StepName.EDIT_TRACK, True)
    main_window._sync_identity()
    assert not main_window.adapter.step_enabled(cst.StepName.EDIT_TRACK)
    main_window._maintenance_plan = ProcessingPlan(tmp_path, "update",
                                                  {tmp_path: (str(cst.StepName.EDIT_TRACK),)}, ())
    monkeypatch.setattr(main_window, "_save_settings", lambda: pytest.fail("Unavailable pipeline step reached saving"))
    main_window._launch_pipeline(convert_only=False)
    assert "Edit tracking is temporarily unavailable inside the pipeline" in main_window.console.toPlainText()
    assert main_window._thread is None
