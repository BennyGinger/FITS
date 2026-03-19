from __future__ import annotations

from pathlib import Path

from fits.workflows.metadata_change import _collect_fits_files, change_labels, change_status


class DummyReader:
    def __init__(self, path: Path, seen: dict[str, list[tuple[Path, object]]]) -> None:
        self._path = path
        self._seen = seen

    def set_status(self, status: object) -> None:
        self._seen['status'].append((self._path, status))

    def set_channel_labels(self, labels: object) -> None:
        self._seen['labels'].append((self._path, labels))


def test_collect_fits_files_respects_recursive_flag(tmp_path: Path, touch) -> None:
    top_array = touch(tmp_path / 'exp' / 'fits_array.tif')
    nested_mask = touch(tmp_path / 'exp' / 'nested' / 'fits_mask.tif')

    non_recursive = _collect_fits_files(tmp_path / 'exp', recursive=False)
    recursive = _collect_fits_files(tmp_path / 'exp', recursive=True)

    assert sorted(non_recursive) == [top_array]
    assert sorted(recursive) == [top_array, nested_mask]


def test_change_status_updates_each_discovered_file(monkeypatch, tmp_path: Path, touch) -> None:
    files = [touch(tmp_path / 'fits_array.tif'), touch(tmp_path / 'fits_mask.tif')]
    seen: dict[str, list[tuple[Path, object]]] = {'status': [], 'labels': []}

    monkeypatch.setattr(
        'fits.workflows.metadata_change.FitsIO.from_path',
        lambda path: DummyReader(path, seen),
    )

    change_status(tmp_path, 'skip')

    assert sorted(seen['status']) == [(files[0], 'skip'), (files[1], 'skip')]


def test_change_labels_updates_each_discovered_file_recursively(monkeypatch, tmp_path: Path, touch) -> None:
    top_file = touch(tmp_path / 'exp1' / 'fits_array.tif')
    nested_file = touch(tmp_path / 'exp2' / 'nested' / 'fits_mask.tif')
    seen: dict[str, list[tuple[Path, object]]] = {'status': [], 'labels': []}

    monkeypatch.setattr(
        'fits.workflows.metadata_change.FitsIO.from_path',
        lambda path: DummyReader(path, seen),
    )

    change_labels([tmp_path / 'exp1', tmp_path / 'exp2'], ['GFP', 'RFP'], recursive=True)

    assert sorted(seen['labels']) == [
        (top_file, ['GFP', 'RFP']),
        (nested_file, ['GFP', 'RFP']),
    ]