"""Check recorded file relationships and their conflict-review presentation."""

from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication, QGraphicsRectItem, QGraphicsTextItem
from fits_io.metadata.models import FitsIOMeta

from fits.environment import constant as cst
from fits.gui.artifact_lineage import ArtifactLineageWidget, file_lineage
from fits.workflows.checks.models import ArtifactRecord, PreflightReport


_APP: QApplication | None = None


def _application() -> QApplication:
    """
    Retain the Qt application for all widgets in this test module.
    """
    global _APP
    existing = QApplication.instance()
    _APP = existing if isinstance(existing, QApplication) else QApplication([])
    return _APP


def _record(path: Path, step: str, *inputs: str, problem: str = "") -> ArtifactRecord:
    """
    Build a report record with saved input paths without creating image files.
    """
    metadata = FitsIOMeta().new_revision([{"artifact_path": source} for source in inputs])
    return ArtifactRecord(path, step, metadata, problem)


def test_saved_branches_and_overwrite_impact(tmp_path: Path) -> None:
    """
    Keep independent analysis branches separate and color the requested overwrite.
    """
    raw, background, masks, extract, distance = (tmp_path / name for name in (
        "raw.tif", "background.tif", "masks.tif", "extract.parquet", "distance.parquet"))
    report = PreflightReport((
        _record(raw, cst.StepName.CONVERT, "../source.nd2"),
        _record(background, cst.StepName.BG_SUB, raw.name),
        _record(masks, cst.StepName.SEGMENT, background.name, problem="Input revision differs"),
        _record(extract, cst.StepName.EXTRACT, masks.name, background.name),
        _record(distance, cst.StepName.DISTANCE_PROFILE, masks.name),
    ), (cst.StepName.BG_SUB,), (cst.StepName.SEGMENT, cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE), ())
    graph = file_lineage(report, tmp_path)
    nodes = {node.path: node for node in graph.nodes}
    assert nodes[background].role == "selected"
    assert nodes[raw].role == "input"
    assert nodes[masks].role == nodes[extract].role == nodes[distance].role == "affected"
    assert nodes[masks].problem == "Input revision differs"
    assert set(graph.edges) == {
        ((tmp_path.parent / "source.nd2"), raw), (raw, background), (background, masks),
        (masks, extract), (background, extract), (masks, distance),
    }


def test_preserved_legacy_and_planned_outputs_have_no_invented_edges(tmp_path: Path) -> None:
    """
    Show older results as preserved and new rebuild files without guessed lineage.
    """
    old, new = tmp_path / "fits_array.tif", tmp_path / cst.FITS_ARRAY_RAW
    metadata = FitsIOMeta.from_dict({"fits_io": {"derived_from": "old source"}})
    report = PreflightReport((ArtifactRecord(old, cst.StepName.CONVERT, metadata, "Old format", True),),
                             (cst.StepName.CONVERT,), (), (), ((cst.StepName.CONVERT, new),))
    graph = file_lineage(report, tmp_path)
    nodes = {node.path: node for node in graph.nodes}
    assert nodes[old].legacy
    assert nodes[old].role == "conflict"
    assert nodes[new].new_output
    assert graph.edges == ()


def test_experiment_scope_and_cyclic_metadata(tmp_path: Path) -> None:
    """
    Follow saved ancestors safely without including unrelated experiment files.
    """
    first, second = tmp_path / "first", tmp_path / "second"
    a, b, unrelated = first / "a.tif", first / "b.tif", second / "other.tif"
    report = PreflightReport((_record(a, cst.StepName.CONVERT, b.name),
                              _record(b, cst.StepName.BG_SUB, a.name),
                              _record(unrelated, cst.StepName.CONVERT)), (), (), ())
    graph = file_lineage(report, first)
    assert {node.path for node in graph.nodes} == {a, b}
    assert set(graph.edges) == {(a, b), (b, a)}


def test_widget_experiment_selector_and_file_details(tmp_path: Path) -> None:
    """
    Expose exact paths and reasons when a user selects a file in the diagram.
    """
    _application()
    first, second = tmp_path / "first" / "raw.tif", tmp_path / "second" / "raw.tif"
    report = PreflightReport((_record(first, cst.StepName.CONVERT, problem="Changed input"),
                              _record(second, cst.StepName.CONVERT)), (), (), ())
    widget = ArtifactLineageWidget(report)
    assert widget.experiments.count() == 2
    card = next(item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem))
    labels = [item.toPlainText() for item in card.childItems() if isinstance(item, QGraphicsTextItem)]
    assert any(first.name in label and "Existing conflict" in label for label in labels)
    card.setSelected(True)
    assert str(first) in widget.details.text()
    assert "Changed input" in widget.details.text()
    widget.experiments.setCurrentIndex(1)
    cards = [item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem)]
    assert [card.data(0) for card in cards] == [second]
    widget.close()


