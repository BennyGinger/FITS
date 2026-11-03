"""Verify optional viewer installation without network access or system changes."""

from __future__ import annotations

import importlib
import io
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture
def tad(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """
    Import the standalone installer module without loading the FITS GUI.
    """
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[2] / 'startup'))
    return importlib.import_module('fits.external_tools.tad')


def test_existing_tad_is_reused(tad: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Reinstalling FITS neither prompts nor downloads when Tad is present.
    """
    monkeypatch.setattr(tad, 'find_tad', lambda root: tmp_path / 'Tad')
    monkeypatch.setattr('builtins.input', lambda prompt: pytest.fail('Unexpected prompt'))
    install = Mock()
    monkeypatch.setattr(tad, '_install_tad', install)
    messages: list[str] = []
    tad.setup_optional_tad(tmp_path, None, messages.append)
    install.assert_not_called()
    assert 'reused' in messages[-1]


@pytest.mark.parametrize('answer,expected', [('n', False), ('', True), ('yes', True)])
def test_optional_prompt(tad: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, answer: str, expected: bool) -> None:
    """
    Explain third-party ownership and honor the user's optional installation choice.
    """
    monkeypatch.setattr(tad, 'find_tad', lambda root: None)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: True)
    monkeypatch.setattr('builtins.input', lambda prompt: answer)
    install = Mock(return_value=tmp_path / 'Tad')
    monkeypatch.setattr(tad, '_install_tad', install)
    messages: list[str] = []
    tad.setup_optional_tad(tmp_path, None, messages.append)
    assert install.called is expected
    assert 'third-party' in messages[0] and 'does not manage its updates' in messages[0]


def test_failed_optional_install_keeps_fits_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tad: ModuleType) -> None:
    """
    A failed Tad download leaves the main installer successful and clearly reports both outcomes.
    """
    setup = importlib.import_module('setup')
    monkeypatch.setattr(setup, 'ROOT', tmp_path)
    monkeypatch.setattr(setup, 'require_independent_python', lambda root: None)
    monkeypatch.setattr(setup.Installer, 'install', lambda self, no_shortcut: None)
    monkeypatch.setattr(tad, 'find_tad', lambda root: None)
    monkeypatch.setattr(tad, '_install_tad', Mock(side_effect=OSError('Download failed')))
    monkeypatch.setattr(setup.subprocess, 'run', lambda *args, **kwargs: tad.setup_optional_tad(
        tmp_path, True, setup.Installer(tmp_path).message))
    monkeypatch.setattr(sys, 'argv', ['setup.py', '--with-tad'])
    assert setup.main() == 0
    log = (tmp_path / 'startup/logs/install.log').read_text()
    assert 'Optional Tad installation was unsuccessful' in log
    assert log.rstrip().endswith('FITS installed successfully and is ready to use.')


def test_noninteractive_install_does_not_download(tad: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Unattended setup requires explicit opt-in before downloading the viewer.
    """
    monkeypatch.setattr(tad, 'find_tad', lambda root: None)
    monkeypatch.setattr(sys.stdin, 'isatty', lambda: False)
    install = Mock()
    monkeypatch.setattr(tad, '_install_tad', install)
    tad.setup_optional_tad(tmp_path, None, lambda message: None)
    tad.setup_optional_tad(tmp_path, False, lambda message: None)
    install.assert_not_called()


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux archive and executable permissions')
def test_linux_archive_install_and_reuse(tad: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Install the upstream archive layout while retaining executable permissions and licence files.
    """
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w:bz2') as contents:
        for name, data, mode in [('tad-0.14.0/tad', b'#!/bin/sh\n', 0o755),
                                 ('tad-0.14.0/LICENSE', b'Tad license', 0o644)]:
            info = tarfile.TarInfo(name)
            info.size, info.mode = len(data), mode
            contents.addfile(info, io.BytesIO(data))
    monkeypatch.setattr(tad, 'urlopen', lambda url, timeout: io.BytesIO(archive.getvalue()))
    monkeypatch.setattr(tad.platform, 'machine', lambda: 'x86_64')
    executable = tad._install_tad(tmp_path, lambda message: None)
    assert executable == tmp_path / 'startup/tools/Tad/tad'
    assert (executable.parent / 'LICENSE').read_text() == 'Tad license'
    assert tad.find_tad(tmp_path) == executable


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux desktop launcher')
def test_clickable_launcher_handles_relocated_paths(tmp_path: Path) -> None:
    """
    Resolve the startup installer even when its checkout path contains shell characters.
    """
    entry = Path(__file__).resolve().parents[2] / 'install_linux.desktop'
    root = tmp_path / 'FITS spaces $ ` % "'
    root.mkdir()
    launcher = root / entry.name
    launcher.write_bytes(entry.read_bytes())
    (root / 'startup').mkdir()
    (root / 'startup/install_linux.sh').write_text('printf "%s" "$1"')
    command = next(line[5:] for line in entry.read_text().splitlines() if line.startswith('Exec='))
    # Decode the desktop-entry string layer, then its Exec quoting and field codes.
    command = command.replace('\\\\', '\\')
    # Unlike GLib's Exec parser, shlex preserves escaped dollar signs in quotes.
    arguments = [argument.replace('%%', '%').replace('\\$', '$') for argument in shlex.split(command)]
    arguments[-1] = str(launcher)
    result = subprocess.run(arguments, check=True, text=True, capture_output=True, cwd=tmp_path)
    assert result.stdout == '--pause'


def test_windows_install_uses_current_user_and_reuses_result(tad: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """
    Pass the NSIS destination with spaces correctly, then detect the installed executable.
    """
    monkeypatch.setattr(tad.sys, 'platform', 'win32')
    monkeypatch.setattr(tad.shutil, 'which', lambda name: None)
    monkeypatch.setattr(tad.platform, 'machine', lambda: 'AMD64')
    monkeypatch.setattr(tad, 'urlopen', lambda url, timeout: io.BytesIO(b'installer'))
    destination = tmp_path / 'FITS with spaces/startup/tools/Tad'
    commands: list[str] = []

    def install(command: str, check: bool) -> None:
        """
        Simulate the vendor installer writing its per-user application.
        """
        assert check
        commands.append(command)
        destination.mkdir(parents=True)
        executable = destination / 'Tad.exe'
        executable.touch()
        executable.chmod(0o755)

    monkeypatch.setattr(tad.subprocess, 'run', install)
    executable = tad._install_tad(tmp_path / 'FITS with spaces', lambda message: None)
    assert executable == destination / 'Tad.exe'
    assert commands[0].endswith(f' /S /currentuser /D={destination}')
    assert tad.find_tad(tmp_path / 'FITS with spaces') == executable
