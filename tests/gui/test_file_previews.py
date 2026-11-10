"""Verify visual plans agree with migration, rebuild and compaction actions."""

from pathlib import Path

import numpy as np
import tifffile
from PySide6.QtCore import QPointF, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QCheckBox, QDialog, QGraphicsPathItem, QGraphicsRectItem, QGraphicsTextItem, QTreeWidget, QTreeWidgetItem

from fisch.environment import constant as cst
from fisch.gui.file_preview.compaction import compaction_groups
from fisch.gui.file_preview.changes import FileChangesWidget
from fisch.gui.file_preview.migration import MigrationPreviewWidget
from fisch.gui.file_management.manager import confirm_files, confirm_migration
from fisch.gui.file_preview.graphics import wrapped_filename
from fisch.gui.file_preview.models import PreviewFile, PreviewGroup
from fisch.gui.file_preview.overview import run_overview
from fisch.gui.file_preview.portable import portable_changes, portable_groups
from fisch.gui.file_preview.processing import processing_groups
from fisch.gui.file_preview.widget import FilePreviewWidget
from fisch.workflows.file_management import api
from fisch.workflows.file_management.compaction import plan_compaction
from fisch.workflows.artifacts.provenance import read_metadata
from scope_io import ScopeIO
from test_file_management import legacy_run


_APP: QApplication | None = None


def _application() -> QApplication:
    """
    Retain a QApplication for all graphics checks in this module.
    """
    global _APP
    app = QApplication.instance()
    _APP = app if isinstance(app, QApplication) else QApplication([])
    return _APP


def _row(tree: QTreeWidget, *indices: int) -> QTreeWidgetItem:
    """
    Return a required row from the grouped stage list.
    """
    row = tree.topLevelItem(indices[0])
    assert row is not None
    for index in indices[1:]:
        row = row.child(index)
        assert row is not None
    return row


def test_migration_preview_matches_published_names(tmp_path: Path) -> None:
    """
    Derive rename arrows from ordered real moves and preserve the migration's pixels.
    """
    _, old, pixels = legacy_run(tmp_path)
    plan = api.plan_migration(tmp_path)
    assert plan is not None
    groups = portable_groups(plan)
    files = groups[0].files
    renamed = next(item for item in files if item.path.name == cst.ARRAY_BGSUB)
    assert renamed.action == 'rename'
    assert renamed.source == old.workdir / cst.ARRAY_NAME
    assert not renamed.path.exists()
    original = next(item for item in files if item.title == 'Original')
    assert original.stage < renamed.stage
    states = api.migrate(plan)
    assert states[0].workdir == groups[0].directory
    assert all(item.path.is_file() for item in files)
    np.testing.assert_array_equal(tifffile.imread(renamed.path), pixels)


def test_rebuild_preview_uses_profile_inputs_and_disabled_stage_bypass(tmp_path: Path) -> None:
    """
    Show actual planned outputs and bypass disabled registration stages in their arrows.
    """
    adapter, _, _ = legacy_run(tmp_path)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    api.migrate(migration)
    adapter.set_step_enabled(cst.StepName.REGISTER_CHANNEL, True)
    adapter.set_step_enabled(cst.StepName.REGISTER_TIME, False)
    adapter.save_to_run_dir()
    plan = api.plan_full_rebuild(tmp_path)
    assert plan is not None
    before = {path: path.read_bytes() for path in tmp_path.rglob('*.tif')}
    group = processing_groups(plan)[0]
    files = {item.path.name: item for item in group.files}
    assert files[cst.ARRAY_RAW].action == 'create'
    assert files[cst.ARRAY_REG_CHANNEL].action == 'create'
    assert files[cst.ARRAY_BGSUB].action == 'rebuild'
    assert cst.ARRAY_REG_TIME not in files
    folder = group.directory
    assert (folder / cst.ARRAY_RAW, folder / cst.ARRAY_REG_CHANNEL) in group.edges
    assert (folder / cst.ARRAY_REG_CHANNEL, folder / cst.ARRAY_BGSUB) in group.edges
    assert group.planned_edges
    assert all(path.read_bytes() == content for path, content in before.items())


