import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication
from tifffile import imwrite

from fits_io import FitsIO
from fits.environment.constant import StepName
from fits.gui.settings import SettingsAdapter, StepSettingsEditor
from fits.settings.models import ConvertSettings
from fits.tasks.convert import convert
from fits.workflows.definitions.registry import REGISTRY
from fits.workflows.experiments import ExperimentState


@pytest.mark.parametrize("initial", ["all", ["GFP", "BFP"]])
@pytest.mark.parametrize("text, indices", [(" GFP, BFP ", [1, 2]), ("BFP", [2]), ("ALL", [0, 1, 2])])
def test_gui_channel_selection_round_trip_and_conversion(tmp_path, initial, text, indices):
    app = QApplication.instance() or QApplication([])
    adapter = SettingsAdapter()
    labels = ["BF", "GFP", "BFP"]
    adapter.set_field_value(StepName.CONVERT, "channel_labels", labels)
    adapter.set_field_value(StepName.CONVERT, "export_channels", initial)
    editor = StepSettingsEditor(adapter, StepName.CONVERT)
    widget = editor.widgets["export_channels"]
    widget.setText(text)
    widget.editingFinished.emit()
    expected = "all" if len(indices) == 3 else [labels[i] for i in indices]
    assert adapter.field_value(StepName.CONVERT, "export_channels") == expected
    editor.sync_to_adapter()
    adapter.load(adapter.save(tmp_path / "settings.toml"))
    settings = ConvertSettings.model_validate(adapter.as_mapping()["convert"]["params"])
    assert settings.export_channels == expected

    raw = tmp_path / "input.tif"
    array = np.arange(2 * 3 * 4 * 5, dtype=np.uint16).reshape(2, 3, 4, 5)
    imwrite(raw, array, imagej=True, metadata={"axes": "TCYX"})
    results = convert(settings, ExperimentState.init(tmp_path, raw), REGISTRY[StepName.CONVERT].profile)
    output = FitsIO.from_path(results[0].artifact("image"))
    assert output.channel_labels == [labels[i] for i in indices]
    actual = output.get_array().array
    expected_array = array[:, indices] if len(indices) > 1 else array[:, indices[0]]
    np.testing.assert_array_equal(actual, expected_array)
    editor.close()
