import os
from shutil import copyfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest
import tifffile
from fits_io import FitsIO
from PySide6.QtWidgets import QApplication

from fits.gui.main_window import FitsMainWindow
from fits.gui.settings import SettingsAdapter
from fits.gui.viewer.registration import RegistrationTunerWindow
from fits.gui.viewer.segmentation import SegmentationTunerWindow

_APP = None


@pytest.fixture(autouse=True)
def application(monkeypatch):
    global _APP
    _APP = QApplication.instance() or QApplication([])
    monkeypatch.setattr(SegmentationTunerWindow, "_initialize_selected_model", lambda self: None)


@pytest.fixture
def images(tmp_path):
    paths = []
    for name, intensity in (("a_first", 10), ("b_selected", 20)):
        folder = tmp_path / name
        folder.mkdir()
        path = folder / "fits_array.tif"
        array = np.full((3, 2, 16, 16), intensity, dtype=np.uint16)
        input_path = folder / "input.tif"
        tifffile.imwrite(input_path, array,
                         imagej=True, metadata={"axes": "TCYX", "Labels": ["GFP", "RFP"]})
        FitsIO.from_path(input_path).save_array(
            array, channel_labels=("GFP", "RFP"), output_path=path)
        paths.append(path)
    return paths


@pytest.mark.parametrize("tuner_class", [SegmentationTunerWindow, RegistrationTunerWindow])
@pytest.mark.parametrize("selection", [None, "folder", "image", "sibling"])
def test_tuner_opens_and_reveals_initial_image(tuner_class, selection, images, tmp_path):
    first, selected = images
    initial = None
    if selection == "folder":
        initial = selected.parent
    elif selection == "image":
        initial = selected
    elif selection == "sibling":
        initial = selected.parent / "fits_track.tif"
        initial.touch()
    tuner = tuner_class(tmp_path, initial_path=initial)
    try:
        expected = first if initial is None else selected
        assert tuner._source_path == expected, tuner.status_label.text()
        assert tuner.directory_browser.selected_path == expected
        assert tuner.image_viewer.image_item.image is not None
        assert np.all(tuner.image_viewer.image_item.image == (10 if initial is None else 20))
    finally:
        tuner.close()


@pytest.mark.parametrize("tuner_class", [SegmentationTunerWindow, RegistrationTunerWindow])
def test_choosing_a_directory_opens_first_image(tuner_class, images, tmp_path):
    tuner = tuner_class()
    try:
        tuner._set_experiments_directory(tmp_path)
        assert tuner._source_path == images[0], tuner.status_label.text()
    finally:
        tuner.close()


@pytest.mark.parametrize("tuner_class", [SegmentationTunerWindow, RegistrationTunerWindow])
def test_image_in_selected_folder_takes_priority_over_subfolders(tuner_class, images, tmp_path):
    source = tmp_path / "fits_array.tif"
    copyfile(images[1], source)
    tuner = tuner_class(tmp_path)
    try:
        assert tuner._source_path == source, tuner.status_label.text()
    finally:
        tuner.close()


@pytest.mark.parametrize("tuner_class", [SegmentationTunerWindow, RegistrationTunerWindow])
def test_selected_empty_experiment_does_not_open_another(tuner_class, images, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    tuner = tuner_class(tmp_path, initial_path=empty)
    try:
        assert tuner._source_path is None
        assert "No fits_array.tif" in tuner.status_label.text()
    finally:
        tuner.close()


@pytest.mark.parametrize("kind", ["segmentation", "registration"])
@pytest.mark.parametrize("select_experiment", [False, True])
def test_main_gui_passes_selected_experiment(kind, select_experiment, images, tmp_path):
    adapter = SettingsAdapter()
    adapter.run_dir = str(tmp_path)
    adapter.set_segment_channels([{"channel": "GFP"}])
    main = FitsMainWindow(adapter)
    tuner = None
    try:
        if select_experiment:
            assert main.run_browser.select_path(images[1].parent)
        if kind == "segmentation":
            main._open_segmentation_tuner()
            tuner = main._segmentation_tuner
        else:
            main._open_registration_tuner("channel")
            tuner = main._registration_tuner
            assert tuner.mode() == "channel"
        expected = images[1] if select_experiment else images[0]
        assert tuner._source_path == expected, tuner.status_label.text()
        assert tuner.directory_browser.selected_path == expected
    finally:
        if tuner is not None:
            tuner.close()
        main.close()
