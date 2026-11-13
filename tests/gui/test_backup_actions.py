"""Confirm the exact scope of bulk backup deletion."""

from pathlib import Path
from typing import Any, cast

from PySide6.QtWidgets import QApplication, QWidget
from pytest import MonkeyPatch

from fisch.gui.file_management.manager import _history_action, _history_panel
from fisch.workflows.file_management.history import Snapshot

_APP: QApplication | None = None


def test_delete_all_requires_confirmation_and_only_removes_listed_backups(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    """
    Delete the displayed scope regardless of row selection, only after confirmation.
    """
    global _APP
    _APP = cast(QApplication, QApplication.instance() or QApplication([]))
    entries = tuple(Snapshot(tmp_path / str(index), tmp_path, (tmp_path / str(index) / 'saved.tif',), ())
                    for index in range(2))
    group, history, notice = _history_panel(entries, tmp_path, lambda action: None)
    history.setCurrentRow(1)
    confirmations: list[tuple[str, str]] = []
    deleted: list[tuple[Snapshot, ...]] = []
    accepted = False

    def _confirm(title: str, text: str, parent: QWidget, action: str, **kwargs: Any) -> bool:
        """
        Record the explicit delete-all review and simulate the user's choice.
        """
        confirmations.append((text, action))
        return accepted

    monkeypatch.setattr('fisch.gui.file_management.manager.confirm_files', _confirm)
    monkeypatch.setattr('fisch.gui.file_management.manager.delete_history', lambda root, picked: deleted.append(tuple(picked)))
    monkeypatch.setattr('fisch.gui.file_management.manager.run_file_task', lambda task, parent: task())
    try:
        assert _history_action(tmp_path, group, notice, history, entries, 'delete_all') is None
        assert not deleted
        accepted = True
        apply = _history_action(tmp_path, group, notice, history, entries, 'delete_all')
        assert apply is not None
        apply()
        assert deleted == [entries]
        assert confirmations[-1][1] == 'Delete all listed backups'
        assert 'Delete all 2 backups shown in this list' in confirmations[-1][0]
        assert 'backups outside this list are preserved' in confirmations[-1][0]
    finally:
        group.close()
