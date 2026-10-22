"""Windows visibility changes must be harmless on Linux and restricted shares."""

import importlib.util
from pathlib import Path
import stat
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fits.environment import hidden, paths


def test_linux_never_inspects_or_changes_attributes(monkeypatch):
    monkeypatch.setattr(hidden.sys, "platform", "linux")
    entry = Mock(spec=Path)
    assert hidden.hide_on_windows(entry)
    entry.stat.assert_not_called()


@pytest.mark.parametrize("attributes", [stat.FILE_ATTRIBUTE_DIRECTORY, stat.FILE_ATTRIBUTE_ARCHIVE | stat.FILE_ATTRIBUTE_READONLY])
def test_windows_retains_original_attributes(monkeypatch, attributes):
    monkeypatch.setattr(hidden.sys, "platform", "win32")
    entry = Mock(spec=Path)
    entry.stat.return_value = SimpleNamespace(st_file_attributes=attributes)
    setter = Mock()
    monkeypatch.setattr(hidden, "_set_hidden_attribute", setter)
    assert hidden.hide_on_windows(entry)
    setter.assert_called_once_with(entry, attributes)


def test_windows_already_hidden_is_not_rewritten(monkeypatch):
    monkeypatch.setattr(hidden.sys, "platform", "win32")
    entry = Mock(spec=Path)
    entry.stat.return_value = SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_HIDDEN)
    setter = Mock()
    monkeypatch.setattr(hidden, "_set_hidden_attribute", setter)
    assert hidden.hide_on_windows(entry)
    setter.assert_not_called()


def test_windows_attribute_denial_does_not_raise(monkeypatch):
    monkeypatch.setattr(hidden.sys, "platform", "win32")
    entry = Mock(spec=Path)
    entry.stat.return_value = SimpleNamespace(st_file_attributes=stat.FILE_ATTRIBUTE_DIRECTORY)
    monkeypatch.setattr(hidden, "_set_hidden_attribute", Mock(side_effect=PermissionError("share denies attributes")))
    assert not hidden.hide_on_windows(entry)
    entry.stat.side_effect = FileNotFoundError()
    assert not hidden.hide_on_windows(entry)


def test_creation_hides_metadata_root_only_and_lookup_does_not_create(tmp_path, monkeypatch):
    hidden_paths = []
    monkeypatch.setattr(paths, "hide_on_windows", lambda path: hidden_paths.append(path))
    metadata = paths.fits_dir(tmp_path)
    assert not metadata.exists()
    target = metadata / "viewer_cache" / "tracking_paths"
    paths.ensure_fits_directory(target)
    assert target.is_dir()
    assert hidden_paths == [metadata, metadata]
    paths.ensure_fits_directory(tmp_path / "ordinary logs")
    assert hidden_paths == [metadata, metadata]


def test_installer_hides_only_internal_entries_and_tolerates_failure(tmp_path, monkeypatch, capsys):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "startup"))
    source = Path(__file__).resolve().parents[1] / "startup" / "verify.py"
    spec = importlib.util.spec_from_file_location("fits_install_verify", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    (tmp_path / ".gitignore").touch()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "uv.lock").touch()
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "README.md").touch()
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / ".leave-alone").touch()
    hidden_paths = []
    monkeypatch.setattr(module.sys, "platform", "win32")
    monkeypatch.setattr(hidden, "hide_on_windows", lambda path: hidden_paths.append(path) or False)
    module.hide_checkout_internal_entries(tmp_path)
    assert set(hidden_paths) == {
        tmp_path / ".gitignore", tmp_path / ".venv",
    }
    assert "installation will continue" in capsys.readouterr().out
    hidden_paths.clear()
    monkeypatch.setattr(module.sys, "platform", "linux")
    module.hide_checkout_internal_entries(tmp_path)
    assert not hidden_paths


@pytest.mark.parametrize("filename, expected", [
    ("C:\\data\\.fits", "\\\\?\\C:\\data\\.fits"),
    ("\\\\server\\share\\.fits", "\\\\?\\UNC\\server\\share\\.fits"),
])
def test_native_call_sets_hidden_without_replacing_other_flags(monkeypatch, filename, expected):
    setter = Mock(return_value=1)
    kernel = SimpleNamespace(SetFileAttributesW=setter)
    monkeypatch.setattr(hidden.ctypes, "WinDLL", Mock(return_value=kernel), raising=False)
    entry = Mock(spec=Path)
    entry.absolute.return_value = filename
    hidden._set_hidden_attribute(entry, stat.FILE_ATTRIBUTE_NORMAL | stat.FILE_ATTRIBUTE_READONLY)
    setter.assert_called_once_with(expected, stat.FILE_ATTRIBUTE_READONLY | stat.FILE_ATTRIBUTE_HIDDEN)