def test_path_update_lists_tables_and_expected_ids(tmp_path: Path) -> None:
    """
    Explain experiment and master updates without reading or rerunning measurements.
    """
    legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    api.migrate(migration)
    import pandas as pd
    master = tmp_path / cst.MASTER_QUANTI_NAME
    frame = pd.read_parquet(master)
    frame['condition_level_1'] = 'old condition'
    frame.to_parquet(master, index=False)
    plan = api.plan_update(tmp_path)
    assert plan is not None
    changes = portable_changes(plan)
    table = next(item for item in changes if item.path.name == cst.MASTER_QUANTI_NAME)
    assert table.action == 'Update paths and tags'
    assert 'condition tags' in table.detail
    assert not any(item.path.name == cst.QUANTI_NAME for item in changes)
    _application()
    widget = FileChangesWidget(changes)
    try:
        assert 'condition tags' in widget.details.text()
    finally:
        widget.close()


def test_compaction_preview_keeps_final_and_marks_only_superseded_files(tmp_path: Path) -> None:
    """
    Show the canonical rename once and match every other removal to the real plan.
    """
    legacy_run(tmp_path)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    api.migrate(migration)
    plan = plan_compaction(tmp_path)
    groups = compaction_groups(plan)
    final = next(item for item in groups[0].files if item.path.name == cst.ARRAY_NAME)
    assert final.action == 'rename' and final.source == plan.selections[0].image
    assert all(item.path in plan.remove for item in groups[0].files if item.action == 'remove')
    assert not any(item.path == final.source for item in groups[0].files if item.action == 'remove')
    assert any(item.title == 'Original' and item.action == 'keep' for item in groups[0].files)


def test_document_rendering_wraps_names_and_marks_creation_and_rename(tmp_path: Path) -> None:
    """
    Render true rename text and dashed prospective files with selectable path details.
    """
    _application()
    old = tmp_path / cst.ARRAY_NAME
    renamed = tmp_path / cst.ARRAY_BGSUB
    created = tmp_path / cst.ARRAY_REG_CHANNEL
    files = (PreviewFile(renamed, 'Background-subtracted', 'rename', source=old),
             PreviewFile(created, 'Channel-shifted', 'create', stage=1))
    widget = FilePreviewWidget((PreviewGroup(tmp_path, files),))
    try:
        cards = {member.path: item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem) for member in item.data(1).files}
        labels = [item for item in cards[renamed].childItems() if isinstance(item, QGraphicsTextItem)]
        assert any('<s>' in item.toHtml() or 'text-decoration: line-through' in item.toHtml() for item in labels)
        assert any('↓' in item.toPlainText() for item in labels)
        icons = [item for item in cards[created].childItems() if isinstance(item, QGraphicsPathItem)]
        assert any(item.pen().style() == Qt.PenStyle.DashLine for item in icons)
        cards[renamed].setSelected(True)
        assert widget.details.stage is not None
        assert widget.details.stage.files[0].source == old
        assert _row(widget.details.tree, 0, 0, 0).text(0) == f'{old.name} → {renamed.name}'
        wrapped = wrapped_filename(cst.ARRAY_REG_CHANNEL, width=12)
        assert wrapped.replace('\n', '') == cst.ARRAY_REG_CHANNEL
        assert '\n' in wrapped
        assert wrapped_filename(cst.QUANTI_NAME).splitlines()[-1].endswith('.parquet')
    finally:
        widget.close()


def test_compartment_and_manual_mask_preview_keeps_branch_roles(tmp_path: Path) -> None:
    """
    Show optional mb/cyto exports and preserve manual drawings when registration is bypassed.
    """
    adapter, _, _ = legacy_run(tmp_path, masks=True)
    migration = api.plan_migration(tmp_path)
    assert migration is not None
    states = api.migrate(migration)
    state = states[0]
    ref = state.workdir / cst.REFERENCE_TEMPLATE.format(label='edge')
    roi = state.workdir / cst.ROI_TEMPLATE.format(label='area')
    image = state.workdir / cst.ARRAY_BGSUB
    reader = ScopeIO.from_path(image)
    metadata = read_metadata(image)
    for path, kind in ((ref, cst.ARTI_REF), (roi, cst.ARTI_ROI)):
        reader.save_array(np.ones((8, 8), dtype=np.uint16), output_path=path,
                          metadata=metadata.with_artifact(artifact_type=kind).new_revision())
    adapter.set_step_enabled(cst.StepName.EXTRACT, True)
    adapter.set_field_value(cst.StepName.EXTRACT, 'compartments', True)
    adapter.set_field_value(cst.StepName.EXTRACT, 'save_compartment_masks', True)
    adapter.save_to_run_dir()
    plan = api.plan_full_rebuild(tmp_path)
    assert plan is not None
    group = processing_groups(plan)[0]
    files = {item.path: item for item in group.files}
    source = state.workdir / cst.MASK_SEG
    for suffix, title in (('mb', 'Membrane'), ('cyto', 'Cytoplasm')):
        output = source.with_name(f'{source.stem}_{suffix}.tif')
        assert files[output].action == 'create'
        assert files[output].title.startswith(title)
        assert (source, output) in group.edges
    assert files[ref].action == files[roi].action == 'keep'
    assert (ref, state.workdir / cst.QUANTI_NAME) in group.edges
    assert (roi, state.workdir / cst.QUANTI_NAME) not in group.edges


