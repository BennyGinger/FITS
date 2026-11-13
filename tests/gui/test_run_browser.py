import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication

from fisch.gui.main_window.run_browser import DirectoryBrowser, RunDirectoryBrowser


def _application() -> QApplication:
    """
    Return the shared widget application used by browser checks.
    """
    application = QApplication.instance() or QApplication([])
    assert isinstance(application, QApplication)
    return application


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
    browser = DirectoryBrowser()
    browser.set_root(tmp_path)
    app.processEvents()
    image_index = browser.model.index(str(image_path))
    assert image_index.isValid()

    browser._on_clicked(image_index)
    assert browser.selected_path == image_path.resolve()

    browser._on_clicked(image_index)
    assert browser.selected_path is None
    assert browser.tree.currentIndex().isValid() is False


def test_run_browser_preserves_multiple_selected_rows(tmp_path: Path) -> None:
    app = _application()
    paths = [tmp_path / "first", tmp_path / "second"]
    for path in paths:
        path.mkdir()
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    app.processEvents()
    selection = browser.tree.selectionModel()
    flags = (QItemSelectionModel.SelectionFlag.Select
             | QItemSelectionModel.SelectionFlag.Rows)
    for path in paths:
        index = browser.model.index(str(path))
        selection.select(index, flags)
        browser._on_clicked(index)
    # Clicking the current row must not clear the extended selection.
    browser._on_clicked(browser.model.index(str(paths[-1])))
    assert {Path(browser.model.filePath(index))
            for index in selection.selectedRows()} == set(paths)


def test_browser_can_promote_a_folder_selection_to_its_artifact(tmp_path: Path) -> None:
    app = _application()
    experiment = tmp_path / "experiment"
    experiment.mkdir()
    artifact = experiment / "proc_array.tif"
    artifact.touch()
    browser = RunDirectoryBrowser()
    browser.set_root(tmp_path)
    app.processEvents()

    assert browser.select_path(artifact) is True
    assert browser.selected_path == artifact.resolve()
    assert browser.selection_label.text() == "Selected: experiment/proc_array.tif"


def test_viewer_browser_reveals_and_highlights_ancestors_without_selecting_them(tmp_path: Path) -> None:
    """
    Show the active experiment path in the tree instead of a wrapping label below it.
    """
    app = _application()
    experiment = tmp_path / "condition" / "acquisition" / "series_1"
    experiment.mkdir(parents=True)
    artifact = experiment / "proc_array.tif"
    artifact.touch()
    browser = DirectoryBrowser(highlight_selection_path=True)
    browser.set_root(tmp_path)
    assert browser.select_path(artifact)
    app.processEvents()
    assert browser.selection_label.isHidden()
    assert browser.selected_path == artifact
    expected = {artifact, experiment, experiment.parent, experiment.parent.parent, tmp_path}
    assert browser.model.highlighted_paths == expected
    for parent in (experiment, experiment.parent, experiment.parent.parent):
        index = browser.model.index(str(parent))
        assert browser.tree.isExpanded(index)
        assert browser.model.data(index, Qt.ItemDataRole.BackgroundRole) == app.palette().color(QPalette.ColorRole.Highlight)
    selected = browser.tree.selectionModel().selectedRows()
    assert [Path(browser.model.filePath(index)) for index in selected] == [artifact]
    other = tmp_path / "other"
    other.mkdir()
    assert browser.select_path(other)
    assert browser.model.highlighted_paths == {tmp_path, other}
    browser._on_clicked(browser.model.index(str(other)))
    assert not browser.model.highlighted_paths
    assert browser.selected_path is None
    browser.close()


def test_viewer_browser_uses_reclaimed_path_label_height_for_the_tree(tmp_path: Path) -> None:
    """
    Keep long experiment names from consuming vertical browser space.
    """
    app = _application()
    experiment = tmp_path / ("long_condition_" * 4) / ("long_acquisition_" * 3) / "series_1"
    experiment.mkdir(parents=True)
    artifact = experiment / "proc_array.tif"
    artifact.touch()
    default = DirectoryBrowser()
    viewer = DirectoryBrowser(highlight_selection_path=True)
    for browser in (default, viewer):
        browser.resize(360, 300)
        browser.set_root(tmp_path)
        browser.select_path(artifact)
        browser.show()
    app.processEvents()
    assert viewer.tree.height() > default.tree.height()
    default.close()
    viewer.close()


def test_run_selection_display_wraps_by_reducing_tree_height(tmp_path: Path) -> None:
    """
    Keep the run browser size fixed while a long selected path takes height from the tree.
    """
    app = _application()
    short = tmp_path / 'series_1'
    long = tmp_path / ('long_condition_' * 4) / ('long_acquisition_' * 3) / 'series_1'
    short.mkdir()
    long.mkdir(parents=True)
    browsers = [RunDirectoryBrowser(), RunDirectoryBrowser()]
    for browser, path in zip(browsers, (short, long)):
        browser.resize(540, 360)
        browser.set_root(tmp_path)
        browser.select_path(path)
        browser.show()
    app.processEvents()
    assert browsers[1].selection_label.height() > browsers[0].selection_label.height()
    assert browsers[1].tree.height() < browsers[0].tree.height()
    assert browsers[1].size() == browsers[0].size()
    for browser in browsers:
        browser.close()


def test_double_click_activates_file_path(tmp_path: Path) -> None:
    app = _application()
    report = tmp_path / "report_20260911_090000.txt"
    report.touch()
    browser = RunDirectoryBrowser()
    activated = []
    browser.path_activated.connect(activated.append)
    browser.set_root(tmp_path)
    app.processEvents()

    browser._on_activated(browser.model.index(str(report)))

    assert activated == [report.resolve()]