def test_horizontal_flow_keeps_parallel_analysis_branches(tmp_path: Path) -> None:
    """
    Read processing left to right while keeping independent analyses side by side vertically.
    """
    _application()
    raw, background, masks, extract, distance = (tmp_path / name for name in (
        "raw.tif", "background.tif", "masks.tif", "extract.parquet", "distance.parquet"))
    report = PreflightReport((
        _record(raw, cst.StepName.CONVERT, "../source.nd2"),
        _record(background, cst.StepName.BG_SUB, raw.name),
        _record(masks, cst.StepName.SEGMENT, background.name),
        _record(extract, cst.StepName.EXTRACT, masks.name, background.name),
        _record(distance, cst.StepName.DISTANCE_PROFILE, masks.name),
    ), (cst.StepName.BG_SUB,), (cst.StepName.SEGMENT, cst.StepName.EXTRACT, cst.StepName.DISTANCE_PROFILE), ())
    widget = ArtifactLineageWidget(report)
    cards = {item.data(0): item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem)}
    chain = [tmp_path.parent / "source.nd2", raw, background, masks, extract]
    assert all(cards[source].x() < cards[target].x() for source, target in zip(chain, chain[1:]))
    assert len({cards[path].y() for path in chain[:-1]}) == 1
    assert cards[extract].x() == cards[distance].x()
    assert cards[extract].y() != cards[distance].y()
    widget.close()


@pytest.mark.parametrize("rerun,affected_masks", [(cst.StepName.BG_SUB, False),
                                                (cst.StepName.REGISTER_TIME, True),
                                                (cst.StepName.REGISTER_CHANNEL, True)])
def test_manual_masks_branch_from_geometry_not_intensity(tmp_path: Path, rerun: str, affected_masks: bool) -> None:
    """
    Preserve manual drawings through intensity reruns and flag registration review.
    """
    _application()
    raw, registered, background = (tmp_path / name for name in ("raw.tif", "registered.tif", "background.tif"))
    ref, roi = tmp_path / "fits_ref_edge.tif", tmp_path / "fits_roi_area.tif"
    metadata = FitsIOMeta().with_custom_metadata({"registration_revisions": ["saved registration"]})
    # Inherited intensity provenance must not turn manual drawings into intensity dependents.
    drawing = metadata.new_revision([{"artifact_path": background.name}])
    registration = rerun if rerun != cst.StepName.BG_SUB else cst.StepName.REGISTER_TIME
    report = PreflightReport((_record(raw, cst.StepName.CONVERT, "../original.nd2"),
                              ArtifactRecord(registered, registration, metadata.new_revision()),
                              _record(background, cst.StepName.BG_SUB, registered.name),
                              ArtifactRecord(ref, None, drawing), ArtifactRecord(roi, None, drawing)),
                             (rerun,), (cst.StepName.SEGMENT,), ())
    graph = file_lineage(report, tmp_path)
    nodes = {node.path: node for node in graph.nodes}
    assert nodes[ref].role == nodes[roi].role == ("affected" if affected_masks else "input")
    assert set(graph.geometry_edges) == {(registered, ref), (registered, roi)}
    assert all(target not in (ref, roi) for _, target in graph.edges)
    widget = ArtifactLineageWidget(report)
    cards = {item.data(0): item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem)}
    for path in (ref, roi):
        assert cards[path].y() > cards[background].sceneBoundingRect().bottom()
        assert cards[path].x() > cards[registered].x()
    markers = [item.toPlainText() for item in widget.scene.items() if isinstance(item, QGraphicsTextItem)]
    assert "↓ RERUN THIS FILE" in markers
    widget.close()


def test_ctrl_wheel_zooms_but_ordinary_wheel_does_not(tmp_path: Path) -> None:
    """
    Zoom in and out with Ctrl while preserving the ordinary scrolling gesture.
    """
    app = _application()
    report = PreflightReport((_record(tmp_path / "raw.tif", cst.StepName.CONVERT),), (), (), ())
    widget = ArtifactLineageWidget(report)
    widget.resize(800, 400)
    widget.show()
    app.processEvents()
    view = widget.view

    def wheel(delta: int, modifiers: Qt.KeyboardModifier) -> None:
        """
        Send a real wheel event through the graphics view viewport.
        """
        event = QWheelEvent(QPointF(100, 100), QPointF(view.viewport().mapToGlobal(QPoint(100, 100))),
                            QPoint(), QPoint(0, delta), Qt.MouseButton.NoButton,
                            modifiers, Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(view.viewport(), event)

    initial = view.transform().m11()
    wheel(120, Qt.KeyboardModifier.ControlModifier)
    assert view.transform().m11() == pytest.approx(initial * 1.25)
    wheel(-120, Qt.KeyboardModifier.ControlModifier)
    assert view.transform().m11() == pytest.approx(initial)
    wheel(120, Qt.KeyboardModifier.NoModifier)
    assert view.transform().m11() == pytest.approx(initial)
    widget.close()