def test_opening_scale_sequence_arrows_and_background_selection(tmp_path: Path) -> None:
    """
    Open long workflows at readable size and clear short descriptions on background clicks.
    """

    app = _application()
    files = tuple(PreviewFile(tmp_path / f'file_{index}.tif', f'Stage {index}', stage=index) for index in range(12))
    widget = FilePreviewWidget((PreviewGroup(tmp_path, files),))
    widget.resize(900, 500)
    widget.show()
    app.processEvents()
    try:
        assert widget.view.transform().m11() >= 1
        arrows = [item for item in widget.scene.items() if isinstance(item, QGraphicsPathItem) and item.data(0) == 'workflow-order']
        assert len(arrows) == len(files) - 1
        assert all('does not assert a saved input relationship' in item.toolTip() for item in arrows)
        cards = {member.path: item for item in widget.scene.items() if isinstance(item, QGraphicsRectItem) for member in item.data(1).files}
        for item in files[:2]:
            app.processEvents()
            point = widget.view.mapFromScene(cards[item.path].sceneBoundingRect().center())
            QTest.mouseClick(widget.view.viewport(), Qt.MouseButton.LeftButton, pos=point)
            assert widget.details.stage is not None
            assert widget.details.stage.files == (item,)
            assert widget.details.isVisible()
        app.processEvents()
        bounds = cards[files[0].path].sceneBoundingRect()
        background = widget.view.mapFromScene(QPointF(bounds.right() + 30, bounds.top() + 10))
        assert widget.view.itemAt(background) is None
        QTest.mouseClick(widget.view.viewport(), Qt.MouseButton.LeftButton, pos=background)
        assert widget.details.stage is None
        assert widget.details.tree.topLevelItemCount() == 0
        assert not widget.details.isVisible()
    finally:
        widget.close()


