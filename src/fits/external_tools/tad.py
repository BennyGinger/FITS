"""Discover and optionally install the independent Tad table viewer."""

from __future__ import annotations

import argparse
from collections.abc import Callable
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
from urllib.request import urlopen


TAD_WEBSITE = 'https://www.tadviewer.com/'
TAD_VERSION = '0.14.0'
RELEASE_URL = f'https://github.com/antonycourtney/tad/releases/download/v{TAD_VERSION}'


def find_tad(root: Path) -> Path | None:
    """
    Locate an existing Tad executable without requiring a Python environment.
    """
    executable = 'Tad.exe' if sys.platform == 'win32' else 'tad'
    candidates = [root / 'startup' / 'tools' / 'Tad' / executable]
    installed = shutil.which(executable)
    # The unrelated Node.js test runner also installs a command named tad.
    # Resolve launcher symlinks before checking for the viewer's Electron bundle.
    if installed and (Path(installed).resolve().parent / 'resources' / 'app.asar').is_file():
        candidates.append(Path(installed))
    if sys.platform == 'win32':
        for variable in ('LOCALAPPDATA', 'ProgramFiles', 'ProgramFiles(x86)'):
            if directory := os.environ.get(variable):
                candidates.extend((Path(directory) / 'Programs' / 'Tad' / executable,
                                   Path(directory) / 'Tad' / executable,
                                   ))
    else:
        candidates.extend((Path('/opt/Tad/tad'), Path('/opt/tad/tad')))
    return next((path for path in candidates if path.is_file() and os.access(path, os.X_OK)), None)


def launch_tad(root: Path, parquet: Path) -> subprocess.Popen[bytes]:
    """
    Open a file in a separate Tad process; callers handle unavailable-viewer feedback.
    """
    executable = find_tad(root)
    if executable is None:
        raise FileNotFoundError(f'Tad is not installed. Install it from {TAD_WEBSITE}')
    return subprocess.Popen([str(executable), str(parquet.resolve())])


def _install_tad(root: Path, report: Callable[[str], None]) -> Path:
    """
    Download the pinned upstream distribution and install without administrator access.
    """
    if sys.platform not in ('linux', 'win32'):
        raise RuntimeError('Automatic Tad installation supports Linux and Windows only. Install Tad from its website on macOS.')
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        raise RuntimeError('Automatic Tad installation currently supports x86-64 machines only.')
    asset = f'Tad-Setup-{TAD_VERSION}.exe' if sys.platform == 'win32' else f'tad-{TAD_VERSION}.tar.bz2'
    tools = root / 'startup' / 'tools'
    tools.mkdir(parents=True, exist_ok=True)
    destination = tools / 'Tad'
    with tempfile.TemporaryDirectory(prefix='tad-download-', dir=tools) as temporary:
        staging = Path(temporary)
        archive = staging / asset
        report(f'Downloading Tad {TAD_VERSION} from its official release (approximately 180–225 MB)…')
        with urlopen(f'{RELEASE_URL}/{asset}', timeout=60) as source, archive.open('wb') as target:
            shutil.copyfileobj(source, target)
        if sys.platform == 'win32':
            # NSIS requires /D last and unquoted, including when its path has spaces.
            command = subprocess.list2cmdline([str(archive), '/S', '/currentuser'])
            subprocess.run(f'{command} /D={destination}', check=True)
        else:
            unpacked = staging / 'unpacked'
            with tarfile.open(archive) as distribution:
                distribution.extractall(unpacked, filter='data')
            executable = next(path for path in unpacked.rglob('tad') if path.is_file() and os.access(path, os.X_OK))
            if destination.exists():
                raise RuntimeError(f'An incomplete Tad installation exists at {destination}. Remove it before retrying.')
            shutil.move(str(executable.parent), destination)
    executable = find_tad(root)
    if executable is None:
        raise RuntimeError('The Tad installer finished but its executable could not be found.')
    return executable


def setup_optional_tad(root: Path, requested: bool | None, report: Callable[[str], None]) -> None:
    """
    Offer Tad independently, keeping optional installation failures nonfatal for FITS.
    """
    if requested is False:
        report('Optional Tad installation skipped.')
        return
    existing = find_tad(root)
    if existing is not None:
        report(f'Existing Tad installation reused: {existing}')
        return
    report('\nTad is an optional third-party application for viewing Parquet tables.\n'
           'It is developed and maintained independently of FITS. FITS can install it\n'
           'for convenience, but does not manage its updates.')
    if sys.platform == 'darwin':
        report(f'On macOS, install Tad separately from {TAD_WEBSITE}')
        return
    if requested is None:
        if sys.stdin is None or not sys.stdin.isatty():
            report('Tad was not installed. Rerun interactively or use --with-tad to install it.')
            return
        try:
            answer = input('Install Tad for viewing Parquet tables? [Y/n] ').strip().lower()
        except (EOFError, KeyboardInterrupt):
            report('\nOptional Tad installation skipped.')
            return
        if answer not in ('', 'y', 'yes'):
            report('Optional Tad installation skipped.')
            return
    try:
        executable = _install_tad(root, report)
    except (OSError, RuntimeError, subprocess.SubprocessError, tarfile.TarError, StopIteration, KeyboardInterrupt) as error:
        report(f'Optional Tad installation was unsuccessful: {error}\nYou can install it separately from {TAD_WEBSITE}')
        return
    report(f'Tad installed successfully: {executable}')


def main() -> None:
    """
    Offer the viewer from the newly installed FITS environment.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('root', type=Path)
    choice = parser.add_mutually_exclusive_group()
    choice.add_argument('--with-tad', dest='tad', action='store_true')
    choice.add_argument('--without-tad', dest='tad', action='store_false')
    parser.set_defaults(tad=None)
    arguments = parser.parse_args()
    setup_optional_tad(arguments.root, arguments.tad, print)


if __name__ == '__main__':
    main()
