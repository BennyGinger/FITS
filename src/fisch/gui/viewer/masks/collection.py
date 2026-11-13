"""Previewable mask collection UI. Pipeline scheduling is deliberately external."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PySide6.QtCore import QSignalBlocker, Qt, Signal, Slot
from PySide6.QtGui import QCloseEvent, QColor, QKeyEvent, QPalette
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QTreeWidget, QTreeWidgetItem, QStyle, QMessageBox, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from fisch.gui.viewer.masks.window import MaskDrawingWindow
from fisch.gui.viewer.masks.reference_panel import ReferenceMaskPanel
from fisch.gui.viewer.common.tuner_actions import (
    CLOSE_WINDOW_STYLE, RUN_PREVIEW_STYLE, configure_tuner_window)
from fisch.interaction.planes import PlaneState
from fisch.workflows.runtime.interactive.messages import (
    MaskCollectionOutcome, MaskCollectionRequest)
from fisch.settings.models import DistanceProfileSettings, ExtractSettings
from fisch.tasks.reference_mask import ReferenceMaskSession
from fisch.tasks.roi_mask import RoiSession


@dataclass
class _MaskSlot:
    """
    Keep one saved mask or an independent, unsaved drawing slot.
    """

    path: Path | None = None
    session: ReferenceMaskSession | RoiSession | None = None
    label: str = ""
    channel: str = ""
    dirty: bool = False
    baseline: dict[tuple[int, int, int], PlaneState] | None = None
    revisions: tuple[int, ...] = ()
    plane_revisions: dict[tuple[int, int, int], int] | None = None
    baseline_label: str = ""
    canvas_dirty: bool = False


class MaskCollectionWindow(MaskDrawingWindow):
    """One active experiment, an append-only waiting queue, and explicit outcomes."""

    source_panel_sizes = (213, 807)

    experiment_finalized = Signal(object)
    collection_finished = Signal()

    def __init__(self, parent: QWidget | None = None, *, preview: bool = False,
                 extraction: ExtractSettings | None = None,
                 profile: DistanceProfileSettings | None = None,
                 run_dir: Path | None = None,
                 ) -> None:
        """
        Initialize the experiment queue and independent mask drafts.
        """
        self.run_dir = Path(run_dir).resolve() if run_dir is not None else None
        self._preview = preview
        self._preview_extraction = extraction
        self._preview_profile = profile
        self._waiting: deque[MaskCollectionRequest] = deque()
        self._seen: set[Path] = set()
        self._requests: dict[Path, MaskCollectionRequest] = {}
        self._resolved: set[Path] = set()
        self._inspection: ReferenceMaskSession | RoiSession | None = None
        self._return_view: tuple[str, int, int, tuple[float, float], NDArray[np.uint8] | None] | None = None
        self._active: MaskCollectionRequest | None = None
        self._collapse_source: Path | None = None
        self._input_complete = False
        self._ended = False
        self._completed = 0
        self._expected_experiments: int | None = None
        self._baseline: dict[str, dict[tuple[int, int, int], PlaneState]] = {}
        self._baseline_labels: dict[str, str] = {}
        self._baseline_revisions: dict[str, tuple[int, ...]] = {}
        self._baseline_plane_revisions: dict[str, dict[tuple[int, int, int], int]] = {}
        self._label_suggestions = {"reference": "", "roi": ""}
        self._canvas_dirty: set[str] = set()
        self._saved: dict[str, set[Path]] = {"reference": set(), "roi": set()}
        self._skipped = {"reference": 0, "roi": 0}
        self._slots: dict[str, list[_MaskSlot]] = {"reference": [], "roi": []}
        self._selected_slots = {"reference": -1, "roi": -1}
        self._targets = {"reference": 0, "roi": 0}
        super().__init__(parent=parent)
        self.viewer_actions.setFixedWidth(400)
        self.setWindowTitle("FIScH Mask Collection" + (" — Preview" if preview else ""))
        configure_tuner_window(self, self.status_label)
        self.mask_saved.connect(self._saved_mask)
        self.image_viewer.drawing_started.connect(self._drawing_started)
        for kind in ("reference", "roi"):
            self._session_panel(kind)[1].label_edit.textChanged.connect(self._refresh_mask_lists)
        for signal in (self.roi_panel.automatic_current_requested,
                       self.roi_panel.automatic_stack_requested,
                       self.roi_panel.manual_stack_requested,
                       self.roi_panel.threshold_changed):
            signal.connect(self._record_edit_channel)
        self._refresh_collection()

    def _build_source_controls(self) -> QWidget:
        """
        Build the experiment queue above the mask settings.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        self.preview_note = QLabel(
            "Preview only — no pipeline is running.\nSaving writes masks to the selected experiment folder.")
        self.preview_note.setWordWrap(True)
        self.preview_note.setVisible(self._preview)
        layout.addWidget(self.preview_note)
        self.load_button = QPushButton("Load test experiments…")
        self.load_button.setVisible(self._preview)
        self.load_button.setToolTip("Preview only: load prepared experiments from a folder.")
        self.load_button.clicked.connect(self._load_test_experiments)
        layout.addWidget(self.load_button)
        self.experiment_label = QLabel()
        self.count_label = QLabel()
        layout.addWidget(self.experiment_label)
        layout.addWidget(self.count_label)
        self.experiment_tree = QTreeWidget()
        self.experiment_tree.setHeaderHidden(True)
        self.experiment_tree.setMinimumHeight(60)
        self.experiment_tree.setToolTip(
            "Expand an experiment to see its saved masks. Click a mask to open it. "
            "The highlighted folder is the current drawing experiment.")
        self.experiment_tree.itemClicked.connect(self._tree_mask_selected)
        self.experiment_tree.itemActivated.connect(self._tree_mask_selected)
        layout.addWidget(self.experiment_tree, 1)
        self.return_button = QPushButton("Return to current experiment")
        self.return_button.setToolTip("Return to your current drawing without changing the experiment queue.")
        self.return_button.clicked.connect(self._return_to_current)
        self.return_button.hide()
        layout.addWidget(self.return_button)
        self.next_button = QPushButton("Next experiment")
        self.next_button.setStyleSheet(RUN_PREVIEW_STYLE)
        self.next_button.clicked.connect(self._finish_experiment)
        self.next_button.setToolTip(
            "Open the next experiment. Missing masks and unsaved work in both tabs require confirmation.")
        self.close_button = QPushButton("Close window")
        self.close_button.setStyleSheet(CLOSE_WINDOW_STYLE)
        self.close_button.clicked.connect(self.close)
        self.close_button.setToolTip(
            "Close mask collection. Missing masks and unsaved work in both tabs require confirmation.")
        return panel

    def _connect_source_controls(self) -> None:
        """
        Leave experiment loading under the collection coordinator.
        """
        # The coordinator supplies images; no directory-browser signals here.
        pass

    def _build_tools(self) -> QWidget:
        """
        Keep each tab's mask list fixed below its scrollable settings.
        """
        tools = super()._build_tools()
        self.mask_lists: dict[str, QListWidget] = {}
        self.add_mask_buttons: dict[str, QPushButton] = {}
        for kind in ("reference", "roi"):
            panel = self._session_panel(kind)[1]
            header = QHBoxLayout()
            header.setContentsMargins(8, 12, 8, 4)
            header.addWidget(QLabel("REF masks" if kind == "reference" else "ROI masks"))
            header.addStretch(1)
            button = QPushButton("Add mask")
            button.setFixedWidth(120)
            button.setStyleSheet(
                "QPushButton { background-color: #4f8f5b; color: white; "
                "padding: 6px 12px; border-radius: 4px; } "
                "QPushButton:hover { background-color: #5ca568; } "
                "QPushButton:pressed { background-color: #3f7449; }")
            button.clicked.connect(lambda checked=False, k=kind: self._add_mask(k))
            self.add_mask_buttons[kind] = button
            header.addWidget(button)
            panel.outer_layout.addLayout(header)
            mask_list = QListWidget()
            mask_list.setMinimumHeight(180)
            mask_list.setMaximumHeight(300)
            mask_list.currentRowChanged.connect(lambda row, k=kind: self._select_mask_slot(k, row))
            panel.outer_layout.addWidget(mask_list, 1)
            panel.outer_layout.setStretchFactor(panel.controls_scroll, 3)
            self.mask_lists[kind] = mask_list
        return tools

    @Slot(object)
    def enqueue_experiment(self, request: MaskCollectionRequest) -> None:
        """Call on the GUI thread, or connect a worker's queued signal to this slot."""
        if self._ended or self._input_complete:
            raise RuntimeError("Mask collection is no longer accepting requests.")
        key = request.image_path
        if key in self._seen:
            return
        self._seen.add(key)
        self._requests[key] = request
        self._waiting.append(request)
        if self._active is None:
            self._activate_next()
        self._refresh_collection()

    @Slot()
    def no_more_requests(self) -> None:
        """
        Mark experiment preparation complete and finish an idle collection.
        """
        self._input_complete = True
        self._refresh_collection()
        self._complete_if_idle()

    @Slot(int)
    def set_expected_experiments(self, count: int) -> None:
        """
        Display the total number of experiments supplied by the pipeline.
        """
        self._expected_experiments = max(0, count)
        self._refresh_collection()

    def _activate_next(self) -> None:
        """
        Open the next experiment with its own saved masks and expected slots.
        """
        # Suggest names only; never carry drawing pixels to another experiment.
        if self._source_path is not None:
            for kind in ("reference", "roi"):
                paths = sorted(self._saved[kind])
                if paths:
                    prefix = "proc_ref_" if kind == "reference" else "proc_roi_"
                    labels = [path.stem.removeprefix(prefix) for path in paths]
                    current_label = self._session_panel(kind)[1].label_edit.text()
                    self._label_suggestions[kind] = (
                        current_label if kind == "roi" and current_label in labels else labels[0])
        # Remember the experiment we are leaving even when the live conveyor has
        # not supplied its successor yet.  The demo normally has a populated
        # queue, while a real pipeline can briefly leave the queue empty.
        if self._active is not None:
            self._collapse_source = self._active.image_path
        if not self._waiting:
            self._active = None
            self._close_session()
            return
        if self._inspection is not None:
            self._return_to_current()
        self._active = self._waiting.popleft()
        self._skipped = {"reference": 0, "roi": 0}
        self._targets = {"reference": self._active.expected_ref_masks,
                         "roi": self._active.expected_roi_masks}
        self._open_source(self._active.image_path)
        self.tool_tabs.setCurrentWidget(self.reference_panel)
        self._saved = {
            "reference": {p for p in self._active.image_path.parent.glob("proc_ref_*.tif") if p.is_file()},
            "roi": {p for p in self._active.image_path.parent.glob("proc_roi_*.tif") if p.is_file()}}
        self._canvas_dirty.clear()
        self._baseline.clear()
        self._baseline_labels.clear()
        for kind in ("reference", "roi"):
            session, panel = self._session_panel(kind)
            if session is not None and not panel.label_edit.text():
                panel.label_edit.setText(self._label_suggestions[kind])
            paths = sorted(self._saved[kind])
            self._slots[kind] = [self._loaded_slot(kind, path, session if index == 0 else None)
                                 for index, path in enumerate(paths)]
            self._slots[kind].extend(_MaskSlot() for _ in range(max(0, self._targets[kind] - len(paths))))
            self._targets[kind] = len(self._slots[kind])
            if self._slots[kind]:
                slot = self._slots[kind][0]
                slot.session = session
                slot.label = panel.label_edit.text()
                self._selected_slots[kind] = 0
            self._remember(kind)
        self._refresh_mask_lists()

    def _kind(self) -> str:
        """
        Return the mask type belonging to the active tab.
        """
        return "reference" if self._reference_tool_active() else "roi"

    def _session_panel(self, kind: str) -> tuple[ReferenceMaskSession | RoiSession | None, ReferenceMaskPanel]:
        """
        Return the session and controls belonging to one mask type.
        """
        return ((self._reference_session, self.reference_panel) if kind == "reference"
                else (self._roi_session, self.roi_panel))

    def _remember(self, kind: str) -> None:
        """
        Record the active draft baseline without copying whole stacks.
        """
        session, panel = self._session_panel(kind)
        if session is not None:
            self._baseline[kind] = {
                key: session._mask.snapshot_plane(key) for key in session._mask.keys()}
            self._baseline_revisions[kind] = tuple(session._mask.channel_revisions)
            self._baseline_plane_revisions[kind] = session._mask.plane_revisions.copy()
            self._baseline_labels[kind] = panel.label_edit.text()
        self._canvas_dirty.discard(kind)

    def _drawing_started(self) -> None:
        """
        Mark the selected drawing dirty and identify its channel.
        """
        self._canvas_dirty.add(self._kind())
        slot = self._current_slot(self._kind())
        if slot is not None:
            slot.channel = self.channel_combo.currentText()
        self._refresh_mask_lists()

    def _record_edit_channel(self, *_: object) -> None:
        """
        Associate an automatic or threshold edit with the current channel.
        """
        kind = self._kind()
        session, _panel = self._session_panel(kind)
        slot = self._current_slot(kind)
        if slot is not None and session is not None and not slot.channel:
            if tuple(session._mask.channel_revisions) != self._baseline_revisions.get(kind):
                slot.channel = self.channel_combo.currentText()
                self._refresh_mask_lists()

    def _dirty(self, kind: str) -> bool:
        """
        Check unsaved work in every draft belonging to a tab.
        """
        return self._current_dirty(kind) or any(
            slot.dirty for index, slot in enumerate(self._slots[kind])
            if index != self._selected_slots[kind])

    def _current_dirty(self, kind: str) -> bool:
        """
        Compare the selected draft with its last saved or loaded baseline.
        """
        session, panel = self._session_panel(kind)
        if session is None:
            return False
        baseline = self._baseline.get(kind)
        if (kind in self._canvas_dirty or baseline is None
                or panel.label_edit.text() != self._baseline_labels.get(kind, "")):
            return True
        if tuple(session._mask.channel_revisions) == self._baseline_revisions.get(kind):
            return False
        remembered = self._baseline_plane_revisions[kind]
        for key, revision in session._mask.plane_revisions.items():
            if revision != remembered.get(key, 0):
                if not np.array_equal(session._mask.plane(*key),
                                      session._mask.read_snapshot(key, baseline[key])):
                    return True
        return False

    def _confirm(self, title: str, message: str) -> bool:
        """
        Ask for confirmation before skipping or discarding mask work.
        """
        return QMessageBox.warning(self, title, message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Ok

    def _discard(self, kind: str) -> None:
        """
        Reload the selected draft after an explicit discard decision.
        """
        assert self._source_path is not None
        if kind == "reference":
            self._reference_session = ReferenceMaskSession(self._source_path, reference_path=self._reference_path)
            self._image_session = self._reference_session
            self.reference_panel.label_edit.setText(self._reference_session.reference_label or "")
        else:
            self._roi_session = RoiSession(self._source_path, roi_path=self._roi_path)
            self.roi_panel.label_edit.setText(self._roi_session.roi_label or "")
        self._remember(kind)
        self._display_selection()

    def switch_mode(self, kind: str) -> None:
        """
        Select a mask tab while retaining the other tab's work.
        """
        if kind not in ("reference", "roi"):
            raise ValueError(f"Unknown drawing mode: {kind}")
        if self._active is None or self._ended or kind == self._kind():
            return
        self.tool_tabs.setCurrentWidget(self._session_panel(kind)[1])
        self._refresh_collection()

    def _saved_mask(self, kind: str, path: Path) -> None:
        """
        Record the saved channel while preserving other unsaved channels.
        """
        self._saved[kind].add(path)
        if kind == "reference":
            self._reference_path = path
        else:
            self._roi_path = path
        # A save writes only the selected channel. Other channels may still be unsaved.
        session, panel = self._session_panel(kind)
        if session is None:
            return
        channel = session.channel_labels.index(self.channel_combo.currentText())
        baseline = self._baseline[kind]
        remembered = self._baseline_plane_revisions[kind]
        for key, revision in session._mask.plane_revisions.items():
            if key[1] == channel and revision != remembered.get(key, 0):
                baseline[key] = session._mask.snapshot_plane(key)
                remembered[key] = revision
        revisions = list(self._baseline_revisions[kind])
        revisions[channel] = session._mask.channel_revisions[channel]
        self._baseline_revisions[kind] = tuple(revisions)
        self._baseline_labels[kind] = panel.label_edit.text()
        self._canvas_dirty.discard(kind)
        slot = self._current_slot(kind)
        if slot is not None:
            self._reconcile_saved_slots(kind, slot, path)
            slot.path = path
            slot.label = panel.label_edit.text()
            slot.channel = self.channel_combo.currentText()
            slot.dirty = False
        self._refresh_collection()

    def _reconcile_saved_slots(self, kind: str, selected: _MaskSlot, path: Path) -> None:
        """
        Keep every saved file represented when saving under a different label.
        """
        if selected.path is not None and selected.path != path:
            self._slots[kind].append(self._loaded_slot(kind, selected.path))
        for index, slot in enumerate(self._slots[kind]):
            if slot is not selected and slot.path == path:
                if slot.dirty:
                    slot.path = None
                else:
                    if slot.session is not None:
                        slot.session.close()
                    self._slots[kind][index] = _MaskSlot()
        self._targets[kind] = len(self._slots[kind])

    def _loaded_slot(self, kind: str, path: Path, session: ReferenceMaskSession | RoiSession | None = None) -> _MaskSlot:
        """
        Create a list entry from a saved file and its channel metadata.
        """
        assert self._source_path is not None
        if session is None:
            session = (ReferenceMaskSession(self._source_path, reference_path=path) if kind == "reference"
                       else RoiSession(self._source_path, roi_path=path))
        label = (session.reference_label if isinstance(session, ReferenceMaskSession) else session.roi_label) or ""
        return _MaskSlot(path=path, session=session, label=label, channel=", ".join(session.loaded_channels))

    def _current_slot(self, kind: str) -> _MaskSlot | None:
        """
        Return the selected mask slot, if this tab has any slots.
        """
        index = self._selected_slots[kind]
        return self._slots[kind][index] if 0 <= index < len(self._slots[kind]) else None

    def _stash_slot(self, kind: str) -> None:
        """
        Preserve the selected draft before opening another slot.
        """
        slot = self._current_slot(kind)
        if slot is not None:
            session, panel = self._session_panel(kind)
            slot.dirty = self._current_dirty(kind)
            slot.session = session
            slot.label = panel.label_edit.text()
            slot.baseline = self._baseline.get(kind)
            slot.revisions = self._baseline_revisions.get(kind, ())
            slot.plane_revisions = self._baseline_plane_revisions.get(kind)
            slot.baseline_label = self._baseline_labels.get(kind, "")
            slot.canvas_dirty = kind in self._canvas_dirty

    def _select_mask_slot(self, kind: str, index: int) -> None:
        """
        Open a slot while retaining every other slot's unsaved work.
        """
        if index < 0 or index == self._selected_slots[kind] or self._source_path is None:
            return
        self._stop_mask_preview()
        self._stash_slot(kind)
        slot = self._slots[kind][index]
        if slot.session is None:
            if self._selected_slots[kind] < 0:
                previous = self._session_panel(kind)[0]
                if previous is not None:
                    previous.close()
            slot.session = (ReferenceMaskSession(self._source_path, reference_path=slot.path)
                            if kind == "reference" else RoiSession(self._source_path, roi_path=slot.path))
            slot.label = ((slot.session.reference_label if isinstance(slot.session, ReferenceMaskSession)
                           else slot.session.roi_label) or "")
            slot.channel = slot.session.loaded_channels[0] if slot.session.loaded_channels else ""
        self._selected_slots[kind] = index
        panel = self._session_panel(kind)[1]
        if kind == "reference":
            assert isinstance(slot.session, ReferenceMaskSession)
            self._reference_session = slot.session
            self._reference_path = slot.path
            self._image_session = slot.session
        else:
            assert isinstance(slot.session, RoiSession)
            self._roi_session = slot.session
            self._roi_path = slot.path
        panel.label_edit.setText(slot.label)
        if slot.baseline is None:
            self._remember(kind)
        else:
            self._baseline[kind] = slot.baseline
            self._baseline_revisions[kind] = slot.revisions
            self._baseline_plane_revisions[kind] = slot.plane_revisions or {}
            self._baseline_labels[kind] = slot.baseline_label
            self._canvas_dirty.discard(kind)
            if slot.canvas_dirty:
                self._canvas_dirty.add(kind)
        if slot.channel:
            self.channel_combo.setCurrentText(slot.channel)
        self._display_selection()
        self._refresh_collection()

    def _add_mask(self, kind: str) -> None:
        """
        Increase the expected count and start an independent empty mask.
        """
        if self._active is None or self._ended or self._inspection is not None:
            return
        self._slots[kind].append(_MaskSlot())
        self._targets[kind] = len(self._slots[kind])
        self._select_mask_slot(kind, len(self._slots[kind]) - 1)

    def _delete_mask(self, kind: str, index: int) -> None:
        """
        Remove a slot and permanently delete its saved file after confirmation.
        """
        slot = self._slots[kind][index]
        if slot.path is not None:
            if not self._confirm("Delete saved mask?",
                                 f"Permanently delete {slot.path.name} from disk? This cannot be undone."):
                return
            self._stop_mask_preview()
            try:
                slot.path.unlink()
            except OSError as error:
                self.status_label.setText(f"Could not delete {slot.path.name}: {error}")
                return
            self._saved[kind].discard(slot.path)
        elif slot.channel and (slot.dirty or (index == self._selected_slots[kind] and self._current_dirty(kind))):
            if not self._confirm("Delete unsaved mask?", "Discard the unsaved drawing in this slot?"):
                return
        selected = self._selected_slots[kind]
        self._stop_mask_preview()
        if selected != index:
            self._stash_slot(kind)
        self._slots[kind].pop(index)
        if slot.session is not None:
            slot.session.close()
        self._targets[kind] = len(self._slots[kind])
        if selected == index:
            self._selected_slots[kind] = -1
            if self._slots[kind]:
                self._select_mask_slot(kind, min(index, len(self._slots[kind]) - 1))
            else:
                if kind == "reference":
                    self._reference_path = None
                else:
                    self._roi_path = None
                self._discard(kind)
        elif selected > index:
            self._selected_slots[kind] -= 1
        self._refresh_collection()

    def _refresh_mask_lists(self) -> None:
        """
        Display saved masks and numbered expected slots with deletion controls.
        """
        for kind, mask_list in self.mask_lists.items():
            with QSignalBlocker(mask_list):
                mask_list.clear()
                for index, slot in enumerate(self._slots[kind]):
                    label = (self._session_panel(kind)[1].label_edit.text()
                             if index == self._selected_slots[kind] else slot.label)
                    text = (f"{slot.channel} – {label or 'unlabelled'}" if slot.channel
                            else f"Expected mask – {index + 1}")
                    row = QWidget()
                    row_layout = QHBoxLayout(row)
                    row_layout.setContentsMargins(4, 0, 4, 0)
                    select = QPushButton(text)
                    select.setCheckable(True)
                    select.setChecked(index == self._selected_slots[kind])
                    select.clicked.connect(lambda checked=False, k=kind, i=index: self.mask_lists[k].setCurrentRow(i))
                    row_layout.addWidget(select, 1)
                    delete = QPushButton("🗑")
                    delete.setFixedWidth(28)
                    delete.setToolTip("Permanently delete saved mask" if slot.path else "Remove expected mask")
                    delete.clicked.connect(lambda checked=False, k=kind, i=index: self._delete_mask(k, i))
                    row_layout.addWidget(delete)
                    item = QListWidgetItem()
                    item.setSizeHint(row.sizeHint())
                    item.setData(Qt.ItemDataRole.UserRole, slot.path)
                    mask_list.addItem(item)
                    mask_list.setItemWidget(item, row)
                mask_list.setCurrentRow(self._selected_slots[kind])

    def _new_mask(self) -> None:
        """
        Add a mask to the active tab.
        """
        self._add_mask(self._kind())

    def _build_viewer_actions(self, layout: QHBoxLayout) -> None:
        """
        Stack the saving row, next experiment, and close actions below the image.
        """
        actions = QVBoxLayout()
        self.saving_stack = QStackedWidget()
        for panel in (self.reference_panel, self.roi_panel):
            panel.outer_layout.removeWidget(panel.saving_section)
            panel.label_edit.setMinimumWidth(120)
            panel.label_edit.setMaximumWidth(16777215)
            panel.save_row.setStretch(1, 1)
            panel.save_row.setStretch(2, 0)
            self.saving_stack.addWidget(panel.saving_section)
        actions.addWidget(self.saving_stack)
        actions.addWidget(self.next_button)
        actions.addWidget(self.close_button)
        layout.addLayout(actions, 1)

    def _confirm_leaving(self, *, closing: bool) -> bool:
        """
        Confirm missing masks and unsaved edits together in one dialog.
        """
        notes: list[str] = []
        if self._active is not None:
            for kind in ("reference", "roi"):
                remaining = max(0, self._targets[kind] - len(self._saved[kind]) - self._skipped[kind])
                if remaining:
                    notes.append(f"{remaining} expected {kind} mask(s) remain. They will be skipped.")
        if closing and self._waiting and not self._all_expected_done():
            notes.append("Remaining queued mask requests will be skipped.")
        if any(self._dirty(kind) for kind in ("reference", "roi")):
            notes.append("Your unsaved changes will be lost.")
        if not notes:
            return True
        notes.append("Cancel returns to drawing. OK continues without saving.")
        return self._confirm("Close mask collection?" if closing else "Next experiment?", "\n\n".join(notes))

    def _outcome(self, request: MaskCollectionRequest,
                 saved: dict[str, set[Path]],
                 skipped: dict[str, int],
                 ) -> MaskCollectionOutcome:
        """
        Report saved files and explicitly skipped mask slots.
        """
        return MaskCollectionOutcome(request, tuple(sorted(saved["reference"])),
                                     tuple(sorted(saved["roi"])), skipped["reference"], skipped["roi"])

    def _finish_experiment(self) -> bool:
        """
        Finalize both mask tabs and activate the next prepared experiment.
        """
        if self._active is None:
            return True
        # During a live conveyor, keep the current experiment open until its
        # successor is ready.  Only the final experiment may finish with an
        # empty queue, after preparation has explicitly completed.
        if not self._waiting and not (self._input_complete or self._preview):
            return False
        kinds = ("reference", "roi")
        if not self._confirm_leaving(closing=False):
            return False
        for kind in kinds:
            self._skipped[kind] = max(self._skipped[kind], self._targets[kind] - len(self._saved[kind]))
        self.experiment_finalized.emit(self._outcome(self._active, self._saved, self._skipped))
        self._resolved.add(self._active.image_path)
        self._completed += 1
        self._activate_next()
        self._refresh_collection()
        self._complete_if_idle()
        return True

    def _complete_if_idle(self) -> None:
        """
        Close normally after the final experiment is resolved.
        """
        if (not self._ended and self._requests and self._active is None
                and not self._waiting and (self._input_complete or self._preview)):
            self._ended = True
            self.collection_finished.emit()
            self.close()

    def _all_expected_done(self) -> bool:
        """
        Check both tabs and queued experiments for unfinished mask work.
        """
        if not (self._input_complete or self._preview):
            return False
        if any(self._dirty(kind) for kind in ("reference", "roi")):
            return False
        for request in ([self._active] if self._active else []) + list(self._waiting):
            if request == self._active:
                refs, rois = len(self._saved["reference"]), len(self._saved["roi"])
                ref_target, roi_target = self._targets["reference"], self._targets["roi"]
            else:
                folder = request.image_path.parent
                refs = sum(p.is_file() for p in folder.glob("proc_ref_*.tif"))
                rois = sum(p.is_file() for p in folder.glob("proc_roi_*.tif"))
                ref_target, roi_target = request.expected_ref_masks, request.expected_roi_masks
            if refs < ref_target or rois < roi_target:
                return False
        return True

    def _experiment_name(self, request: MaskCollectionRequest) -> str:
        """
        Display the experiment path relative to its run directory.
        """
        if self.run_dir is not None:
            try:
                relative = request.image_path.parent.relative_to(self.run_dir)
                return relative.as_posix() if relative.parts else self.run_dir.name
            except ValueError:
                return request.image_path.parent.name
        return request.experiment_id

    def _finish_drawing(self, *, close_window: bool = True) -> bool:
        """
        Finalize mask outcomes after confirmation, leaving pipeline decisions external.
        """
        if not self._confirm_leaving(closing=True):
            return False
        if self._active:
            for kind in ("reference", "roi"):
                self._skipped[kind] = max(self._skipped[kind], self._targets[kind] - len(self._saved[kind]))
            self.experiment_finalized.emit(self._outcome(self._active, self._saved, self._skipped))
        # Preserve existing artifacts for unvisited experiments; skip only unmet targets.
        for request in self._waiting:
            folder = request.image_path.parent
            references = tuple(sorted(p for p in folder.glob("proc_ref_*.tif") if p.is_file()))
            rois = tuple(sorted(p for p in folder.glob("proc_roi_*.tif") if p.is_file()))
            self.experiment_finalized.emit(MaskCollectionOutcome(
                request, references, rois,
                max(0, request.expected_ref_masks - len(references)),
                max(0, request.expected_roi_masks - len(rois))))
        self._resolved.update(self._requests)
        self._waiting.clear()
        self._active = None
        self._ended = True
        self._close_session()
        self.collection_finished.emit()
        self._refresh_collection()
        if close_window:
            self.close()
        return True

    def _refresh_experiment_tree(self) -> None:
        """
        Show received experiments and their saved mask files.
        """
        tree = self.experiment_tree
        expanded = set()
        selected = tree.currentItem().data(0, Qt.ItemDataRole.UserRole) if tree.currentItem() else None
        for index in range(tree.topLevelItemCount()):
            item = tree.topLevelItem(index)
            if item is None:
                continue
            key = item.data(0, Qt.ItemDataRole.UserRole)[0]
            if item.isExpanded():
                expanded.add(key)
        expanded.discard(self._collapse_source)
        self._collapse_source = None
        tree.clear()
        folder_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        mask_icon = self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        for source, request in self._requests.items():
            current = self._active is not None and source == self._active.image_path
            status = "current" if current else "finished" if source in self._resolved else "waiting"
            parent = QTreeWidgetItem(tree, [f"{self._experiment_name(request)} — {status}"])
            parent.setData(0, Qt.ItemDataRole.UserRole, (source, None))
            parent.setIcon(0, folder_icon)
            parent.setToolTip(0, self._experiment_name(request))
            if current:
                font = parent.font(0)
                font.setBold(True)
                parent.setFont(0, font)
                colour = QColor(self.palette().highlight().color())
                colour.setAlpha(85)
                parent.setBackground(0, colour)
            for pattern in ("proc_ref_*.tif", "proc_roi_*.tif"):
                for path in sorted(source.parent.glob(pattern)):
                    if not path.is_file():
                        continue
                    item = QTreeWidgetItem(parent, [path.name])
                    item.setIcon(0, mask_icon)
                    item.setData(0, Qt.ItemDataRole.UserRole, (source, path))
                    item.setToolTip(0, "Open this mask for editing." if current else
                                    "View this saved mask without changing the current drawing experiment.")
                    if selected == (source, path):
                        tree.setCurrentItem(item)
            parent.setExpanded(source in expanded or current)

    def _tree_mask_selected(self, item: QTreeWidgetItem, column: int = 0) -> None:
        """
        Edit a current mask or inspect another experiment's saved file.
        """
        source, path = item.data(0, Qt.ItemDataRole.UserRole)
        if path is None:
            return
        kind = "reference" if path.name.startswith("proc_ref_") else "roi"
        try:
            candidate = (ReferenceMaskSession(source, reference_path=path) if kind == "reference"
                         else RoiSession(source, roi_path=path))
        except Exception as error:
            self.status_label.setText(f"Could not open {path.name}: {error}")
            return
        current = self._active is not None and source == self._active.image_path and not self._ended
        if not current:
            self._inspect_mask(candidate, path)
            return
        if self._inspection is not None:
            self._return_to_current()
        self.switch_mode(kind)
        for index, slot in enumerate(self._slots[kind]):
            if slot.path == path:
                self._select_mask_slot(kind, index)
                break
        self.status_label.setText(f"Loaded {path.name} for editing.")

    def _inspect_mask(self, session: ReferenceMaskSession | RoiSession, path: Path) -> None:
        """
        View another experiment without replacing the current drafts.
        """
        if self._inspection is None:
            self._return_view = (
                self.channel_combo.currentText(), self.frame_slider.value(), self.z_slider.value(),
                self.image_viewer.display_levels, self.image_viewer.drawing_mask.copy()
                if self._source_path is not None else None)
        self._inspection = session
        self._inspection_path = path
        blockers = [QSignalBlocker(widget) for widget in (self.channel_combo, self.frame_slider, self.z_slider)]
        self.channel_combo.clear()
        self.channel_combo.addItems(session.channel_labels)
        self.channel_combo.setCurrentText(session.loaded_channels[0])
        self.frame_slider.setRange(0, session.frame_count - 1)
        self.z_slider.setRange(0, session.plane_count - 1)
        self.frame_slider.setValue(0)
        self.z_slider.setValue(0)
        del blockers
        self.tool_panel.setEnabled(False)
        for widget in (self.channel_combo, self.frame_slider, self.z_slider):
            widget.setEnabled(True)
        self._display_selection()
        self.image_viewer.auto_scale()
        self.status_label.setText("Viewing a saved mask. Your current drawing is kept until you return.")
        self._refresh_collection()

    def _return_to_current(self) -> None:
        """
        Restore the current experiment after inspecting another saved mask.
        """
        if self._inspection is None or self._return_view is None:
            return
        self._inspection = None
        channel, frame, z, levels, canvas = self._return_view
        self._return_view = None
        blockers = [QSignalBlocker(widget) for widget in (self.channel_combo, self.frame_slider, self.z_slider)]
        self.channel_combo.clear()
        session = self._image_session
        if session is not None:
            self.channel_combo.addItems(session.channel_labels)
            self.channel_combo.setCurrentText(channel)
            self.frame_slider.setRange(0, session.frame_count - 1)
            self.z_slider.setRange(0, session.plane_count - 1)
            self.frame_slider.setValue(frame)
            self.z_slider.setValue(z)
        del blockers
        self._set_source_controls_enabled(session is not None and not self._ended)
        if session is not None:
            self._display_selection()
            self.image_viewer.set_display_levels(levels)
            if canvas is not None:
                self.image_viewer.set_drawing_mask(canvas)
            self.status_label.setText("Returned to the current experiment.")
        else:
            self.image_viewer.image_item.clear()
            self.image_viewer.pixel_readout.set_planes(())
            self.image_viewer.clear_mask()
        self._refresh_collection()

    def _display_selection(self) -> None:
        """
        Display the active drawing or the read-only inspection plane.
        """
        session = self._inspection
        if session is None:
            super()._display_selection()
            self._update_drawing_options()
            return
        if self.channel_combo.currentIndex() < 0:
            return
        frame, channel, z = self.frame_slider.value(), self.channel_combo.currentText(), self.z_slider.value()
        self.image_viewer.set_channel_lut(channel)
        self.image_viewer.set_image(session.display_frame(frame, channel, z))
        mask = (session.display_mask_plane(frame, channel, z) if isinstance(session, RoiSession)
                else session.mask_plane(frame, channel, z))
        self.image_viewer.set_drawing_mask(mask)
        self.image_viewer.set_drawing_enabled(False)
        self.image_viewer.set_mask_visible(self.show_mask.isChecked())
        self.image_viewer.set_mask_opacity(self.mask_opacity.value() / 100.0)
        self.frame_value.setText(f"{frame + 1} / {session.frame_count}")
        self.z_value.setText(f"{z + 1} / {session.plane_count}")

    def _tool_keypress(self, event: QKeyEvent) -> bool:
        """
        Prevent editing shortcuts while inspecting another experiment.
        """
        if self._inspection is not None or self._current_slot(self._kind()) is None:
            return event.key() == Qt.Key.Key_S or bool(
                event.key() == Qt.Key.Key_D and event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        return super()._tool_keypress(event)

    def _undo(self) -> None:
        """
        Undo only when the current tab has an editable mask slot.
        """
        if self._inspection is None and self._current_slot(self._kind()) is not None:
            super()._undo()

    def _close_session(self) -> None:
        """
        Release all active and parked mask drafts when leaving an experiment.
        """
        if self._inspection is not None:
            self._inspection.close()
        self._inspection = None
        self._return_view = None
        self._stop_mask_preview()
        for slots in self._slots.values():
            for slot in slots:
                if slot.session is not None and slot.session not in (self._reference_session, self._roi_session):
                    slot.session.close()
        self._slots = {"reference": [], "roi": []}
        self._selected_slots = {"reference": -1, "roi": -1}
        super()._close_session()

    def _guide_page(self) -> str:
        """
        Open the collection workflow guide, with links to each drawing tool.
        """
        return "tools/mask_collection.md"

    def _build_mode_controls(self, layout: QHBoxLayout) -> None:
        """
        Show the active mask type above the image, matching SegTune.
        """
        self.mode_label = QLabel()
        layout.addWidget(self.mode_label, 0, Qt.AlignmentFlag.AlignCenter)

    def _apply_mode_appearance(self) -> None:
        """
        Retain the REF and ROI colours with SegTune-style tab navigation.
        """
        roi = isinstance(self._inspection, RoiSession) if self._inspection else self._kind() == "roi"
        background, accent, badge = (("#182e27", "#82d5b1", "#254c3c") if roi
                                     else ("#172635", "#80b9f2", "#243e58"))
        central = self.centralWidget()
        assert central is not None
        palette = central.palette()
        if palette.color(QPalette.ColorRole.Window) != QColor(background):
            palette.setColor(QPalette.ColorRole.Window, QColor(background))
            central.setPalette(palette)
            central.setAutoFillBackground(True)
            # Palette changes can clear the graphics viewport without repainting its scene.
            viewport = self.image_viewer.canvas.viewport()
            assert viewport is not None
            viewport.update()
        self.mode_label.setText(("ROI" if roi else "REFERENCE") +
                               (" — read-only" if self._inspection else ""))
        self.mode_label.setStyleSheet(
            f"background: {badge}; color: {accent}; border-left: 5px solid {accent}; "
            "padding: 4px 8px; font-weight: bold; font-size: 14px;")

    def _tool_changed(self, _: int) -> None:
        """
        Switch tabs without discarding either tab's draft.
        """
        super()._tool_changed(_)
        if hasattr(self, "saving_stack"):
            self._refresh_collection()

    def _update_drawing_options(self) -> None:
        """
        Allow drawing only when the current tab has a mask slot.
        """
        super()._update_drawing_options()
        if self._current_slot(self._kind()) is None:
            self.image_viewer.set_drawing_enabled(False)

    def _refresh_collection(self) -> None:
        """
        Update queue status, mask slots and action availability.
        """
        if not hasattr(self, "experiment_label"):
            return
        active = self._active is not None and self._source_path is not None and not self._ended
        if self._ended:
            title = "Drawing session finished."
        elif self._active:
            position = str(self._completed + 1)
            if self._expected_experiments is not None:
                position += f" of {self._expected_experiments}"
            title = f"Experiment {position}: {self._experiment_name(self._active)}"
        else:
            title = "All experiments finished." if self._input_complete else "Waiting for an experiment…"
        self.experiment_label.setText(title)
        self._refresh_experiment_tree()
        self.count_label.setText(f"{len(self._waiting)} experiment(s) waiting")
        editable = active and self._inspection is None
        kind = self._kind()
        self._apply_mode_appearance()
        self.saving_stack.setCurrentIndex(0 if kind == "reference" else 1)
        self.saving_stack.setEnabled(editable and self._current_slot(kind) is not None)
        for mask_kind in ("reference", "roi"):
            self.add_mask_buttons[mask_kind].setEnabled(editable)
            self.mask_lists[mask_kind].setEnabled(editable)
            controls = self._session_panel(mask_kind)[1].controls_scroll.widget()
            assert controls is not None
            controls.setEnabled(editable and self._current_slot(mask_kind) is not None)
        self._refresh_mask_lists()
        self._update_drawing_options()
        self.return_button.setText("Return to current experiment" if self._active else "Return to collection")
        self.return_button.setVisible(self._inspection is not None)
        self.next_button.setEnabled(
            editable and (bool(self._waiting) or self._input_complete or self._preview))
        self.load_button.setEnabled(not self._ended and not self._input_complete)

    def load_test_experiments(self, directory: Path) -> None:
        """
        Queue prepared images from a preview folder.
        """
        if self.run_dir is None:
            self.run_dir = directory.resolve()
        for source in sorted(directory.rglob("proc_array.tif")):
            if source.is_file():
                self.enqueue_experiment(MaskCollectionRequest.from_settings(
                    source, extraction=self._preview_extraction, profile=self._preview_profile))

    def _load_test_experiments(self) -> None:
        """
        Choose a folder for the standalone collection preview.
        """
        directory = QFileDialog.getExistingDirectory(self, "Choose test experiments")
        if directory:
            self.load_test_experiments(Path(directory))

    def closeEvent(self, event: QCloseEvent) -> None:
        """
        Close mask collection without requesting pipeline cancellation.
        """
        if not self._ended:
            if self._inspection is not None:
                self._return_to_current()
            if not self._finish_drawing(close_window=False):
                event.ignore()
                return
        super().closeEvent(event)