def test_migration_checkbox_projects_the_actual_full_rebuild(tmp_path: Path) -> None:
    """
    Toggle reconstruction without writes and match its outputs to the post-migration plan.
    """

    app = _application()
    legacy_run(tmp_path, masks=True)
    plan = api.plan_migration(tmp_path)
    assert plan is not None
    before = {path: path.read_bytes() for path in tmp_path.rglob('*') if path.is_file()}
    projected: list[PreviewGroup] = []

    def inspect() -> None:
        """
        Exercise the real checkbox connection and verify reversible visual switching.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            preview = dialog.findChild(MigrationPreviewWidget)
            checkbox = dialog.findChild(QCheckBox)
            assert preview is not None and checkbox is not None
            assert not hasattr(preview.diagram, 'experiments')
            moves = preview.diagram._groups
            assert not checkbox.isChecked()
            checkbox.setChecked(True)
            assert 'rebuild the full workflow' in preview.diagram.guidance.text()
            projected.extend(preview.diagram._groups)
            assert any(item.path.name == cst.ARRAY_RAW and item.action == 'create' for item in projected[0].files)
            checkbox.setChecked(False)
            assert preview.diagram._groups == moves
        finally:
            dialog.accept()

    QTimer.singleShot(0, inspect)
    assert confirm_migration(plan) is False
    assert projected
    assert all(path.read_bytes() == data for path, data in before.items())
    assert set(before) == {path for path in tmp_path.rglob('*') if path.is_file()}
    api.migrate(plan)
    rebuild = api.plan_full_rebuild(tmp_path)
    assert rebuild is not None
    actual = processing_groups(rebuild)[0]
    operations = ('create', 'rebuild', 'remove')
    expected = {item.path: item.action for item in actual.files if item.action in operations}
    shown = {item.path: item.action for item in projected[0].files if item.action in operations}
    assert shown == expected
    assert projected[0].edges == actual.edges


def test_run_overview_counts_shared_originals_and_mixed_stage_renames(tmp_path: Path) -> None:
    """
    Count five acquisitions once across ten series and preserve partial rename actions.
    """
    _application()
    groups: list[PreviewGroup] = []
    for acquisition in range(5):
        folder = tmp_path / 'control' / f'image_{acquisition}'
        original = PreviewFile(folder / f'image_{acquisition}.nd2', 'Original', stage=0)
        for series in range(2):
            directory = folder / f'image_{acquisition}_s{series}'
            raw = PreviewFile(directory / cst.ARRAY_RAW, 'Converted', 'create', stage=1)
            changed = acquisition < 3
            background = PreviewFile(directory / cst.ARRAY_BGSUB, 'BgSubtracted',
                                     'rename' if changed else 'keep', stage=2,
                                     source=directory / cst.ARRAY_NAME if changed else None)
            groups.append(PreviewGroup(directory, (original, raw, background)))
    widget = FilePreviewWidget(tuple(groups))
    try:
        stages = {stage.title: stage for stage in widget.overview.stages}
        assert len(stages) == 3
        assert len(stages['Original'].files) == 5
        assert stages['Original'].action == 'keep'
        assert len(stages['Converted'].files) == 10
        assert stages['Converted'].action == 'create'
        background = stages['BgSubtracted']
        assert background.action == 'update'
        assert background.count_summary == '4 kept · 6 renamed'
        assert background.renames == ((cst.ARRAY_NAME, cst.ARRAY_BGSUB, 6),)
        card = next(item for item in widget.scene.items()
                    if isinstance(item, QGraphicsRectItem) and item.data(1).title == 'Original')
        labels = ' '.join(item.toPlainText() for item in card.childItems() if isinstance(item, QGraphicsTextItem))
        assert '.nd2' not in labels and '5 files' in labels
        background_card = next(item for item in widget.scene.items()
                               if isinstance(item, QGraphicsRectItem) and item.data(1).title == 'BgSubtracted')
        background_card.setSelected(True)
        tree = widget.details.tree
        assert tree.topLevelItemCount() == 5
        assert _row(tree, 0).childCount() == 2
        assert _row(tree, 0, 0, 0).text(1) == 'Will be renamed'
        assert _row(tree, 4, 0, 0).text(1) == 'Kept'
    finally:
        widget.close()


def test_run_overview_preserves_distinct_renames_and_independent_branches(tmp_path: Path) -> None:
    """
    Combine rename patterns without inventing links between unrelated experiment stages.
    """
    first, second = tmp_path / 'first', tmp_path / 'second'
    files = (PreviewFile(first / 'final.tif', 'Converted', 'rename', source=first / 'old.tif', stage=1),
             PreviewFile(second / 'final.tif', 'Converted', 'rename', source=second / 'older.tif', stage=1))
    extract = PreviewFile(first / 'measurements.parquet', 'Measurements', stage=9)
    distance = PreviewFile(second / 'distance.parquet', 'Distance', stage=9)
    overview = run_overview((PreviewGroup(first, (files[0], extract)), PreviewGroup(second, (files[1], distance))))
    stage = next(stage for stage in overview.stages if stage.title == 'Converted')
    assert stage.renames == (('old.tif', 'final.tif', 1), ('older.tif', 'final.tif', 1))
    assert len(overview.links) == 2
    assert all(link.source == stage.key for link in overview.links)


def test_rebuild_review_moves_and_resizes_independently() -> None:
    """
    Detach the review from its owner while retaining modal confirmation and resize controls.
    """
    app = _application()
    owner = QDialog()
    owner.resize(600, 400)
    owner.show()
    app.processEvents()
    original = owner.geometry()

    def inspect() -> None:
        """
        Move and resize the real review without moving or resizing its owner.
        """
        dialog = app.activeModalWidget()
        assert isinstance(dialog, QDialog)
        try:
            assert dialog.parentWidget() is None
            assert dialog.windowType() == Qt.WindowType.Window
            handle = dialog.windowHandle()
            assert handle is not None and handle.transientParent() is None
            assert dialog.windowFlags() & Qt.WindowType.WindowMaximizeButtonHint
            position = dialog.pos() + QPointF(35, 25).toPoint()
            dialog.move(position)
            width, height = dialog.width() + 80, dialog.height() + 40
            dialog.resize(width, height)
            app.processEvents()
            assert dialog.pos() == position
            assert (dialog.width(), dialog.height()) == (width, height)
            assert owner.geometry() == original
        finally:
            dialog.reject()

    try:
        QTimer.singleShot(0, inspect)
        assert not confirm_files('Review rebuilding', 'Rebuild selected results.', owner,
                                 preview=FilePreviewWidget(()))
    finally:
        owner.close()
