"""Exercise shared decisions and compact publication on the Qt main thread."""
import os
from pathlib import Path
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import numpy as np
import pytest
import tifffile
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QDialog, QPushButton
from scope_io import ScopeIO

from fits.workflows.file_management.compaction import plan_compaction
from fits.environment import constant as cst
from fits.gui.file_management.compaction import publish_compaction
from fits.gui.artifact_decisions import choose_artifacts
from fits.workflows.checks.models import ArtifactRecord, PreflightReport
from fits.workflows.experiments import ExperimentState, save_experiment_state, discover_saved_states

_APP: QApplication | None = None


def application() -> QApplication:
    """
    Keep the Qt application alive while testing the real review choices.
    """
    global _APP
    current = QApplication.instance()
    _APP = current if isinstance(current, QApplication) else QApplication([])
    return _APP


@pytest.mark.parametrize('title,expected,legacy', [
    ('Selected step only', 'selected', False),
    ('Selected step and downstream', 'rebuild', False),
    ('Cancel', 'cancel', False), ('Rebuild results…', 'rebuild', True)])
@pytest.mark.parametrize('outdated_master', [False, True])
def test_shared_preflight_choices(tmp_path: Path, title: str, expected: str, legacy: bool, outdated_master: bool) -> None:
    """
    Keep normal overwrite choices available even when downstream combined analysis is outdated.
    """
    app = application()
    path = tmp_path / cst.FITS_ARRAY_BGSUB
    report = PreflightReport((ArtifactRecord(path, cst.StepName.BG_SUB, None,
        'Input revision differs', legacy),), (cst.StepName.BG_SUB,), (cst.StepName.SEGMENT,), (),
        outdated_masters=(tmp_path / cst.MASTER_QUANTI_NAME,) if outdated_master else ())
    def choose() -> None:
        """
        Select the expected action from the actual modal review window.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        button = next(button for button in dialog.findChildren(QPushButton) if button.text() == title)
        button.click()
    QTimer.singleShot(0, choose)
    assert choose_artifacts(report) == expected


def test_gui_compact_worker_publishes_and_updates_state(tmp_path):
    application()
    original = tmp_path / 'source.tif'
    pixels = np.ones((8, 8), dtype=np.uint16)
    tifffile.imwrite(original, pixels, photometric='minisblack')
    reader = ScopeIO.from_path(original)
    payload = reader.build_payload(export_channels='all', artifact_type=cst.ARTI_IMG_RAW,
        custom_metadata={'pipeline_meta': {'version': '4.0.0'}}).new_revision()
    raw = reader.save_array(pixels, metadata=payload, output_path=tmp_path / cst.FITS_ARRAY_RAW)
    state = ExperimentState.init(tmp_path, original).with_complete_step(
        step_name=cst.StepName.CONVERT, artifact_kind=cst.ARTI_IMG_RAW, artifact_path=raw)
    save_experiment_state(state)
    result = publish_compaction(plan_compaction(tmp_path))
    assert result == (tmp_path / cst.FITS_ARRAY_NAME,)
    assert discover_saved_states(tmp_path)[0].compacted
    assert not raw.exists()
