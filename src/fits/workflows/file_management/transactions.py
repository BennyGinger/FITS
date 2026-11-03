"""Reviewed file moves and atomic rewrites with rollback; no image processing."""

from __future__ import annotations

from types import TracebackType
from typing import Self
from pathlib import Path
import os
import shutil
import tempfile


class FileUpdate:
    def __init__(self, root: Path) -> None:
        """
        Initialize the FileUpdate state and dependencies.
        """
        parent = root / '.fits'
        parent.mkdir(parents=True, exist_ok=True)
        self.backup = Path(tempfile.mkdtemp(prefix='file_update_', dir=parent))
        self.saved: dict[Path, Path | None] = {}
        self.moves: list[tuple[Path, Path]] = []
        self.directories: list[Path] = []

    def parents(self, directory: Path) -> None:
        """
        Create missing parent directories and record them for rollback.
        """
        missing = []
        while not directory.exists():
            missing.append(directory)
            directory = directory.parent
        for path in reversed(missing):
            path.mkdir()
            self.directories.append(path)

    def protect(self, path: Path) -> None:
        """
        Retain the current file revision before replacing it.
        """
        path = Path(path)
        if path in self.saved:
            return
        if path.is_file():
            backup = self.backup / str(len(self.saved))
            try:
                os.link(path, backup)
            except OSError:
                shutil.copy2(path, backup)
            self.saved[path] = backup
        else:
            self.saved[path] = None

    def move(self, source: Path, target: Path) -> None:
        """
        Move a file or directory and record its inverse operation.
        """
        source, target = Path(source), Path(target)
        if source == target:
            return
        if target.exists():
            raise ValueError(f'Destination already exists: {target}')
        self.parents(target.parent)
        source.replace(target)
        self.moves.append((source, target))

    def rollback(self) -> None:
        """
        Restore protected files, reverse moves and remove newly created directories.
        """
        failures = []
        for path, backup in reversed(list(self.saved.items())):
            try:
                if backup is None:
                    path.unlink(missing_ok=True)
                else:
                    os.replace(backup, path)
            except OSError as error:
                failures.append(str(error))
        for source, target in reversed(self.moves):
            try:
                target.replace(source)
            except OSError as error:
                failures.append(str(error))
        for path in reversed(self.directories):
            try:
                path.rmdir()
            except OSError:
                pass
        if failures:
            raise RuntimeError(f'Rollback needs review; backups retained at {self.backup}: {failures}')

    def __enter__(self) -> Self:
        """
        Return the active file-update transaction.
        """
        return self

    def __exit__(self,
                 error_type: type[BaseException] | None,
                 error: BaseException | None,
                 traceback: TracebackType | None,
                 ) -> None:
        """
        Roll back failed updates and release temporary backups.
        """
        if error_type is not None:
            self.rollback()
        shutil.rmtree(self.backup)
