import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from fits.gui.run_browser import RunDirectoryBrowser


def _application() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_run_browser_is_rooted_at_selected_directory(tmp_path: Path) -> None:
    _application()
    (tmp_path / "experiment").mkdir()
    (tmp_path / "image.tif").touch()
    browser = RunDirectoryBrowser()

    browser.set_root(tmp_path)

    assert browser.root_path == tmp_path.resolve()
    assert browser.selected_path == tmp_path.resolve()
    assert browser.tree.isHidden() is False


def test_run_browser_stays_blank_without_run_directory() -> None:
    _application()
    browser = RunDirectoryBrowser()

    assert browser.root_path is None
    assert browser.tree.isHidden() is False
    assert browser.tree.model() is browser.empty_model
    assert browser.title_label.isHidden() is False
    assert browser.selection_label.isHidden() is True


def test_setting_same_root_preserves_tree_state(tmp_path: Path) -> None:
    _application()
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    browser.tree.setExpanded(browser.tree.rootIndex(), True)

    browser.set_root(tmp_path)

    assert browser.tree.isExpanded(browser.tree.rootIndex()) is True


def test_clicking_selected_path_again_clears_selection(tmp_path: Path) -> None:
    app = _application()
    image_path = tmp_path / "image.tif"
    image_path.touch()
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    app.processEvents()
    image_index = browser.model.index(str(image_path))
    assert image_index.isValid()

    browser._on_clicked(image_index)
    assert browser.selected_path == image_path.resolve()

    browser._on_clicked(image_index)
    assert browser.selected_path is None
    assert browser.tree.currentIndex().isValid() is False


def test_browser_can_promote_a_folder_selection_to_its_artifact(tmp_path: Path) -> None:
    app = _application()
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    artifact = experiment / "fits_array.tif"
    artifact.touch()
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    app.processEvents()

    assert browser.select_path(artifact) is True
    assert browser.selected_path == artifact.resolve()
    assert browser.selection_label.text() == "Selected: experiment/fits_array.tif"
